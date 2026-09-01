"""skill_router.py —— 技能路由中间件（轻量实现，纯标准库零依赖）

参考 SkillRouter（arXiv:2603.22455 / github.com/zhengyanzhao1997/SkillRouter）
的「retrieve-and-rerank + body-aware」方法论：当 skills 数量膨胀、无法全部暴露
给 Agent 时，由本中间件按「任务描述」从中央仓库检索-重排出 top-K 该激活的 skill，
供 Manager / Leader / MCP 消费。

两阶段设计（对齐论文，但轻量化到单机标准库可跑）：
- Stage 1 检索（召回）：对每个 skill 的 frontmatter（description + assign_when）
  与正文分别做 TF-IDF，取融合分 top-N 作为候选集。
- Stage 2 重排（精排）：body-aware —— 论文核心洞见是「只看 description 会漏」，
  正文包含真正触发细节，故精排融合「描述相关性 + 正文相关性」，并叠加两个强信号：
  ① description 中「触发词：…」的命中；② 目标 Worker 角色与 assign_when 的匹配。

典型规模：本项目 20+ skills 秒级；官方 80K 规模需上 0.6B/1.2B 模型（见
references/refs/skillrouter 与 references/theory/SKILL-ROUTER-EVALUATION.md）。

用法：
    from skill_router import SkillRouter
    router = SkillRouter()                       # 默认扫描 ../../skills/
    hits = router.route("修复登录接口空指针", top_k=3, worker="fixer")
    print(router.to_json(hits))

CLI：
    python src/skill_router.py --query "修复登录接口空指针" --top-k 3 --worker fixer --json
    python src/skill_router.py --list            # 列出已索引 skills
    python src/skill_router.py --validate        # 校验全部 frontmatter
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S | re.M)
REQUIRED_FIELDS = ("name", "description")
# assign_when 缺失时从 description 的英文 "Use when ..." / 中文「…时分配」段提取触发词
USE_WHEN_RE = re.compile(r"(?:use when|used when|when user|…时分配|时分配|当用户)", re.I)
# 英文词 or 连续中文片段（中文章节按重叠 bigram 切分，参照论文的 token 粒度）
TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+")

STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "with", "from", "by", "at", "as", "be", "this", "that", "it", "its", "if",
    "then", "else", "do", "does", "not", "no", "can", "will", "should", "must",
    "use", "using", "used", "via", "per", "each", "all", "any", "into", "out",
    "we", "you", "they", "them", "your", "our", "their", "about", "after",
    # 中文高频停用（bigram 粒度）
    "一个", "以及", "用于", "进行", "通过", "包括", "需要", "提供", "确保",
    "生成", "输出", "输入", "处理", "完成", "执行", "根据", "相关", "同时",
    "以及", "如果", "否则", "其中", "以及", "以及", "作为", "这是", "这个",
    "产生", "返回", "直接", "所有", "每个", "任何", "多个", "指定",
}

# 触发词强信号前缀（description 中「触发词：xxx、yyy」段落）
TRIGGER_MARKER = "触发词"

# Worker 角色中英文别名（assign_when 多为中文角色名，如「修复工程师」）
WORKER_ALIASES = {
    "leader": ["leader", "编排", "经理", "manager", "lead"],
    "aggregator": ["aggregator", "产品", "需求", "aggr"],
    "rootcause": ["rootcause", "根因", "架构"],
    "frontend": ["frontend", "前端"],
    "backend": ["backend", "后端"],
    "fixer": ["fixer", "修复", "补丁", "修理工"],
    "tester": ["tester", "测试", "验证"],
    "releaser": ["releaser", "发布", "运维", "devops"],
    "retrospector": ["retrospector", "复盘"],
}


class SkillRouterError(Exception):
    """skill 中央仓库解析/校验错误。"""


@dataclass
class SkillDoc:
    """一份 SKILL.md 的解析结果。"""

    name: str
    description: str
    assign_when: str
    body: str
    path: Path
    tokens: Counter = field(default_factory=Counter)  # frontmatter + body 全量 token


@dataclass
class RouteHit:
    """一次路由命中的结果项。"""

    rank: int
    skill: str
    score: float
    reasons: list
    path: str


def tokenize(text: str) -> list[str]:
    """中英混合分词：英文/数字按词，连续中文按重叠 bigram，过滤停用词。"""
    tokens: list[str] = []
    for seg in TOKEN_RE.findall(text.lower()):
        if re.fullmatch(r"[a-zA-Z0-9_]+", seg):
            if seg not in STOPWORDS:
                tokens.append(seg)
        else:
            for i in range(len(seg) - 1):
                bigram = seg[i : i + 2]
                if bigram not in STOPWORDS:
                    tokens.append(bigram)
    return tokens


def _parse_frontmatter(block: str) -> dict:
    """解析 YAML frontmatter（key: value 扁平行，容错注释、空行与引号）。"""
    fm: dict = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip("\"'")
    return fm


def _extract_assign_when(fm: dict) -> str:
    """assign_when 缺失时从 description 的 Use-when 段提取触发描述。"""
    desc = fm.get("description", "")
    m = USE_WHEN_RE.search(desc)
    if m:
        return desc[max(0, m.start() - 6) :]
    return ""


class SkillRouter:
    """技能路由中间件：索引中央仓库 + 检索重排 + 校验。"""

    def __init__(
        self,
        skills_dir: Optional[str | Path] = None,
        strict: bool = False,
    ):
        self.skills_dir = Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR
        self.skills: list[SkillDoc] = []
        self.idf: dict[str, float] = {}
        self.errors: list[str] = []
        self.build_index(strict=strict)

    # ---------- 索引 ----------

    def build_index(self, strict: bool = False) -> int:
        """扫描 skills/<name>/SKILL.md 建立内存索引，返回 skill 数量。

        :param strict: True 时坏文档直接抛 SkillRouterError（索引必须全合法）；
            False（默认）时坏文档跳过并记入 self.errors，保证 validate/路由鲁棒。
        """
        self.skills = []
        self.errors = []
        for path in sorted(self.skills_dir.glob("*/SKILL.md")):
            try:
                self.skills.append(self._parse(path))
            except SkillRouterError as exc:
                if strict:
                    raise
                self.errors.append(str(exc))
        self._compute_idf()
        return len(self.skills)

    def _parse(self, path: Path) -> SkillDoc:
        text = path.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        if not m:
            raise SkillRouterError(f"{path}: 缺少 frontmatter（--- 开头）")
        fm = _parse_frontmatter(m.group(1))
        missing = [f for f in REQUIRED_FIELDS if not fm.get(f)]
        if missing:
            raise SkillRouterError(f"{path}: frontmatter 缺字段 {missing}")
        if path.parent.name != fm["name"]:
            raise SkillRouterError(
                f"{path}: 目录名 {path.parent.name} 与 name {fm['name']} 不一致"
            )
        assign_when = fm.get("assign_when") or _extract_assign_when(fm)
        body = text[m.end() :]
        tokens = Counter(
            tokenize(f"{fm['description']} {assign_when} {body}")
        )
        return SkillDoc(
            name=fm["name"],
            description=fm["description"],
            assign_when=assign_when,
            body=body,
            path=path,
            tokens=tokens,
        )

    def _compute_idf(self) -> None:
        n = max(len(self.skills), 1)
        df: Counter = Counter()
        for doc in self.skills:
            df.update(doc.tokens.keys())
        self.idf = {
            token: math.log((n + 1) / (count + 1)) + 1.0
            for token, count in df.items()
        }

    # ---------- 检索-重排 ----------

    def route(
        self,
        query: str,
        top_k: int = 3,
        worker: Optional[str] = None,
    ) -> list[RouteHit]:
        """把任务描述路由到 top-K 个该激活的 skill。

        :param query: 任务/问题描述（如「修复登录接口空指针」）。
        :param top_k: 返回的推荐数量。
        :param worker: 目标 Worker 名（如 fixer），用于 assign_when 角色匹配加分。
        """
        qvec = Counter(tokenize(query))
        if not qvec:
            return []

        # Stage 1 检索：TF-IDF 打分全量参与（0 分也进候选池兜底），取 top-N
        n_cand = max(top_k * 3, 8)
        scored = [(self._tfidf_score(qvec, doc), doc) for doc in self.skills]
        scored.sort(key=lambda x: x[0], reverse=True)
        candidates = [doc for _, doc in scored[:n_cand]]

        # Stage 2 重排：body-aware 细打分（含触发词/角色强信号）
        ranked = [self._rerank(query, qvec, doc, worker) for doc in candidates]
        ranked.sort(key=lambda x: x.score, reverse=True)

        hits = []
        for i, item in enumerate(ranked[:top_k], start=1):
            hits.append(
                RouteHit(
                    rank=i,
                    skill=item.skill,
                    score=round(item.score, 4),
                    reasons=item.reasons,
                    path=str(item.path),
                )
            )
        return hits

    def _tfidf_score(self, qvec: Counter, doc: SkillDoc) -> float:
        """TF-IDF 余弦近似：query token 权重与 doc token 重合的加权和。"""
        score = 0.0
        for token, qtf in qvec.items():
            if token in doc.tokens and token in self.idf:
                score += qtf * self.idf[token] * math.log1p(doc.tokens[token])
        return score

    def _rerank(self, query: str, qvec: Counter, doc: SkillDoc, worker: Optional[str]):
        """body-aware 精排：0.6 描述相关性 + 0.4 正文相关性 + 触发词 + 角色匹配。"""
        desc_text = f"{doc.description} {doc.assign_when}"
        body_text = doc.body
        desc_doc = Counter(tokenize(desc_text))
        body_doc = Counter(tokenize(body_text))

        desc_score = self._field_score(qvec, desc_doc)
        body_score = self._field_score(qvec, body_doc)
        score = 0.6 * desc_score + 0.4 * body_score

        reasons: list[str] = []

        # 强信号 1：description「触发词：…」命中（对齐论文的 trigger-aware 发现）
        trig_part = self._trigger_part(doc.description)
        if trig_part:
            hit_trig = [t for t in qvec if t in tokenize(trig_part)]
            if hit_trig:
                score += 1.2
                reasons.append(f"触发词命中: {', '.join(hit_trig)}")

        # 强信号 2：Worker 角色与 assign_when 匹配（中英文别名）
        if worker and any(
            alias in doc.assign_when.lower()
            for alias in WORKER_ALIASES.get(worker.lower(), [worker.lower()])
        ):
            score += 0.8
            reasons.append(f"角色匹配: {worker}")

        if body_score > 0:
            reasons.append(f"正文相关: {round(body_score, 3)}")
        if not reasons:
            reasons.append(f"描述相关: {round(desc_score, 3)}")
        return _Reranked(skill=doc.name, score=score, reasons=reasons, path=doc.path)

    def _field_score(self, qvec: Counter, doc_tokens: Counter) -> float:
        score = 0.0
        for token, qtf in qvec.items():
            if token in doc_tokens and token in self.idf:
                score += qtf * self.idf[token] * math.log1p(doc_tokens[token])
        return score

    @staticmethod
    def _trigger_part(description: str) -> str:
        idx = description.find(TRIGGER_MARKER)
        if idx == -1:
            return ""
        return description[idx:]

    # ---------- 校验 ----------

    def validate(self) -> list[str]:
        """校验所有 SKILL.md 的 frontmatter 完整性，返回错误列表（空 = 全通过）。"""
        self.build_index()  # 重新扫描收集最新错误（坏文档跳过，不抛错）
        return list(self.errors)

    # ---------- 输出 ----------

    def to_json(self, hits: list[RouteHit]) -> str:
        return json.dumps(
            {"router": "skill_router", "hits": [asdict(h) for h in hits]},
            ensure_ascii=False,
            indent=2,
        )


@dataclass
class _Reranked:
    skill: str
    score: float
    reasons: list
    path: Path


# ---------- CLI ----------

def _cli(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="skill_router",
        description="技能路由中间件：从 skills 中央仓库检索-重排 top-K 该激活的 skill。",
    )
    parser.add_argument("--query", help="任务/问题描述，用于路由")
    parser.add_argument("--top-k", type=int, default=3, help="返回推荐数（默认 3）")
    parser.add_argument("--worker", help="目标 Worker 名（如 fixer），角色匹配加分")
    parser.add_argument("--skills-dir", help="skills 中央仓库路径（默认 ../../skills/）")
    parser.add_argument("--list", action="store_true", help="列出已索引 skills")
    parser.add_argument("--validate", action="store_true", help="校验全部 frontmatter")
    parser.add_argument("--json", action="store_true", help="JSON 输出（路由结果）")
    args = parser.parse_args(argv)

    try:
        router = SkillRouter(skills_dir=args.skills_dir)
    except SkillRouterError as exc:
        print(f"[skill_router] 索引失败: {exc}", file=sys.stderr)
        return 1

    if args.validate:
        errors = router.validate()
        if errors:
            print(f"[skill_router] 校验失败 {len(errors)} 项:")
            for err in errors:
                print(f"  - {err}")
            return 1
        print(f"[skill_router] 校验通过：{len(router.skills)} 个 skills 全部合法")
        return 0

    if args.list:
        print(f"[skill_router] 已索引 {len(router.skills)} 个 skills：")
        for doc in router.skills:
            print(f"  - {doc.name}  ({doc.path})")
        return 0

    if not args.query:
        parser.print_help()
        return 2

    hits = router.route(args.query, top_k=args.top_k, worker=args.worker)
    if args.json:
        print(router.to_json(hits))
    else:
        print(f"[skill_router] query: {args.query!r}  ->  top-{len(hits)}")
        for h in hits:
            print(f"  #{h.rank} {h.skill}  score={h.score}")
            for reason in h.reasons:
                print(f"      · {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
