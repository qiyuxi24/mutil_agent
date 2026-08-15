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
WORKERS_YAML = PROJECT / "src" / "agentteams" / "workers.yaml"
SKILLS_DIR = PROJECT / "skills"

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


def collect_referenced_skills() -> tuple[dict, list]:
    """返回 ({worker: [skills]}, 去重后的全部 skill 名)。"""
    if not WORKERS_YAML.exists():
        raise FileNotFoundError(f"找不到 {WORKERS_YAML}")
    text = WORKERS_YAML.read_text(encoding="utf-8")
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
            # YAML 解析失败时退化为正则
            per_worker, all_skills = {}, []
    if not per_worker:
        # 正则兜底：按 "---" 分割每个文档，找 name + skills
        for doc_text in re.split(r"^---\s*$", text, flags=re.M):
            name_m = re.search(r"^metadata:\s*$.*?^  name:\s*([\w-]+)", doc_text, re.S)
            if not name_m:
                continue
            name = name_m.group(1)
            skills = _regex_skills(doc_text)
            if skills:
                per_worker[name] = skills
                all_skills.extend(skills)
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
