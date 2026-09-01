#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch_cli.py — 派发契约 CLI（Coordinator 协同路由员专用）

面向多 Agent 研发团队的派发契约化工具（L3 · Skill scripts 层，见 design/TOOLCHAIN.md）：
  - validate-brief  派发哨兵校验（fail-closed，缺验收标准即 BLOCKED）
  - template-brief  生成派发包七要素模板
  - validate-review 独立复审包协议校验
  - role-map        输出角色-模型映射表
  - schema          输出派发包 schema（人类可读）

设计原则：
  1. 解耦：自包含、不依赖本项目任何内部模块，可独立复制/测试。
  2. 零依赖：仅用 Python 标准库（argparse/json/sys），无第三方包。
  3. 声明式：ROLE_MAP / BRIEF_FIELDS / REVIEW_FIELDS 常量即声明式真相源，
     与 references/ 下的 Markdown 文档保持一致（文档为人类可读副本）。
  4. 确定性：同样输入产出同样判定，供 Worker 产出可审计的派发契约。

用法：
  python dispatch_cli.py validate-brief brief.json
  python dispatch_cli.py template-brief --outcome "..." --target backend --role executor \
      --scope "..." --checks '["pytest tests -q"]' --stop-when "..." --returns "..."
  python dispatch_cli.py validate-review review.json
  python dispatch_cli.py role-map [--json]
  python dispatch_cli.py schema

退出码：0 通过（PASS/ACCEPTED）；1 参数错误；2 校验失败（BLOCKED/REJECTED）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ============================================================
# 一、声明式配置（真相源，与 references/*.md 保持一致）
# ============================================================

WORKER_ROSTER = [
    "leader", "aggregator", "rootcause",
    "frontend", "backend", "fixer",
    "tester", "releaser", "retrospector",
    "doc-manager", "coordinator",
]

# 角色-模型映射（三角色理念，见 references/ROLE-MODEL-MAP.md）
ROLE_MAP = {
    "explorer": {
        "label": "探索者（读密集型）",
        "workers": ["aggregator", "rootcause"],
        "model_tier": "economical",
        "permission": "read-only",
        "rationale": "以读代码/日志/聚合为主，成本敏感",
    },
    "executor": {
        "label": "执行者（编码实现）",
        "workers": ["frontend", "backend", "fixer"],
        "model_tier": "high_reasoning",
        "permission": "workspace-write",
        "rationale": "编码实现需要高推理与写权限",
    },
    "reviewer": {
        "label": "复审者（独立裁判）",
        "workers": ["tester", "releaser"],
        "model_tier": "independent",
        "permission": "read-only",
        "rationale": "裁判必须独立于被评审者（跨模型族，避免同族自评）",
    },
    "orchestrator": {
        "label": "编排者（全貌决策）",
        "workers": ["leader", "coordinator", "doc-manager", "retrospector"],
        "model_tier": "balanced",
        "permission": "read-write",
        "rationale": "需要全貌视角与决策权",
    },
}

# worker -> role 反向索引
WORKER_TO_ROLE = {
    worker: role
    for role, cfg in ROLE_MAP.items()
    for worker in cfg["workers"]
}

# 派发包七要素（见 references/DISPATCH-BRIEF-SCHEMA.md）
BRIEF_FIELDS = {
    "version": {"required": True, "desc": "契约版本"},
    "outcome": {"required": True, "desc": "本次派发要产出什么（可验收结果）"},
    "benefit": {"required": False, "desc": "为什么派这个员工（对任务的价值）"},
    "sources": {"required": False, "desc": "事实主张必须引用的源（防编造）"},
    "scope": {"required": True, "desc": "明确边界（什么不做）"},
    "checks": {"required": True, "desc": "可运行的验收检查（至少 1 条）"},
    "stop_when": {"required": True, "desc": "有界停止条件（防无限游荡）"},
    "returns": {"required": True, "desc": "返回产物格式/路径"},
    "target": {"required": True, "desc": "派发目标 Worker"},
    "role": {"required": True, "desc": "角色类型（explorer/executor/reviewer/orchestrator）"},
}

