#!/usr/bin/env python3
"""iteration_log.py — 无人值守迭代停滞检测 → 强制结构性转向。

追加式（append-only）逐迭代台账，供「多 Agent 软件研发团队」的 Leader 编排循环使用。
每一轮迭代，编排者（Leader）记录该轮产出的**新发现数**——"发现"指具体新增条目
（新证据、被证伪的假设、候选方向），而不是主观的"有价值结果"。连续 0 新发现的
迭代会累积 stale_count，从而驱动强制转向：

  stale_count >= 2  → pivot = "structural"  （改变结构性约束，而非战术参数）
  stale_count >= 4  → pivot = "human"        （标记需要人类关注/上报）

这是 **Type-A 信号**：它只数条目、改方向；不评判质量——质量/正确性归属跨模型评审
（shared-references/acceptance-gate.md 语义，对应本项目 review-gate）。它只会说
"继续 / 换方向"，永远不会说"足够好了"。

台账是侧车文件，位于 `<root>/runs/<run_id>.iterations.jsonl`（root 传 `src/data/shared`，
与项目产物目录一致）。它刻意不 import、不触碰 run_state 的 done/accepted 状态机，
只共享 `runs/` 目录，使用独立的 `.iterations.jsonl` 后缀。每条记录可带可选
`direction` 字段，供循环的再生成环节拒绝过于接近已尝试方向的候选。

来源：移植自上交大 ARIS（Auto-claude-code-research-in-sleep）`tools/iteration_log.py`，
仅调整侧车路径与 docstring 语境，核心逻辑（PIVOT/ESCALATE 阈值、防逃逸校验、
append-only、fcntl 锁）原样保留。

Usage:
    python iteration_log.py note <root> <run_id> <phase> <new_findings> [--direction "..."]
    python iteration_log.py show <root> <run_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    # Windows 无 fcntl：静默退化为无锁模式（单编排者契约下足够安全）。
    fcntl = None  # type: ignore

PIVOT_STRUCTURAL_AT = 2   # 连续 0 新发现迭代数 → 强制结构性转向
ESCALATE_HUMAN_AT = 4     # 仍停滞 → 标记需要人类关注

__all__ = ["PIVOT_STRUCTURAL_AT", "ESCALATE_HUMAN_AT", "pivot_for", "note", "show"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_path(root: str, run_id: str) -> Path:
    # 与 run_state 相同的 run_id 纪律：不允许路径逃逸。
    safe = "".join(c for c in run_id if c.isalnum() or c in "-_.")
    if not safe or safe != run_id or run_id in (".", ".."):
        raise ValueError(f"invalid run_id {run_id!r} (use [A-Za-z0-9-_.])")
    # root 传入产物目录（如 src/data/shared），台账落在 <root>/runs/<run_id>.iterations.jsonl
    return Path(root) / "runs" / f"{run_id}.iterations.jsonl"


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    """尽力而为的 advisory 锁（单编排者契约；防意外 resumer 并发写）。

    注意：Windows 上 fcntl 不可用，锁静默退化（yield 直接放行），
    依赖"单编排者"这一既有契约保证追加写互斥。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:
        yield
        return
    fh = open(path.with_suffix(".jsonl.lock"), "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def _last_stale(path: Path) -> int:
    """从追加式台账读取最近的 stale_count（无记录则为 0）。"""
    if not path.is_file():
        return 0
    last = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                last = int(json.loads(line).get("stale_count", last))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue  # 容忍损坏/不完整行，保留最后一个好值
    except OSError:
        return 0
    return last


def pivot_for(stale_count: int) -> str:
    if stale_count >= ESCALATE_HUMAN_AT:
        return "human"
    if stale_count >= PIVOT_STRUCTURAL_AT:
        return "structural"
    return "none"


def note(root: str, run_id: str, phase: str, new_findings: int,
         direction: Optional[str] = None) -> dict:
    """记录一轮迭代；返回 {stale_count, pivot}。追加式；绝不阻塞主循环。"""
    new_findings = int(new_findings)
    if new_findings < 0:
        raise ValueError(f"new_findings must be >= 0, got {new_findings}")
    path = _log_path(root, run_id)
    with _lock(path):
        stale_count = 0 if new_findings > 0 else _last_stale(path) + 1
        pivot = pivot_for(stale_count)
        rec = {"ts": _now(), "phase": phase, "new_findings": new_findings,
               "stale_count": stale_count, "pivot": pivot}
        if direction is not None:
            rec["direction"] = direction
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"stale_count": stale_count, "pivot": pivot}


def show(root: str, run_id: str) -> str:
    path = _log_path(root, run_id)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main() -> int:
    ap = argparse.ArgumentParser(description="无人值守迭代停滞检测 → 强制结构性转向")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("note")
    n.add_argument("root"); n.add_argument("run_id"); n.add_argument("phase")
    n.add_argument("new_findings", type=int); n.add_argument("--direction", default=None)
    s = sub.add_parser("show"); s.add_argument("root"); s.add_argument("run_id")
    a = ap.parse_args()
    if a.cmd == "note":
        print(json.dumps(note(a.root, a.run_id, a.phase, a.new_findings, a.direction)))
    elif a.cmd == "show":
        sys.stdout.write(show(a.root, a.run_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
