"""scan-aris-skills.py —— 把上交大 ARIS 仓库的 skills 分门别类 + 路由冒烟

扫描 `Auto-claude-code-research-in-sleep/skills/` 主层 80 个 SKILL.md，
按领域关键词自动归类（文献/实验/写作/审计/专利/展示/证明/创意/基建/协作），
生成分类目录文档 `references/theory/ARIS-SKILLS-CATALOG.md`，并跑一组路由冒烟
验证 `src/skill_router.py` 在外部技能库上的检索-重排效果。

用法：
    python scripts/scan-aris-skills.py              # 扫描 + 生成目录 + 冒烟
    python scripts/scan-aris-skills.py --no-route   # 只扫描生成目录，不跑冒烟
    python scripts/scan-aris-skills.py --dir <ARIS>/skills   # 指定仓库路径

依赖：src/skill_router.py（纯标准库）。运行时需把 src 加进 sys.path。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from skill_router import SkillRouter  # noqa: E402

DEFAULT_ARIS_SKILLS = (
    ROOT.parent / "Auto-claude-code-research-in-sleep" / "skills"
)

# 分类规则：每项 (分类, 名称关键词, 描述关键词)，互斥设计——先按名称精确匹配，
# 未命中再按描述兜底；顺序即优先级（专利/证明/展示等特异领域放前面）。
CATEGORY_RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("专利撰写", ("patent", "claims", "specification", "embodiment",
                  "invention", "jurisdiction", "figure-description"),
     ("patent", "claims", "专利", "权利要求", "embodiment")),
    ("证明理论", ("proof-", "formula"),
     ("proof", "theorem", "prove", "推导公式", "证明")),
    ("展示汇报", ("slides", "poster", "talk", "interview", "cheatsheet"),
     ("slides", "poster", "talk", "演示", "汇报")),
    ("文献检索", ("arxiv", "lit-", "semantic", "openalex", "deepxiv",
                  "alphaxiv", "exa-search", "gemini-search", "research-lit",
                  "prior-art", "web-debug", "wiki"),
     ("search papers", "literature", "论文检索", "文献", "search")),
    ("审计复盘", ("audit", "integrity", "forensics", "novelty",
                  "kill-argument", "review", "meta-", "research-review"),
     ("audit", "review", "验证", "审计", "复核")),
    ("实验执行", ("experiment", "run-", "result-to-claim", "analyze-results",
                  "training-check", "ablation", "monitor", "system-profile",
                  "vast", "serverless", "qzcli", "modal", "queue"),
     ("experiment", "gpu", "训练", "实验", "跑")),
    ("论文写作", ("paper-", "writing", "render-html", "mermaid", "overleaf",
                  "rebuttal", "resubmit", "grant", "figure-spec",
                  "research-refine", "research-pipeline"),
     ("paper", "write", "写作", "论文")),
    ("创意发现", ("idea-", "dse-loop"),
     ("idea", "discovery", "创意", "发现")),
    ("协同协作", ("feishu", "team", "comm"),
     ("feishu", "通知", "协同")),
]


def classify(name: str, description: str) -> str:
    """先按名称关键词精确归类，未命中再按描述兜底。"""
    n = name.lower()
    d = description.lower()
    for category, name_kw, desc_kw in CATEGORY_RULES:
        if any(k in n for k in name_kw):
            return category
    for category, _, desc_kw in CATEGORY_RULES:
        if any(k in d for k in desc_kw):
            return category
    return "其他"

# 冒烟查询：中文任务 → 期望命中领域（用于人工核对，不硬断言）
SMOKE_QUERIES: list[tuple[str, int]] = [
    ("搜索并下载 arXiv 上的论文，生成摘要", 3),
    ("分析实验结果，生成对比表格与洞察", 3),
    ("撰写论文 rebuttal 回应评审意见", 3),
    ("检查论文引用真实性，审计参考文献", 3),
    ("撰写专利申请的权利要求书", 3),
    ("证明一个 ML 理论定理", 3),
    ("在 vast.ai 租 GPU 跑实验", 3),
    ("生成论文的 slides 演示文稿", 3),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_ARIS_SKILLS),
        help="ARIS skills 目录（默认 Auto-claude-code-research-in-sleep/skills）",
    )
    parser.add_argument("--no-route", action="store_true", help="跳过路由冒烟")
    args = parser.parse_args(argv)

    skills_dir = Path(args.dir)
    if not skills_dir.is_dir():
        print(f"[scan-aris] 目录不存在: {skills_dir}", file=sys.stderr)
        return 1

    # 1. 用 router 索引外部技能库（验证 ARIS 格式兼容 + 校验）
    router = SkillRouter(skills_dir=skills_dir)
    if router.errors:
        print(f"[scan-aris] ⚠️ {len(router.errors)} 个 skill 解析失败：")
        for err in router.errors:
            print(f"  - {err}")
    print(f"[scan-aris] 已索引 {len(router.skills)} 个 ARIS skills（主层）")

    # 2. 分门别类
    buckets: dict[str, list[str]] = {}
    for doc in router.skills:
        cat = classify(doc.name, doc.description)
        buckets.setdefault(cat, []).append(doc.name)

    order = [c for c, _, _ in CATEGORY_RULES if c in buckets]
    other = [c for c in buckets if c not in order]
    ordered = order + sorted(other)
    print(f"\n[scan-aris] 分类统计（共 {len(ordered)} 类）：")
    total = 0
    for cat in ordered:
        names = sorted(buckets[cat])
        total += len(names)
        print(f"  {cat:<8} {len(names):>2}  {', '.join(names[:8])}"
              + (" ..." if len(names) > 8 else ""))
    print(f"[scan-aris] 合计 {total} 个")

    # 3. 生成分类目录文档
    catalog = ROOT / "references" / "theory" / "ARIS-SKILLS-CATALOG.md"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# ARIS 技能分类目录（分门别类索引）",
        "",
        "> 由 `scripts/scan-aris-skills.py` 自动生成 · 来源：上交大 "
        "Auto-claude-code-research-in-sleep 仓库主层 skills/ · 生成日期：2026-08-31",
        "",
        "按领域自动归类（规则在脚本 `CATEGORY_RULES`），供 `skill_router` 路由冒烟与",
        "外部技能库复用参考。",
        "",
        "## 分类总览",
        "",
        "| 分类 | 数量 | skills |",
        "|---|---|---|",
    ]
    for cat in ordered:
        names = sorted(buckets[cat])
        lines.append(f"| {cat} | {len(names)} | {', '.join(names)} |")
    lines.append("")
    for cat in ordered:
        lines.append(f"## {cat}")
        lines.append("")
        for name in sorted(buckets[cat]):
            doc = next(d for d in router.skills if d.name == name)
            desc = doc.description.replace("\n", " ").strip()
            if len(desc) > 100:
                desc = desc[:100] + "…"
            lines.append(f"- **{name}** — {desc}")
        lines.append("")
    catalog.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[scan-aris] 目录文档已生成: {catalog.relative_to(ROOT)}")

    # 4. 路由冒烟
    if args.no_route:
        return 0
    print("\n[scan-aris] 路由冒烟（SkillRouter on ARIS skills）：")
    for query, top_k in SMOKE_QUERIES:
        hits = router.route(query, top_k=top_k)
        top = ", ".join(f"{h.skill}({h.score})" for h in hits[:3])
        print(f"  Q: {query}\n      → {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