# 复审包四要素（见 references/REVIEW-PACKAGE.md）
REVIEW_FIELDS = {
    "risk": {"required": True, "desc": "一个具体的未解决风险"},
    "evidence": {"required": True, "desc": "精确证据（文件/行号/日志）"},
    "passed_checks": {"required": True, "desc": "已通过的检查清单"},
    "stop_when": {"required": True, "desc": "本轮有界停止条件"},
}

BLOCKED_CODES = {
    "BLOCKED-01": "version 缺失",
    "BLOCKED-02": "outcome 为空",
    "BLOCKED-03": "checks 缺失或空（无验收标准即拒）",
    "BLOCKED-04": "scope 为空",
    "BLOCKED-05": "stop_when 为空",
    "BLOCKED-06": "target 不在 Worker 名册",
    "BLOCKED-07": "role 与 target 映射不一致",
    "BLOCKED-08": "returns 为空",
}
WARN_CODES = {
    "WARN-01": "事实性断言无 sources",
    "WARN-02": "executor 员工收到只读分析派发",
    "WARN-03": "benefit 为空",
}
REVIEW_CODES = {
    "REVIEW-01": "risk 缺失",
    "REVIEW-02": "evidence 缺失（无证据的复审不成立）",
    "REVIEW-03": "passed_checks 缺失或空",
    "REVIEW-04": "stop_when 缺失",
}


# ============================================================
# 二、校验逻辑
# ============================================================

def _has_text(value) -> bool:
    """非空判定：str 非空串；list 非空。"""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, list):
        return len(value) > 0
    return False


_FIELD_CODES = {
    "outcome": "BLOCKED-02",
    "checks": "BLOCKED-03",
    "scope": "BLOCKED-04",
    "stop_when": "BLOCKED-05",
    "returns": "BLOCKED-08",
}


def validate_brief(brief: dict) -> dict:
    """派发哨兵校验（fail-closed）。返回 {ok, blocks, warns, verdict}。"""
    blocks, warns = [], []
    if not _has_text(brief.get("version")):
        blocks.append("BLOCKED-01")
    for field, code in _FIELD_CODES.items():
        if not _has_text(brief.get(field)):
            blocks.append(code)
    if brief.get("target") not in WORKER_ROSTER:
        blocks.append("BLOCKED-06")
    target = brief.get("target")
    role = brief.get("role")
    if role and target in WORKER_TO_ROLE and WORKER_TO_ROLE[target] != role:
        blocks.append("BLOCKED-07")

    # 软性提示
    if not _has_text(brief.get("sources")):
        warns.append("WARN-01")
    if not _has_text(brief.get("benefit")):
        warns.append("WARN-03")
    if (
        target in WORKER_TO_ROLE
        and WORKER_TO_ROLE.get(target) == "executor"
        and role == "explorer"
    ):
        warns.append("WARN-02")

    passed = len(blocks) == 0
    return {
        "ok": passed,
        "blocks": blocks,
        "warns": warns,
        "verdict": "PASS" if passed else "BLOCKED",
    }


def validate_review(review: dict) -> dict:
    """独立复审包协议校验。返回 {ok, rejected, missing}。"""
    missing = []
    for field, meta in REVIEW_FIELDS.items():
        if not _has_text(review.get(field)):
            missing.append(field)
    ok = len(missing) == 0
    codes = {
        "risk": "REVIEW-01",
        "evidence": "REVIEW-02",
        "passed_checks": "REVIEW-03",
        "stop_when": "REVIEW-04",
    }
    return {
        "ok": ok,
        "rejected": [codes[f] for f in missing if f in codes],
        "missing": sorted(set(missing)),
        "verdict": "ACCEPTED" if ok else "REJECTED",
    }


def build_brief(args) -> dict:
    """从命令行参数构造派发包。"""
    checks = json.loads(args.checks) if args.checks else []
    return {
        "version": "1.0",
        "outcome": args.outcome,
        "benefit": args.benefit or "",
        "sources": args.sources.split(",") if args.sources else [],
        "scope": args.scope,
        "checks": checks,
        "stop_when": args.stop_when,
        "returns": args.returns,
        "target": args.target,
        "role": args.role,
    }


