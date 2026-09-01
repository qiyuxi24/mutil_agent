"""C2 · 员工间通信 —— AgentBus 定向请求/应答单测。

验证「一套班子」里员工可互相通信的核心场景：
  - Tester → Backend 请求开发日志（request-reply）
  - 授权控制：未授权 peer 不能通信
  - 应答通过 request_id 关联
"""
from __future__ import annotations

from loop.agent_bus import AgentBus, MessageType


class TestTeamComm:
    def test_request_reply_flow(self):
        """Tester → Backend 请求开发日志，Backend 应答。"""
        bus = AgentBus()
        bus.authorize("tester", "backend")

        request_id = bus.request(
            "tester", "backend", "T-1",
            "请提供 POST /api/submit 接口的开发日志", kind="log",
        )
        assert request_id.startswith("req-")

        # Backend 收到请求
        reqs = bus.get_requests_for("backend")
        assert len(reqs) == 1
        assert reqs[0].msg_type == MessageType.REQUEST
        assert reqs[0].metadata["kind"] == "log"

        # Backend 应答
        ok = bus.reply("backend", "tester", "T-1", request_id, "接口日志已写入 /tmp/server.log")
        assert ok

        # Tester 收到应答
        replies = [m for m in bus.receive("tester")
                   if m.msg_type == MessageType.REPLY]
        assert len(replies) == 1
        assert replies[0].metadata["request_id"] == request_id
        assert "接口日志" in replies[0].content

    def test_request_requires_authorization(self):
        """未授权 peer 的请求被拒绝。"""
        bus = AgentBus()
        # aggregator → retrospector 不在默认流水线/横向协作授权内
        request_id = bus.request("aggregator", "retrospector", "T-1", "请求")
        assert request_id == ""  # 未授权返回空
        assert bus.get_requests_for("retrospector") == []

    def test_find_request_by_id(self):
        """按 request_id 在历史中找回原请求。"""
        bus = AgentBus()
        bus.authorize("tester", "backend")
        request_id = bus.request("tester", "backend", "T-1", "要日志")
        req = bus.find_request(request_id)
        assert req is not None
        assert req.sender == "tester"
        assert req.content == "要日志"

    def test_reply_with_unknown_request(self):
        """reply 对不存在 request_id 仍可发送（底层不校验，但请求需授权）。"""
        bus = AgentBus()
        bus.authorize("backend", "tester")
        ok = bus.reply("backend", "tester", "T-1", "req-nonexistent", "回复")
        assert ok

    def test_default_pipeline_authorization(self):
        """默认 PDCA 上下游已授权（leader 与全员、流水线上下游）。"""
        bus = AgentBus()
        # leader 已授权与所有 pipeline worker 通信
        assert bus.is_authorized("leader", "tester")
        assert bus.is_authorized("tester", "leader")

    def test_get_peers(self):
        """get_peers 返回指定 Worker 的所有授权通信对象。"""
        bus = AgentBus()
        bus.authorize("tester", "backend")
        bus.authorize("frontend", "tester")
        peers = bus.get_peers("tester")
        assert "backend" in peers
        assert "frontend" in peers

    def test_request_history_recorded(self):
        """request/reply 都会进历史。"""
        bus = AgentBus()
        bus.authorize("tester", "backend")
        bus.request("tester", "backend", "T-1", "要日志")
        bus.reply("backend", "tester", "T-1", "req-1", "回复")
        hist = bus.history(task_id="T-1")
        types = {h["msg_type"] for h in hist}
        assert "REQUEST" in types
        assert "REPLY" in types
