"""GAP-04 委托模式降级测试（TODO 3.1）。

场景：`mock=False`（委托模式）但 AgentTeams 平台不可用时，
`_run_delegated()` 应自动 fallback 到 mock，打印提示并跑完整闭环，
保证演示（"闭环真能跑"卖点）不翻车。

通过 monkeypatch `AgentTeamsClient.ping` 模拟平台不可用，不依赖真实平台。
运行：`python -m pytest tests/test_delegated_fallback.py -v`
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loop.agentteams_loop import AgentTeamsLoop
from loop.agentteams_client import AgentTeamsClient
from loop.state import State


def test_delegated_falls_back_to_mock_when_platform_down(tmp_path: Path, monkeypatch):
    """平台探活失败（ping 返回 False）→ 委托模式自动降级到 mock 完整闭环。"""

    async def _ping_false(self) -> bool:
        return False

    monkeypatch.setattr(AgentTeamsClient, "ping", _ping_false)

    loop = AgentTeamsLoop(
        task_id="t-fallback-down",
        spec="修复登录接口空用户名500",
        workdir=tmp_path,
        mock=False,  # 委托模式
    )
    state = asyncio.run(loop.run())

    # 降级后应走 mock 完整闭环，而非返回未完成的初始状态
    assert state.state == State.RETROSPECT
    assert "RETROSPECT_DONE" in state.milestones
    assert len(state.milestones) == 6
    # 审计留痕记录降级事件
    audit_dir = tmp_path / "shared" / "audit"
    jsonl = list(audit_dir.glob("*.jsonl"))
    assert jsonl, "应生成审计日志"
    text = jsonl[0].read_text(encoding="utf-8")
    assert "degrade_to_mock" in text, "审计应记录 degrade_to_mock 事件"


def test_delegated_falls_back_when_ping_raises(tmp_path: Path, monkeypatch):
    """平台探活异常（ping 抛异常）→ 委托模式同样降级到 mock，不中断演示。"""

    async def _ping_raises(self) -> bool:
        raise RuntimeError("docker daemon not reachable")

    monkeypatch.setattr(AgentTeamsClient, "ping", _ping_raises)

    loop = AgentTeamsLoop(
        task_id="t-fallback-raise",
        spec="修复登录接口空用户名500",
        workdir=tmp_path,
        mock=False,
    )
    state = asyncio.run(loop.run())

    assert state.state == State.RETROSPECT
    assert "RETROSPECT_DONE" in state.milestones


def test_delegated_create_task_failure_falls_back(tmp_path: Path, monkeypatch):
    """平台探活通过但 create_task（Matrix 提交）失败 → 降级到 mock。"""
    from loop.agentteams_client import TaskInfo

    async def _ping_ok(self) -> bool:
        return True

    async def _create_task_fail(self, spec: str, pipeline=None, manager: str = "default"):
        raise RuntimeError("Matrix 登录失败: room not reachable")

    monkeypatch.setattr(AgentTeamsClient, "ping", _ping_ok)
    monkeypatch.setattr(AgentTeamsClient, "create_task", _create_task_fail)

    loop = AgentTeamsLoop(
        task_id="t-fallback-ct",
        spec="修复登录接口空用户名500",
        workdir=tmp_path,
        mock=False,
    )
    state = asyncio.run(loop.run())

    assert state.state == State.RETROSPECT
    assert "RETROSPECT_DONE" in state.milestones

    audit_dir = tmp_path / "shared" / "audit"
    jsonl = list(audit_dir.glob("*.jsonl"))
    text = jsonl[0].read_text(encoding="utf-8")
    assert "degrade_to_mock" in text