def format_brief(brief: dict) -> str:
    """人类可读的派发包渲染。"""
    lines = ["派发包（Dispatch Brief）"]
    lines.append(f"  版本      : {brief.get('version', '?')}")
    lines.append(f"  目标      : {brief.get('target', '?')}（role={brief.get('role', '?')}）")
    lines.append(f"  Outcome   : {brief.get('outcome', '?')}")
    lines.append(f"  Benefit   : {brief.get('benefit', '-')}")
    lines.append(f"  Sources   : {', '.join(brief.get('sources') or []) or '-'}")
    lines.append(f"  Scope     : {brief.get('scope', '?')}")
    lines.append(f"  Checks    : {json.dumps(brief.get('checks') or [], ensure_ascii=False)}")
    lines.append(f"  Stop when : {brief.get('stop_when', '?')}")
    lines.append(f"  Returns   : {brief.get('returns', '?')}")
    return "\n".join(lines)


def _load_json(path: str) -> dict:
    """读取 JSON 文件（支持顶层 {brief: {...}} 包装）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "brief" in data and isinstance(data["brief"], dict):
        return data["brief"]
    return data


# ============================================================
# 三、CLI
# ============================================================

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="dispatch_cli.py",
        description="派发契约 CLI（Coordinator 协同路由员专用）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # validate-brief
    p_brief = sub.add_parser("validate-brief", help="派发哨兵校验（fail-closed）")
    p_brief.add_argument("brief_json", help="派发包 JSON 文件路径")

    # template-brief
    p_tpl = sub.add_parser("template-brief", help="生成派发包模板")
    p_tpl.add_argument("--outcome", required=True)
    p_tpl.add_argument("--target", required=True)
    p_tpl.add_argument("--role", required=True, choices=sorted(ROLE_MAP))
    p_tpl.add_argument("--scope", required=True)
    p_tpl.add_argument("--checks", required=True, help='JSON 数组，如 ["pytest tests -q"]')
    p_tpl.add_argument("--stop-when", required=True)
    p_tpl.add_argument("--returns", required=True)
    p_tpl.add_argument("--benefit", default="")
    p_tpl.add_argument("--sources", default="", help="逗号分隔的源路径")

    # validate-review
    p_rev = sub.add_parser("validate-review", help="独立复审包协议校验")
    p_rev.add_argument("review_json", help="复审包 JSON 文件路径")

    # role-map
    p_rm = sub.add_parser("role-map", help="输出角色-模型映射表")
    p_rm.add_argument("--json", action="store_true", help="输出 JSON")

    # schema
    sub.add_parser("schema", help="输出派发包 schema")

    args = parser.parse_args(argv)

    if args.cmd == "validate-brief":
        brief = _load_json(args.brief_json)
        result = validate_brief(brief)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ok"]:
            print("DISPATCH BLOCKED: 派发被哨兵拦截，请补齐契约后重新派发。")
            return 2
        return 0

    if args.cmd == "template-brief":
        brief = build_brief(args)
        print(format_brief(brief))
        print("---")
        result = validate_brief(brief)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if not result["ok"] else 0

    if args.cmd == "validate-review":
        review = _load_json(args.review_json)
        result = validate_review(review)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["ok"]:
            print("REVIEW REJECTED: 无有效复审包 = 可避免的路由，请补齐四要素。")
            return 2
        return 0

    if args.cmd == "role-map":
        if getattr(args, "json", False):
            print(json.dumps(ROLE_MAP, ensure_ascii=False, indent=2))
        else:
            for role, cfg in ROLE_MAP.items():
                print(f"{role:12s} {cfg['label']:18s} 模型档位={cfg['model_tier']:16s} "
                      f"权限={cfg['permission']:16s} 员工={','.join(cfg['workers'])}")
        return 0

    if args.cmd == "schema":
        print("派发包七要素（必填项）：")
        for field, meta in BRIEF_FIELDS.items():
            mark = "必填" if meta["required"] else "可选"
            print(f"  - {field:12s} [{mark}] {meta['desc']}")
        print("\n复审包四要素（全部必填）：")
        for field, meta in REVIEW_FIELDS.items():
            print(f"  - {field:12s} {meta['desc']}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
