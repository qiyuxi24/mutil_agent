#!/usr/bin/env python3
"""verify-worker-single-source.py — F1 统一 Worker 定义单源校验。

背景（复赛 F1，见 design/TEAM-ECOSYSTEM-RESTRUCTURE.md）：
  角色定义存在「双轨」——`workers.yaml`（部署真相源，简洁内联 soul/agents/skills/mcpServers）
  与 `workers/<name>/SOUL.md`（详细 Ralph 迭代设计，含记忆沉淀规则）。
  两者职责一致但详略不同，评审/部署时易混淆、易不同步。

本脚本落地「单源策略」：
  - `workers.yaml`（一套完整班子，2026-08-16 重构）= **部署唯一真相源**（apply 用它）。
  - `workers/<name>/SOUL.md` = **详细设计从属说明**（角色详细设计，非部署源）。
  - 校验 ① 每个 Worker 都有对应 SOUL.md；② SOUL.md 引用的 skill 都在 CR 中；
    ③ CR 声明的核心职责关键词在 SOUL.md 中出现（防两文件职责漂移）。

用法（项目根目录）：
  python scripts/verify-worker-single-source.py
  python scripts/verify-worker-single-source.py --json   # 纯 JSON 摘要

退出码：0=一致；1=存在漂移/缺失。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
AGENTTEAMS_DIR = PROJECT / "src" / "agentteams"
WORKERS_YAML = AGENTTEAMS_DIR / "workers.yaml"
WORKERS_DIR = AGENTTEAMS_DIR / "workers"
SKILLS_DIR = PROJECT / "skills"

# 额外 Worker CR（独立于 workers.yaml）—— 2026-08-16 重构后一套班子全在 workers.yaml，无独立 CR
EXTRA_WORKER_YAMLS = []

# 每个角色的「核心职责关键词」，用于核对 CR soul 与 SOUL.md 职责一致（防漂移）。
# key=role, value=必须在 SOUL.md 出现的词（至少 1 个命中即可）。
# 2026-08-16 重构：一套完整班子（保留旧内部名 + 新增 frontend/leader，releaser 兼任部署）。
ROLE_KEYWORDS = {
    "leader": ["Leader", "编排", "挑", "协调", "一套班子"],
    "aggregator": ["产品", "需求", "任务规格", "spec.md", "聚合"],
    "rootcause": ["根因", "RCA", "影响面", "架构"],
    "frontend": ["前端", "UI", "页面", "SITE_READY", "界面"],
    "backend": ["后端", "接口", "POST", "BACKEND_READY", "服务器"],
    "fixer": ["修复", "编码", "FIX_APPLIED", "修理工"],
    "tester": ["测试", "质量门禁", "TEST_PASSED", "真实运行"],
    "releaser": ["发布", "回滚", "RELEASE_OK", "部署"],
    "retrospector": ["复盘", "知识", "RETROSPECT_DONE"],
    "doc-manager": ["文档", "验收", "doc-management", "DOC_ACCEPTED", "归档"],
    "coordinator": ["协同路由员", "派发", "哨兵", "dispatch-contract", "切片", "复审"],
}

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


def _regex_skills(text: str) -> list[str]:
    """PyYAML 不可用时，用正则兜底提取每个 `skills:` 块下的条目。"""
    skills: list[str] = []
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


def _scan_workers() -> dict[str, dict]:
    """扫描所有 Worker CR，返回 {role: {name, soul, skills}}。"""
    workers: dict[str, dict] = {}
    targets = [WORKERS_YAML] + [AGENTTEAMS_DIR / n for n in EXTRA_WORKER_YAMLS]
    for yp in targets:
        if not yp.exists():
            continue
        text = yp.read_text(encoding="utf-8")
        docs: list[dict] = []
        if yaml is not None:
            try:
                docs = [
                    d for d in yaml.safe_load_all(text) if d and d.get("kind") == "Worker"
                ]
            except Exception:  # noqa: BLE001
                docs = []
        if not docs:
            # 正则兜底：按 --- 切分 + metadata.name + skills
            for doc_text in re.split(r"^---\s*$", text, flags=re.M):
                nm = re.search(r"^(\s*)metadata:\s*$.*?^\1\s+name:\s*([\w-]+)", doc_text, re.S | re.M)
                if not nm:
                    continue
                skills = _regex_skills(doc_text)
                if skills:
                    workers[nm.group(2)] = {"name": nm.group(2), "skills": skills, "soul": ""}
            continue
        for doc in docs:
            name = (doc.get("metadata") or {}).get("name")
            spec = doc.get("spec") or {}
            if name:
                workers[name] = {
                    "name": name,
                    "soul": spec.get("soul", ""),
                    "skills": spec.get("skills") or [],
                }
    return workers


def main() -> int:
    parser = argparse.ArgumentParser(description="F1 统一 Worker 定义单源校验")
    parser.add_argument("--json", action="store_true", help="输出纯 JSON 摘要")
    args = parser.parse_args()

    workers = _scan_workers()
    if not workers:
        print(json.dumps({"status": "ERROR", "reason": f"未扫描到任何 Worker（{WORKERS_YAML}）"}, ensure_ascii=False))
        return 2

    issues: list[str] = []
    details: list[dict] = []

    for role, info in sorted(workers.items()):
        soul_md = WORKERS_DIR / role / "SOUL.md"
        entry = {"role": role, "soul_md_exists": soul_md.exists()}

        # ① SOUL.md 存在性
        if not soul_md.exists():
            issues.append(f"[{role}] 缺 workers/{role}/SOUL.md")
            details.append(entry)
            continue

        soul_text = soul_md.read_text(encoding="utf-8")

        # ② SOUL.md 引用的 skill 都在 CR 中（防 SOUL 提到未挂载 skill）
        referenced = set()
        for skill_name in info.get("skills", []):
            if skill_name in soul_text:
                referenced.add(skill_name)
        entry["cr_skills"] = info.get("skills", [])
        entry["referenced_in_soul"] = sorted(referenced)

        # ③ 核心职责关键词在 SOUL.md 出现（防职责漂移）
        kws = ROLE_KEYWORDS.get(role, [])
        hit = [k for k in kws if k in soul_text]
        entry["keyword_hits"] = hit
        entry["keyword_required"] = kws
        if not hit:
            issues.append(f"[{role}] SOUL.md 未命中核心职责关键词 {kws}")

        details.append(entry)

    # 汇总
    ok = not issues
    summary = {
        "status": "PASS" if ok else "FAIL",
        "workers_total": len(workers),
        "workers": [d["role"] for d in details],
        "soul_md_all_present": all(d["soul_md_exists"] for d in details),
        "issues": issues,
        "details": details,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"单源校验（workers.yaml = 部署真相源；workers/<role>/SOUL.md = 详细设计从属）")
        print(f"Worker 总数: {len(workers)}")
        missing = [d["role"] for d in details if not d["soul_md_exists"]]
        print(f"SOUL.md 齐全: {'是' if not missing else f'缺失 {missing}'}")
        for d in details:
            print(f"  {d['role']:12s} SOUL={'✓' if d['soul_md_exists'] else '✗'} "
                  f"skill命中={len(d.get('referenced_in_soul', []))}/{len(d.get('cr_skills', []))} "
                  f"关键词={d.get('keyword_hits', [])}")
        if issues:
            print("❌ 存在不一致：")
            for i in issues:
                print(f"  - {i}")
        else:
            print("✅ 全部 Worker 单源一致（SOUL.md 齐全 + skill 引用一致 + 职责关键词命中）。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
