#!/usr/bin/env python3
"""verify-skill-refs.py
GAP-11  Skill 引用完整性核对。

遍历 `src/agentteams/workers.yaml` 每个 Worker 的 `spec.skills:` 列表，
核对 `skills/` 目录下是否有同名 `SKILL.md`。缺失项可自动建空壳占位。

用法（项目根目录）：
  python scripts/verify-skill-refs.py            # 只核对，输出缺失清单（退出码 0=全部存在）
  python scripts/verify-skill-refs.py --create   # 核对 + 为缺失项自动建空壳 SKILL.md 占位
  python scripts/verify-skill-refs.py --json     # 纯 JSON 摘要（供脚本/CI 消费）

退出码：0=无缺失（或已补齐）；1=存在缺失（未加 --create）；2=参数/解析错误。
"""
import argparse
import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
AGENTTEAMS_DIR = PROJECT / "src" / "agentteams"
WORKERS_YAML = AGENTTEAMS_DIR / "workers.yaml"
SKILLS_DIR = PROJECT / "skills"

# 额外扫描的 Worker CR 文件（2026-08-16 重构后：一套班子全部在 workers.yaml，无独立 CR）
# 原 hr/architect/backend/deployer 独立 CR 已删除并入一套班子（见 design/TEAM-REFACTOR-SINGLE-BANCHANG.md）
EXTRA_WORKER_YAMLS = []

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def _regex_skills(text: str) -> list:
    """PyYAML 不可用时，用正则兜底提取每个 `skills:` 块下的条目。"""
    skills = []
    # 以 "skills:" 开头缩进行为块起点，收集其下更缩进的 "- xxx" 项
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)skills:\s*(#.*)?$", lines[i])
        if m:
            indent = m.group(1)
            j = i + 1
            while j < len(lines):
                line = lines[j]
                if not line.strip() or line.strip().startswith("#") or line.strip().startswith("---"):
                    j += 1
                    continue
                sm = re.match(r"^(\s*)-[ \t]*([a-z0-9][a-z0-9-]*)(\s+#.*)?$", line)
                if sm and len(sm.group(1)) > len(indent):
                    skills.append(sm.group(2))
                    j += 1
                    continue
                break
            i = j
        else:
            i += 1
    return skills


def _scan_yaml_docs(yaml_path: Path) -> tuple[dict, list]:
    """扫描单个 YAML 文件里的所有 Worker CR，返回 (per_worker, all_skills)。"""
    text = yaml_path.read_text(encoding="utf-8")
    per_worker: dict = {}
    all_skills: list = []
    if yaml is not None:
        try:
            docs = list(yaml.safe_load_all(text))
            for doc in docs:
                if not doc or doc.get("kind") != "Worker":
                    continue
                name = (doc.get("metadata") or {}).get("name")
                skills = (doc.get("spec") or {}).get("skills") or []
                if name:
                    per_worker[name] = list(skills)
                    all_skills.extend(skills)
        except Exception:  # noqa: BLE001
            per_worker, all_skills = {}, []
    if not per_worker:
        for doc_text in re.split(r"^---\s*$", text, flags=re.M):
            # metadata/name 允许任意前导缩进（workers.yaml 的 CR 是缩进格式）
            # 需同时 re.M 让 ^ 匹配行首（metadata 顶格、name 缩进 2 空格）
            name_m = re.search(
                r"^(\s*)metadata:\s*$.*?^\1\s+name:\s*([\w-]+)", doc_text, re.S | re.M
            )
            if not name_m:
                continue
            name = name_m.group(2)
            skills = _regex_skills(doc_text)
            if skills:
                per_worker[name] = skills
                all_skills.extend(skills)
    return per_worker, all_skills


def collect_referenced_skills() -> tuple[dict, list]:
    """返回 ({worker: [skills]}, 去重后的全部 skill 名)。

    扫描 `workers.yaml`（修复模式 6 角色）+ `EXTRA_WORKER_YAMLS`（HR + 搭建角色），
    覆盖全团队生态的 skill 引用。文件缺失时静默跳过。
    """
    if not WORKERS_YAML.exists():
        raise FileNotFoundError(f"找不到 {WORKERS_YAML}")
    per_worker: dict = {}
    all_skills: list = []
    targets = [WORKERS_YAML] + [AGENTTEAMS_DIR / n for n in EXTRA_WORKER_YAMLS]
    for yp in targets:
        if not yp.exists():
            continue
        pw, sk = _scan_yaml_docs(yp)
        per_worker.update(pw)
        all_skills.extend(sk)
    # 去重保持顺序
    seen = set()
    uniq = [s for s in all_skills if not (s in seen or seen.add(s))]
    return per_worker, uniq


SHELL_TEMPLATE = """---
name: {name}
description: 【初赛占位，复赛补内容】{desc}
assign_when: {assign_when}
---

# Skill: {name}

> ⚠️ 初赛占位空壳：本 Skill 被 `workers.yaml` 引用但内容尚未编写。
> 复赛需补齐指令正文（对齐官方 9 字段：名称/用途/输入输出/调用条件/依赖工具/失败处理/安全边界/复用价值/协同关系）。

## 状态

- 本文件为 **L1 基座占位**，仅保证 `Worker.spec.skills` 挂载时 Skill 目录存在、引用不悬空。
- 复赛补内容后再渲染分发：`bash skills/scripts/render-skills.sh skills/{name}`

## 复赛待补

- 输入 / 输出契约
- 执行步骤（确定性优先）
- 依赖工具
- 失败处理
- 安全边界
"""


def shell_content(name: str, assign_when: str) -> str:
    """生成空壳 SKILL.md 内容。"""
    desc = {
        "git-operations": "Git 操作：分支/checkout/diff/blame/commit，安全提交审计",
        "code-search": "代码检索：ripgrep 全文 + 语义搜索，定位符号/调用/引用",
        "repo-context": "仓库结构感知：模块划分、依赖图、变更范围、构建入口",
        "knowledge-rag": "知识库检索/写入：查历史经验教训、已修复缺陷、失败模式",
        "evidence-log": "执行证据沉淀：把 Trace/Log/报告写入审计日志，可追溯",
        "team-management": "团队管理：组建/调整 Team，管理成员与群组",
        "project-management": "项目管理：任务拆解、进度跟踪、里程碑管理",
        "dynamic-hiring": "动态招人/裁员：按项目需求组建/回收 Agent 团队",
        "site-design": "站点架构设计：产出 design.md（页面+接口+数据模型）",
        "backend-impl": "后端实现：POST 接口 + 数据存储 + 启动脚本",
        "deploy-runtime": "部署运行：起服务到可访问地址 + 健康检查 + 回滚",
    }.get(name, "见 ASSIGNMENT-MATRIX.md 与该 Skill 分配")
    if assign_when == "见 ASSIGNMENT-MATRIX.md":
        assign_when = "需要" + desc.split("：", 1)[-1] if "：" in desc else "对应职能 Worker 执行时分配"
    return SHELL_TEMPLATE.format(name=name, desc=desc, assign_when=assign_when)


def main() -> int:
    parser = argparse.ArgumentParser(description="GAP-11 Skill 引用完整性核对")
    parser.add_argument("--create", action="store_true", help="为缺失项自动建空壳 SKILL.md 占位")
    parser.add_argument("--json", action="store_true", help="输出纯 JSON 摘要")
    args = parser.parse_args()

    try:
        per_worker, all_skills = collect_referenced_skills()
    except FileNotFoundError as e:
        print(json.dumps({"status": "ERROR", "reason": str(e)}, ensure_ascii=False))
        return 2

    missing = []
    existing = []
    for skill in all_skills:
        skill_dir = SKILLS_DIR / skill
        if (skill_dir / "SKILL.md").exists():
            existing.append(skill)
        else:
            missing.append(skill)

    created = []
    if args.create and missing:
        for skill in missing:
            skill_dir = SKILLS_DIR / skill
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                shell_content(skill, "见 ASSIGNMENT-MATRIX.md"), encoding="utf-8"
            )
            created.append(skill)
        missing = []

    ok = not missing
    summary = {
        "status": "PASS" if ok else "FAIL",
        "workers": list(per_worker.keys()),
        "referenced_skills_total": len(all_skills),
        "referenced_skills": all_skills,
        "existing": existing,
        "missing": missing,
        "created_shells": created,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"workers: {', '.join(summary['workers'])}")
        print(f"引用 skill 总数: {len(all_skills)}")
        print(f"已存在: {', '.join(existing) if existing else '(无)'}")
        if created:
            print(f"✅ 已建空壳占位: {', '.join(created)}")
        if missing:
            print(f"❌ 缺失: {', '.join(missing)}")
            print("提示: 运行 `python scripts/verify-skill-refs.py --create` 自动建空壳。")
        else:
            print("✅ 全部 Skill 引用均有对应 SKILL.md。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
