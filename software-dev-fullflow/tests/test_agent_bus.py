"""GAP-08 测试：AgentBus 消息总线（channelPolicy 权限约束）+ EventBus 事件驱动。

AgentBus（loop/agent_bus.py）：
  - 只有授权 peer 之间可通信（channelPolicy）
  - PDCA 流水线上下游默认授权（aggregator→rootcause→…→retrospector）
  - handoff/feedback/query/alert 便捷方法

EventBus（loop/event_bus.py，由 agent_bus re-export）：
  - 订阅/通配符 "*"
  - 同步/异步回调
  - 事件历史可审计
"""

from __future__ import annotations

import asyncio

from loop.agent_bus import AgentBus, AgentMessage, MessageType, EventBus, Event, EventType


# --------------------------------------------------------------------------- #
# AgentBus: channelPolicy 权限约束
# --------------------------------------------------------------------------- #

def test_pdca_pipeline_authorized_by_default():
    """一套班子流水线上下游默认授权（2026-08-16 重构）。"""
    bus = AgentBus()
    assert bus.is_authorized("aggregator", "rootcause")
    assert bus.is_authorized("rootcause", "frontend")
    assert bus.is_authorized("frontend", "backend")
    assert bus.is_authorized("backend", "fixer")
    assert bus.is_authorized("fixer", "tester")
    assert bus.is_authorized("tester", "releaser")
    assert bus.is_authorized("releaser", "retrospector")
    # leader ↔ all（固定编排者）
    assert bus.is_authorized("leader", "aggregator")
    assert bus.is_authorized("retrospector", "leader")
    # 员工间横向协作（Tester 可向 Backend 要开发日志）
    assert bus.is_authorized("tester", "backend")
    assert bus.is_authorized("backend", "tester")


def test_unauthorized_channel_blocked():
    """未授权 peer 之间 publish 返回 False，消息不入队。"""
    bus = AgentBus()
    # aggregator → retrospector 未直接授权（非上下游）
    msg = AgentMessage(
        msg_id="m1", msg_type=MessageType.QUERY,
        sender="aggregator", receiver="retrospector", content="hi",
    )
    assert bus.publish(msg) is False
    assert bus.peek("retrospector") == []


def test_authorize_opens_new_channel():
    """显式 authorize 后可通信，revoke 后关闭。"""
    bus = AgentBus()
    assert not bus.is_authorized("aggregator", "retrospector")
    bus.authorize("aggregator", "retrospector")
    assert bus.is_authorized("aggregator", "retrospector")
    ok = bus.handoff("aggregator", "retrospector", "t1", "交接")
    assert ok is True
    assert len(bus.peek("retrospector")) == 1
    # 撤销后再次发布被拒
    bus.revoke("aggregator", "retrospector")
    ok2 = bus.feedback("aggregator", "retrospector", "t1", "不再允许")
    assert ok2 is False


def test_handoff_and_receive():
    """handoff 消息可被接收方收到并消费。"""
    bus = AgentBus()
    bus.handoff("fixer", "tester", "t1", "已修复，请测试")
    msgs = bus.receive("tester")
    assert len(msgs) == 1
    assert msgs[0].msg_type == MessageType.TASK_HANDOFF
    assert msgs[0].content == "已修复，请测试"
    # 已消费，peek 为空
    assert bus.peek("tester") == []


def test_peek_does_not_consume():
    """peek 查看不消费（用授权方向 aggregator→rootcause 测）。"""
    bus = AgentBus()
    bus.query("aggregator", "rootcause", "t1", "请补充影响面")
    assert len(bus.peek("rootcause")) == 1
    assert len(bus.peek("rootcause")) == 1  # 仍存在
    assert len(bus.receive("rootcause")) == 1  # receive 才消费


def test_history_filter_by_task_and_type():
    """消息历史可按 task_id / msg_type 过滤。"""
    bus = AgentBus()
    bus.handoff("aggregator", "rootcause", "t1", "spec ready")
    bus.feedback("tester", "fixer", "t2", "测试失败")
    bus.alert("leader", "fixer", "t1", "超时告警")

    assert len(bus.history(task_id="t1")) == 2
    assert len(bus.history(msg_type="TASK_HANDOFF")) == 1
    assert len(bus.history(task_id="t1", msg_type="ALERT")) == 1
    assert len(bus.history(limit=1)) == 1


def test_message_to_dict():
    """AgentMessage.to_dict 把枚举转字符串。"""
    msg = AgentMessage(
        msg_id="m1", msg_type=MessageType.TASK_HANDOFF,
        sender="a", receiver="b", content="x",
    )
    d = msg.to_dict()
    assert d["msg_type"] == "TASK_HANDOFF"
    assert d["sender"] == "a"


# --------------------------------------------------------------------------- #
# EventBus: 订阅 / 通配符 / 回调 / 历史
# --------------------------------------------------------------------------- #

def test_event_bus_subscribe_and_emit_sync():
    """同步回调触发。"""
    bus = EventBus()
    seen: list[str] = []

    def on_milestone(event: Event):
        seen.append(event.data.get("milestone", ""))

    bus.subscribe(EventType.MILESTONE_REACHED, on_milestone)
    bus.emit_sync(Event(
        event_id="e1", event_type=EventType.MILESTONE_REACHED,
        source="fixer", data={"milestone": "FIX_APPLIED"},
    ))
    assert seen == ["FIX_APPLIED"]


def test_event_bus_wildcard_subscribe():
    """通配符 "*" 匹配所有事件。"""
    bus = EventBus()
    seen: list[str] = []

    def on_any(event: Event):
        seen.append(event.event_type.value)

    bus.subscribe("*", on_any)
    bus.emit_sync(Event(event_id="e1", event_type=EventType.WORKER_STARTED, source="a"))
    bus.emit_sync(Event(event_id="e2", event_type=EventType.MILESTONE_REACHED, source="b"))
    assert seen == ["WORKER_STARTED", "MILESTONE_REACHED"]


def test_event_bus_history_and_filter():
    """事件历史可审计、可按类型过滤。"""
    bus = EventBus()
    bus.emit_sync(Event(event_id="e1", event_type=EventType.TASK_STARTED, source="m"))
    bus.emit_sync(Event(event_id="e2", event_type=EventType.WORKER_STARTED, source="aggregator"))
    assert len(bus.history()) == 2
    assert len(bus.history(event_type="WORKER_STARTED")) == 1
    assert len(bus.history(event_type="TASK_STARTED")) == 1


def test_event_bus_async_handler():
    """异步回调被 await。"""
    bus = EventBus()
    done: list[str] = []

    async def on_task(event: Event):
        done.append(event.event_type.value)

    bus.subscribe(EventType.TASK_COMPLETED, on_task)
    asyncio.run(bus.task_completed("t1"))
    assert done == ["TASK_COMPLETED"]


def test_event_bus_convenience_helpers():
    """便捷方法触发对应事件类型并记录历史。"""
    bus = EventBus()
    asyncio.run(bus.worker_started("fixer", "t1"))
    asyncio.run(bus.milestone_reached("fixer", "t1", "FIX_APPLIED"))
    asyncio.run(bus.milestone_failed("tester", "t1", "TEST_FAILED"))
    types = {h["event_type"] for h in bus.history()}
    assert {"WORKER_STARTED", "MILESTONE_REACHED", "MILESTONE_FAILED"} <= types
