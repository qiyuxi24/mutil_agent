"""结构化审计日志（AuditLogger）—— 可观测 / 可审计。

对齐 TODO 3.2（可选增强）与官方「轨迹可观测」要求：
每条审计记录统一字段，落盘为 JSON Lines（一行一条），便于 grep / 采集 / 二次分析。

字段规范（设计 §3.2）：
    timestamp    ISO8601 时间
    trace_id     任务/闭环 trace
    agent_id     触发者（Manager / Worker 名）
    room_id      Matrix 房间（可选）
    event_type   decision | handoff | human_intervention | milestone | error | state
    action       动作名（如 approve_release / send_task / advance_state）
    result       PASS / FAIL / OK / 自定义
    detail       附加结构化信息（dict）

设计说明：
  - 纯标准库实现（json + logging），不引入 structlog，避免给参赛代码包增加外部依赖，
    换环境即用、零安装成本。
  - 线程安全：写入加锁，日志文件可被多 Worker/多任务共享（按 trace_id 区分）。
  - 可通过 `console=True` 同时输出到标准输出（默认只写文件，便于演示时控制台干净）。
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AuditEntry:
    """一条审计记录（可序列化）。"""

    trace_id: str
    agent_id: str
    event_type: str
    action: str
    result: str = "OK"
    room_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp or _now_iso(),
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "room_id": self.room_id,
            "event_type": self.event_type,
            "action": self.action,
            "result": self.result,
            "detail": self.detail,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AuditLogger:
    """结构化审计日志记录器。

    用法：
        audit = AuditLogger(log_dir=Path("data/audit"))
        audit.log_decision(task_id, "manager", action="approve_release",
                           result="PASS", detail={"release_id": "r1"})
        audit.log_handoff(task_id, "fixer", "tester", milestone="FIX_APPLIED")
        audit.log_human_intervention(task_id, "releaser", reason="灰度放量需人工确认")
        audit.close()
    """

    def __init__(self, log_dir: Path, console: bool = False):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._file = (self.log_dir / "audit.jsonl").open("a", encoding="utf-8")
        self._lock = threading.Lock()
        self._console = console
        self._count = 0

    # ------------------------------------------------------------------ #
    # 记录原语
    # ------------------------------------------------------------------ #

    def log(self, trace_id: str, agent_id: str, event_type: str, action: str,
            result: str = "OK", room_id: str = "", detail: dict[str, Any] | None = None) -> str:
        """写入一条审计记录，返回序列化 JSON 串。"""
        entry = AuditEntry(
            trace_id=trace_id,
            agent_id=agent_id,
            event_type=event_type,
            action=action,
            result=result,
            room_id=room_id,
            detail=detail or {},
        )
        line = entry.to_json()
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()
            self._count += 1
        if self._console:
            print(f"  [audit:{entry.event_type}] {entry.action} @{entry.agent_id} → {entry.result}")
        return line

    # ------------------------------------------------------------------ #
    # 语义化记录方法
    # ------------------------------------------------------------------ #

    def log_decision(self, trace_id: str, agent_id: str, decision: str,
                     justification: str = "", result: str = "OK",
                     room_id: str = "", **extra: Any) -> str:
        """记录一次决策（推进/打回/审批等）。"""
        detail = {"decision": decision, "justification": justification, **extra}
        return self.log(trace_id, agent_id, "decision", "decision", result, room_id, detail)

    def log_handoff(self, trace_id: str, from_agent: str, to_agent: str,
                    milestone: str = "", room_id: str = "") -> str:
        """记录一次 Worker 间交接（@mention 接力）。"""
        return self.log(trace_id, from_agent, "handoff", "handoff",
                        detail={"from": from_agent, "to": to_agent, "milestone": milestone},
                        room_id=room_id)

    def log_human_intervention(self, trace_id: str, agent_id: str, reason: str,
                               approved: bool | None = None, room_id: str = "") -> str:
        """记录一次人工介入（审批/反馈/打回）。"""
        result = "PASS" if approved else ("FAIL" if approved is False else "REQUIRED")
        return self.log(trace_id, agent_id, "human_intervention", "human_intervention",
                        result=result, room_id=room_id, detail={"reason": reason})

    def log_milestone(self, trace_id: str, agent_id: str, milestone: str,
                      state: str = "", result: str = "PASS", room_id: str = "") -> str:
        """记录里程碑达成/打回。"""
        return self.log(trace_id, agent_id, "milestone", milestone,
                        result=result, room_id=room_id, detail={"state": state})

    def log_error(self, trace_id: str, agent_id: str, action: str,
                  error: str, room_id: str = "") -> str:
        """记录一次错误。"""
        return self.log(trace_id, agent_id, "error", action, "FAIL", room_id, {"error": error})

    # ------------------------------------------------------------------ #
    # 查询 / 关闭
    # ------------------------------------------------------------------ #

    def count(self) -> int:
        return self._count

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()

    def __enter__(self) -> "AuditLogger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def read_audit_log(log_path: Path) -> list[dict[str, Any]]:
    """读取审计日志文件，返回记录列表（可被测试/审计后台消费）。"""
    log_path = Path(log_path)
    if not log_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        with AuditLogger(p, console=False) as audit:
            audit.log_decision("t1", "manager", decision="approve release",
                               justification="灰度通过", result="PASS")
            audit.log_handoff("t1", "fixer", "tester", milestone="FIX_APPLIED")
            audit.log_human_intervention("t1", "releaser", reason="需人工放量")
            audit.log_milestone("t1", "tester", "TEST_PASSED")
            audit.log_error("t1", "fixer", "compile", error="syntax error")

        records = read_audit_log(p / "audit.jsonl")
        assert len(records) == 5
        assert records[0]["event_type"] == "decision"
        assert records[2]["event_type"] == "human_intervention"
        assert all(r["trace_id"] == "t1" for r in records)
        assert all(r["timestamp"] for r in records)
        print(f"✓ AuditLogger 自检通过（{len(records)} 条记录）")
