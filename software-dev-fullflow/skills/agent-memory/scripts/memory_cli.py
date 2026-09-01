#!/usr/bin/env python3
"""memory_cli.py — 通用记忆系统命令行入口。

为 `skills/agent-memory` Skill 提供可执行能力：
  读取/写入/检索/沉淀 Agent 的独立记忆。

用法（在项目根目录，或把 src/ 加入 PYTHONPATH）：
  python skills/agent-memory/scripts/memory_cli.py \
      --agent fixer write --task T-0001 --phase fix --outcome success \
      --pattern "拆解根因后一次修复成功"
  python skills/agent-memory/scripts/memory_cli.py --agent fixer recall --query "空指针"
  python skills/agent-memory/scripts/memory_cli.py --agent fixer consolidate
  python skills/agent-memory/scripts/memory_cli.py --agent fixer snapshot
  python skills/agent-memory/scripts/memory_cli.py --agent fixer read

退出码：0=成功；1=参数/执行错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接运行：把项目 src/ 加入 sys.path
_PROJECT = Path(__file__).resolve().parent.parent.parent.parent
_SRC = _PROJECT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from loop.context import AgentMemoryEntry, AgentMemoryRegistry  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="通用记忆系统命令行")
    parser.add_argument("--agent", required=True, help="Agent 名称（如 fixer / tester）")
    parser.add_argument("--storage", default="", help="共享存储根目录（默认工作目录/shared）")
    sub = parser.add_subparsers(dest="op", required=True)

    p_write = sub.add_parser("write", help="写入一条迭代记录")
    p_write.add_argument("--task", default="", help="任务 ID")
    p_write.add_argument("--phase", default="", help="阶段（root_cause/fix/test/release/retrospect）")
    p_write.add_argument("--outcome", default="success", help="结果（success/fail/retry）")
    p_write.add_argument("--mistake", action="append", default=[], help="踩过的坑（可多次）")
    p_write.add_argument("--fix", action="append", default=[], help="修正方法（可多次）")
    p_write.add_argument("--pattern", action="append", default=[], help="发现的模式（可多次）")
    p_write.add_argument("--retry-count", type=int, default=0, help="重试次数")

    p_read = sub.add_parser("read", help="读取迭代记录")
    p_read.add_argument("--limit", type=int, default=10, help="读取条数")

    p_recall = sub.add_parser("recall", help="检索历史经验")
    p_recall.add_argument("--query", required=True, help="检索词")
    p_recall.add_argument("--phase", default="", help="限定阶段")
    p_recall.add_argument("--top-k", type=int, default=5, help="返回条数")

    p_cons = sub.add_parser("consolidate", help="沉淀长期记忆")

    p_snap = sub.add_parser("snapshot", help="记忆快照")
    return parser


def _resolve_storage(arg: str) -> Path:
    if arg:
        return Path(arg)
    # 默认：当前目录 / shared；若在 skills 子目录运行，回退到项目根 / shared
    cwd = Path.cwd()
    for base in (cwd, _PROJECT):
        candidate = base / "shared"
        if candidate.exists():
            return candidate
    return _PROJECT / "shared"


def main() -> int:
    args = _build_parser().parse_args()
    storage = _resolve_storage(args.storage)
    registry = AgentMemoryRegistry(storage_dir=storage)
    mem = registry.get(args.agent)

    if args.op == "write":
        entry = AgentMemoryEntry(
            task_id=args.task,
            phase=args.phase,
            outcome=args.outcome,
            mistakes=args.mistake,
            fixes=args.fix,
            patterns=args.pattern,
            retry_count=args.retry_count,
        )
        mem.record_iteration(entry)
        print(json.dumps({"status": "OK", "milestone": "MEMORY_WRITTEN",
                          "agent": args.agent, "task_id": args.task},
                         ensure_ascii=False))
        return 0

    if args.op == "read":
        # 从 JSONL 内存态读取最近的迭代记录
        entries = mem._iterations[-args.limit:]  # noqa: SLF001
        print(json.dumps([{
            "task_id": e.task_id, "phase": e.phase, "outcome": e.outcome,
            "mistakes": e.mistakes, "fixes": e.fixes, "patterns": e.patterns,
            "retry_count": e.retry_count,
        } for e in entries], ensure_ascii=False, indent=2))
        return 0

    if args.op == "recall":
        results = mem.recall(args.query, phase=args.phase, top_k=args.top_k)
        print(json.dumps({"status": "OK", "milestone": "MEMORY_RECALLED",
                          "count": len(results), "results": results},
                         ensure_ascii=False, indent=2))
        return 0

    if args.op == "consolidate":
        count = mem.consolidate_to_long_term()
        print(json.dumps({"status": "OK", "milestone": "MEMORY_CONSOLIDATED",
                          "new_long_term_entries": count}, ensure_ascii=False))
        return 0

    if args.op == "snapshot":
        print(json.dumps(mem.snapshot(), ensure_ascii=False, indent=2))
        return 0

    print(json.dumps({"status": "ERROR", "reason": f"未知操作: {args.op}"}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
