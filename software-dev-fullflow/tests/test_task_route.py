"""B2/E2 · create_task 统一「交给 Leader 编排一套班子」。

2026-08-16 重构：`route_via_hr` 参数已移除（不再有 HR 双模式），
统一为 Leader 从一套班子里按阶段挑人。本测试锁定 create_task 的
消息内容契约，作为一套班子路径的回归锁。

只 mock Matrix 派单接口（matrix_login / ensure_manager_room / send_matrix_message），
不依赖真实 AgentTeams 平台。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from loop.agentteams_client import AgentTeamsClient


class _MatrixSink(AgentTeamsClient):
    """测试替身：捕获 send_matrix_message 的消息，不真正连 Matrix。"""

    def __init__(self, checkpoint_dir: Path):
        super().__init__(checkpoint_dir=checkpoint_dir)
        self.sent_messages: list[str] = []
        self.login_called = False

    def matrix_login(self) -> None:  # noqa: D102
        self.login_called = True

    def ensure_manager_room(self) -> str:  # noqa: D102
        return "!test-room"

    def send_matrix_message(self, room_id: str, message: str) -> None:  # noqa: D102
        self.sent_messages.append(message)


def _run_create(client: AgentTeamsClient, **kwargs):
    return asyncio.run(client.create_task(**kwargs))


def _make_client(tmp_path: Path) -> _MatrixSink:
    return _MatrixSink(tmp_path / "checkpoints")


# --------------------------------------------------------------------------- #
# 测试用例
# --------------------------------------------------------------------------- #

class TestLeaderRoute:
    def test_message_has_team_roster(self, tmp_path: Path):
        """任务消息含「一套班子」团队名单。"""
        c = _make_client(tmp_path)
        _run_create(c, spec="修复登录接口空用户名500")
        assert c.sent_messages, "应发出一条任务消息"
        msg = c.sent_messages[0]
        assert "【研发闭环任务】" in msg
        assert "一套班子" in msg
        assert "leader" in msg
        assert "frontend" in msg and "backend" in msg

    def test_message_has_milestone_contract(self, tmp_path: Path):
        """任务消息含新班子里程碑握手协议。"""
        c = _make_client(tmp_path)
        _run_create(c, spec="修复 bug")
        msg = c.sent_messages[0]
        assert "TASK_SPEC_READY" in msg
        assert "ROOT_CAUSE_FOUND" in msg
        assert "SITE_READY" in msg and "BACKEND_READY" in msg
        assert "FIX_APPLIED" in msg
        assert "TEST_PASSED" in msg
        assert "RELEASE_OK" in msg
        assert "RETROSPECT_DONE" in msg

    def test_message_mentions_leader_coordination(self, tmp_path: Path):
        """消息含「Leader 决定每阶段参与员工 + 协调员工通信」指令。"""
        c = _make_client(tmp_path)
        _run_create(c, spec="搭建官网")
        msg = c.sent_messages[0]
        assert "Leader" in msg
        assert "协调员工间通信" in msg or "协调" in msg

    def test_no_hr_dual_mode(self, tmp_path: Path):
        """不再注入 HR 双模式（route_via_hr 已移除）。"""
        c = _make_client(tmp_path)
        _run_create(c, spec="搭建带 POST 的网站")
        msg = c.sent_messages[0]
        assert "@hr" not in msg
        assert "动态组队指令" not in msg
        assert "搭建任务" not in msg  # 不再区分修复/搭建双模式

    def test_uses_matrix(self, tmp_path: Path):
        """走 Matrix DM 派单。"""
        c = _make_client(tmp_path)
        _run_create(c, spec="搭建官网")
        assert c.login_called, "应调用 matrix_login"
        assert c.sent_messages, "应调用 send_matrix_message 发送任务"

    def test_still_has_task_id(self, tmp_path: Path):
        """消息末尾仍带隐藏 task_id 标记（GAP-06 兼容）。"""
        c = _make_client(tmp_path)
        info = _run_create(c, spec="搭建官网")
        assert f"TASK_ID:{info.task_id}" in c.sent_messages[0]

    def test_checkpoint_saved(self, tmp_path: Path):
        """任务都会写 checkpoint（GAP-07 断点续传兼容）。"""
        c = _make_client(tmp_path)
        _run_create(c, spec="修复 bug")
        cps = list(c._checkpoint_dir.glob("task-*.json"))
        assert len(cps) == 1

    def test_explicit_pipeline_still_honored(self, tmp_path: Path):
        """显式传 pipeline → 消息使用给定流水线。"""
        c = _make_client(tmp_path)
        _run_create(c, spec="修复", pipeline=["aggregator", "fixer"])
        msg = c.sent_messages[0]
        assert "aggregator" in msg and "fixer" in msg

    def test_pdca_workers_is_full_roster(self):
        """PDCA_WORKERS 为「一套完整班子」9 个员工。"""
        c = AgentTeamsClient()
        assert "leader" in c.PDCA_WORKERS
        assert "frontend" in c.PDCA_WORKERS
        assert "backend" in c.PDCA_WORKERS
        assert "fixer" in c.PDCA_WORKERS
