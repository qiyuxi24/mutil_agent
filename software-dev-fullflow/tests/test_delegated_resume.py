"""GAP-25 委托模式断点续跑测试。

场景：
  1. wait_for_task 第一轮超时（status=timeout）→ loop 循环接续，直到 completed
  2. delegation.json 已持久化（status=running）→ 复用同一 platform_task_id，不重复 create_task
  3. delegation.json 已 completed → 视为终态，重新 create_task
  4. 达到 MAX_DELEGATE_ROUNDS 仍未完成 → 优雅收尾（不无限循环）

运行：`python -m pytest tests/test_delegated_resume.py -v`
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loop.agentteams_loop import AgentTeamsLoop
from loop.agentteams_client import AgentTeamsClient
from loop.state import State

COMPLETED_MS = [
    {"milestone": "TASK_SPEC_READY", "worker": "aggregator", "content": ""},
    {"milestone": "ROOT_CAUSE_FOUND", "worker": "rootcause", "content": ""},
    {"milestone": "FIX_APPLIED", "worker": "backend", "content": ""},
    {"milestone": "TEST_PASSED", "worker": "tester", "content": ""},
    {"milestone": "RELEASE_OK", "worker": "releaser", "content": ""},
    {"milestone": "RETROSPECT_DONE", "worker": "retrospector", "content": ""},
]


def _install_platform_ok(monkeypatch) -> None:
    """平台探活通过 + PDCA Worker 就绪（跳过 ensure_workers）。"""

    async def _ping_ok(self) -> bool:
        return True

    async def _status_ok(self) -> dict:
        return {"managers": [], "workers": [], "teams": [],
                "pdca_workers_ready": True}

    monkeypatch.setattr(AgentTeamsClient, "ping", _ping_ok)
    monkeypatch.setattr(AgentTeamsClient, "status", _status_ok)


def test_timeout_then_completed_loops_resume(tmp_path: Path, monkeypatch):
    """第一轮 wait_for_task 超时 → loop 应接续第二轮并从断点完成。"""

    _install_platform_ok(monkeypatch)
    calls = {"n": 0}

    async def _create_task(self, spec: str, pipeline=None, manager: str = "default"):
        from loop.agentteams_client import TaskInfo
        return TaskInfo(task_id="P-LOOP-001", spec=spec)

    async def _wait_task(self, task_id: str, timeout: float = 600, poll_interval: float = 10):
        calls["n"] += 1
        if calls["n"] == 1:
            # 第一轮：增量超时，但已有部分里程碑
            return {"status": "timeout", "milestones": [
                {"milestone": "TASK_SPEC_READY", "worker": "aggregator", "content": ""},
            ], "elapsed": 60.0, "resumed": False, "checkpoint_path": ""}
        # 第二轮：从断点恢复（resumed=True）并完成
        return {"status": "completed", "milestones": COMPLETED_MS,
                "elapsed": 120.0, "resumed": True, "checkpoint_path": ""}

    monkeypatch.setattr(AgentTeamsClient, "create_task", _create_task)
    monkeypatch.setattr(AgentTeamsClient, "wait_for_task", _wait_task)

    loop = AgentTeamsLoop(task_id="t-resume-loop", spec="修复登录 500",
                          workdir=tmp_path, mock=False)
    state = asyncio.run(loop.run())

    assert calls["n"] == 2, "第一轮超时应接续第二轮"
    assert state.state == State.RETROSPECT
    assert "RETROSPECT_DONE" in state.milestones
    # delegation 应标记完成（保留供审计）
    delegation = json.loads(
        (tmp_path / "shared" / "tasks" / "t-resume-loop" / "delegation.json")
        .read_text(encoding="utf-8"))
    assert delegation["status"] == "completed"
    assert delegation["platform_task_id"]


def test_resume_reuses_persisted_platform_task(tmp_path: Path, monkeypatch):
    """delegation.json（running）已存在 → resume forward 复用同一平台任务，不重复 create_task。"""

    _install_platform_ok(monkeypatch)
    # 预写 delegation：模拟上一进程超时退出留下的委托记录
    task_dir = tmp_path / "shared" / "tasks" / "t-resume-reuse"
    task_dir.mkdir(parents=True)
    (task_dir / "delegation.json").write_text(json.dumps({
        "task_id": "t-resume-reuse",
        "platform_task_id": "P-PERSISTED-001",
        "spec": "修复登录 500",
        "created_at": "2026-08-31T00:00:00+00:00",
        "updated_at": "2026-08-31T01:00:00+00:00",
        "status": "running",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    received: dict = {}

    async def _wait_task(self, task_id: str, timeout: float = 600, poll_interval: float = 10):
        received["task_id"] = task_id
        return {"status": "completed", "milestones": COMPLETED_MS,
                "elapsed": 30.0, "resumed": True, "checkpoint_path": ""}

    async def _create_task_fail(self, spec: str, pipeline=None, manager: str = "default"):
        raise AssertionError("续跑场景不应重新 create_task")

    monkeypatch.setattr(AgentTeamsClient, "wait_for_task", _wait_task)
    monkeypatch.setattr(AgentTeamsClient, "create_task", _create_task_fail)

    loop = AgentTeamsLoop(task_id="t-resume-reuse", spec="修复登录 500",
                          workdir=tmp_path, mock=False)
    state = asyncio.run(loop.run())

    assert received.get("task_id") == "P-PERSISTED-001", "应复用持久化的平台任务 ID"
    assert state.state == State.RETROSPECT
    # 完成后委托记录更新为 completed（保留 created_at）
    delegation = json.loads((task_dir / "delegation.json").read_text(encoding="utf-8"))
    assert delegation["status"] == "completed"
    assert delegation["created_at"] == "2026-08-31T00:00:00+00:00"


def test_completed_delegation_creates_new_task(tmp_path: Path, monkeypatch):
    """delegation.json 已 completed → 视为终态，重新 create_task（不续跑旧任务）。"""

    _install_platform_ok(monkeypatch)
    task_dir = tmp_path / "shared" / "tasks" / "t-resume-done"
    task_dir.mkdir(parents=True)
    (task_dir / "delegation.json").write_text(json.dumps({
        "task_id": "t-resume-done",
        "platform_task_id": "P-OLD-DONE",
        "spec": "旧任务",
        "created_at": "2026-08-30T00:00:00+00:00",
        "updated_at": "2026-08-30T05:00:00+00:00",
        "status": "completed",
    }), encoding="utf-8")

    received: dict = {}

    async def _create_task(self, spec: str, pipeline=None, manager: str = "default"):
        from loop.agentteams_client import TaskInfo
        received["spec"] = spec
        return TaskInfo(task_id="P-NEW-002", spec=spec)

    async def _wait_task(self, task_id: str, timeout: float = 600, poll_interval: float = 10):
        received["task_id"] = task_id
        return {"status": "completed", "milestones": COMPLETED_MS,
                "elapsed": 30.0, "resumed": False, "checkpoint_path": ""}

    monkeypatch.setattr(AgentTeamsClient, "create_task", _create_task)
    monkeypatch.setattr(AgentTeamsClient, "wait_for_task", _wait_task)

    loop = AgentTeamsLoop(task_id="t-resume-done", spec="修复登录 500",
                          workdir=tmp_path, mock=False)
    state = asyncio.run(loop.run())

    assert received.get("task_id") == "P-NEW-002", "completed 是终态，应新建任务"
    delegation = json.loads((task_dir / "delegation.json").read_text(encoding="utf-8"))
    assert delegation["platform_task_id"] == "P-NEW-002"
    assert delegation["status"] == "completed"


def test_max_rounds_reached_graceful_exit(tmp_path: Path, monkeypatch):
    """wait_for_task 持续超时 → 达到 MAX_DELEGATE_ROUNDS 后优雅收尾，不无限循环。"""

    _install_platform_ok(monkeypatch)
    monkeypatch.setenv(AgentTeamsLoop.MAX_DELEGATE_ROUNDS_ENV, "2")
    calls = {"n": 0}

    async def _create_task(self, spec: str, pipeline=None, manager: str = "default"):
        from loop.agentteams_client import TaskInfo
        return TaskInfo(task_id="P-MAX-001", spec=spec)

    async def _wait_task(self, task_id: str, timeout: float = 600, poll_interval: float = 10):
        calls["n"] += 1
        return {"status": "timeout", "milestones": [
            {"milestone": "TASK_SPEC_READY", "worker": "aggregator", "content": ""},
        ], "elapsed": 3600.0, "resumed": True, "checkpoint_path": ""}

    monkeypatch.setattr(AgentTeamsClient, "create_task", _create_task)
    monkeypatch.setattr(AgentTeamsClient, "wait_for_task", _wait_task)

    loop = AgentTeamsLoop(task_id="t-resume-max", spec="修复登录 500",
                          workdir=tmp_path, mock=False)
    state = asyncio.run(loop.run())

    assert calls["n"] == 2, "达到最大轮次（2）后应停止，不无限循环"
    # 未完成：状态停在已同步的里程碑处
    assert "TASK_SPEC_READY" in state.milestones
    assert state.state in (State.SPEC_DECOMPOSE, State.RETROSPECT)
    # delegation 保持 running（任务未完成，跨进程可继续续跑）
    delegation = json.loads(
        (tmp_path / "shared" / "tasks" / "t-resume-max" / "delegation.json")
        .read_text(encoding="utf-8"))
    assert delegation["status"] == "running"
    # 审计记录 max_rounds_reached
    audit_dir = tmp_path / "shared" / "audit"
    jsonl = list(audit_dir.glob("*.jsonl"))
    assert jsonl
    assert "max_rounds_reached" in jsonl[0].read_text(encoding="utf-8")
