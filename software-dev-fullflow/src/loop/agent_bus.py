"""AgentBus 消息总线 + EventBus 事件驱动（Layer 2）。

AgentBus: publish/subscribe 模式，支持 Worker 间直接通信
  - channelPolicy 约束：只有授权 peer 之间可通信
  - 消息类型：TASK_HANDOFF / FEEDBACK / QUERY / ALERT

EventBus: 事件驱动，替代同步轮询
  - 事件类型：WORKER_STARTED / WORKER_COMPLETED / MILESTONE_REACHED /
              HUMAN_INTERVENTION_REQUIRED / ERROR_OCCURRED
  - 同步/异步回调均可
  - 内置事件历史（可审计）

与 AgentTeams 的关系：
  - AgentBus → AgentTeams 的 Matrix 房间 @mention 接力
  - EventBus → AgentTeams 的 controller reconcile loop 事件
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable


# ========================================================================== #
# 1. AgentBus —— publish/subscribe 消息总线
# ========================================================================== #

class MessageType(str, Enum):
    """AgentBus 消息类型。"""
    TASK_HANDOFF = "TASK_HANDOFF"      # 任务交接：Worker A → Worker B
    FEEDBACK = "FEEDBACK"              # 反馈：下游 Worker 对上游产物的反馈
    QUERY = "QUERY"                    # 查询：Worker 向上游请求补充信息
    ALERT = "ALERT"                    # 告警：异常/超时/质量不达标


@dataclass
class AgentMessage:
    """一条 Agent 间消息。"""
    msg_id: str
    msg_type: MessageType
    sender: str                        # 发送者 Worker 名称
    receiver: str                      # 接收者 Worker 名称
    content: str
    task_id: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type.value,
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content[:500],
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class AgentBus:
    """publish/subscribe 消息总线 —— Worker 间直接通信。

    核心规则（channelPolicy）：
      - 只有授权 peer 之间可通信
      - 默认授权：PDCA 流水线上下游（aggregator→rootcause→fixer→tester→releaser→retrospector）
      - 跨 Worker 通信需显式授权

    用法：
        bus = AgentBus()
        bus.authorize("fixer", "tester")       # 授权 fixer → tester
        bus.publish(AgentMessage(...))         # 发布消息
        msgs = bus.receive("tester")           # tester 收取消息
    """

    # PDCA 流水线默认授权（上下游）
    PDCA_PIPELINE = ["aggregator", "rootcause", "fixer", "tester", "releaser", "retrospector"]

    def __init__(self):
        self._subscriptions: dict[str, list[AgentMessage]] = defaultdict(list)
        self._authorizations: set[tuple[str, str]] = set()  # (sender, receiver)
        self._history: list[dict[str, Any]] = []
        self._msg_counter = 0

        # 默认授权：PDCA 上下游
        for i in range(len(self.PDCA_PIPELINE) - 1):
            self.authorize(self.PDCA_PIPELINE[i], self.PDCA_PIPELINE[i + 1])
        # manager ↔ all
        for w in self.PDCA_PIPELINE:
            self.authorize("manager", w)
            self.authorize(w, "manager")

    # ---- 授权管理 ----

    def authorize(self, sender: str, receiver: str) -> None:
        """授权 sender → receiver 通信。"""
        self._authorizations.add((sender, receiver))

    def revoke(self, sender: str, receiver: str) -> None:
        """撤销 sender → receiver 通信授权。"""
        self._authorizations.discard((sender, receiver))

    def is_authorized(self, sender: str, receiver: str) -> bool:
        """检查 sender → receiver 是否被授权。"""
        return (sender, receiver) in self._authorizations

    def get_peers(self, worker: str) -> list[str]:
        """获取指定 Worker 的所有授权通信对象。"""
        senders = {r for s, r in self._authorizations if s == worker}
        receivers = {s for s, r in self._authorizations if r == worker}
        return sorted(senders | receivers)

    # ---- 消息发布/订阅 ----

    def publish(self, msg: AgentMessage) -> bool:
        """发布消息到总线。如果 sender→receiver 未授权，返回 False。"""
        if not self.is_authorized(msg.sender, msg.receiver):
            return False

        self._subscriptions[msg.receiver].append(msg)
        self._history.append(msg.to_dict())
        return True

    def receive(self, worker: str, clear: bool = True) -> list[AgentMessage]:
        """收取指定 Worker 的所有待处理消息。"""
        msgs = self._subscriptions.get(worker, [])
        if clear:
            self._subscriptions[worker] = []
        return msgs

    def peek(self, worker: str) -> list[AgentMessage]:
        """查看消息但不消费。"""
        return list(self._subscriptions.get(worker, []))

    # ---- 便捷方法 ----

    def handoff(self, sender: str, receiver: str, task_id: str, content: str,
                metadata: dict[str, Any] | None = None) -> bool:
        """发送任务交接消息。"""
        self._msg_counter += 1
        return self.publish(AgentMessage(
            msg_id=f"handoff-{self._msg_counter}",
            msg_type=MessageType.TASK_HANDOFF,
            sender=sender, receiver=receiver,
            content=content, task_id=task_id,
            metadata=metadata or {},
        ))

    def feedback(self, sender: str, receiver: str, task_id: str, content: str) -> bool:
        """发送反馈消息（打回场景）。"""
        self._msg_counter += 1
        return self.publish(AgentMessage(
            msg_id=f"feedback-{self._msg_counter}",
            msg_type=MessageType.FEEDBACK,
            sender=sender, receiver=receiver,
            content=content, task_id=task_id,
        ))

    def query(self, sender: str, receiver: str, task_id: str, question: str) -> bool:
        """发送查询消息。"""
        self._msg_counter += 1
        return self.publish(AgentMessage(
            msg_id=f"query-{self._msg_counter}",
            msg_type=MessageType.QUERY,
            sender=sender, receiver=receiver,
            content=question, task_id=task_id,
        ))

    def alert(self, sender: str, receiver: str, task_id: str, alert_text: str) -> bool:
        """发送告警消息。"""
        self._msg_counter += 1
        return self.publish(AgentMessage(
            msg_id=f"alert-{self._msg_counter}",
            msg_type=MessageType.ALERT,
            sender=sender, receiver=receiver,
            content=alert_text, task_id=task_id,
        ))

    # ---- 查询 ----

    def history(self, task_id: str = "", msg_type: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """查询消息历史。"""
        results = self._history
        if task_id:
            results = [h for h in results if h.get("task_id") == task_id]
        if msg_type:
            results = [h for h in results if h.get("msg_type") == msg_type]
        return results[-limit:]

    def snapshot(self) -> dict[str, Any]:
        return {
            "pending_messages": sum(len(v) for v in self._subscriptions.values()),
            "authorized_channels": len(self._authorizations),
            "total_history": len(self._history),
            "workers_with_pending": list(self._subscriptions.keys()),
        }


# ========================================================================== #
# 2. EventBus —— 事件驱动
# ========================================================================== #

class EventType(str, Enum):
    """EventBus 事件类型。"""
    WORKER_STARTED = "WORKER_STARTED"                      # Worker 开始执行
    WORKER_COMPLETED = "WORKER_COMPLETED"                  # Worker 执行完成
    WORKER_FAILED = "WORKER_FAILED"                        # Worker 执行失败
    MILESTONE_REACHED = "MILESTONE_REACHED"                # 里程碑达成
    MILESTONE_FAILED = "MILESTONE_FAILED"                  # 里程碑失败
    HUMAN_INTERVENTION_REQUIRED = "HUMAN_INTERVENTION_REQUIRED"  # 需要人工介入
    ERROR_OCCURRED = "ERROR_OCCURRED"                      # 异常发生
    CONTEXT_COMPACTED = "CONTEXT_COMPACTED"                # 上下文压缩
    MEMORY_PERSISTED = "MEMORY_PERSISTED"                  # 记忆持久化
    TASK_STARTED = "TASK_STARTED"                          # 任务开始
    TASK_COMPLETED = "TASK_COMPLETED"                      # 任务完成
    TASK_FAILED = "TASK_FAILED"                            # 任务失败
    TASK_TIMEOUT = "TASK_TIMEOUT"                          # 任务超时


@dataclass
class Event:
    """一个事件。"""
    event_id: str
    event_type: EventType
    source: str                            # 事件来源（Worker/Manager/System）
    task_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "source": self.source,
            "task_id": self.task_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }


# 回调类型：同步 Callable 或异步 Awaitable
EventHandler = Callable[[Event], None] | Callable[[Event], Awaitable[None]]


class EventBus:
    """事件驱动总线 —— 替代同步轮询。

    特性：
      - 支持同步/异步回调
      - 支持通配符订阅（"*" 匹配所有事件）
      - 内置事件历史（可审计）
      - 延迟触发（debounce）

    用法：
        bus = EventBus()

        async def on_milestone(event: Event):
            print(f"里程碑: {event.data['milestone']}")

        bus.subscribe(EventType.MILESTONE_REACHED, on_milestone)
        await bus.emit(Event(...))
    """

    # 需要自动处理的 Manager 关注事件（默认由 Manager 的 _handle_event 处理）
    MANAGER_EVENTS = {
        EventType.MILESTONE_REACHED,
        EventType.MILESTONE_FAILED,
        EventType.HUMAN_INTERVENTION_REQUIRED,
        EventType.ERROR_OCCURRED,
        EventType.TASK_TIMEOUT,
    }

    def __init__(self):
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: list[dict[str, Any]] = []
        self._event_counter = 0
        self._pending_tasks: dict[str, asyncio.Task] = {}  # debounce tasks

    # ---- 订阅 ----

    def subscribe(self, event_type: EventType | str, handler: EventHandler) -> None:
        """订阅事件。支持 "*" 通配。"""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        self._subscribers[key].append(handler)

    def unsubscribe(self, event_type: EventType | str, handler: EventHandler) -> None:
        """取消订阅。"""
        key = event_type.value if isinstance(event_type, EventType) else event_type
        try:
            self._subscribers[key].remove(handler)
        except ValueError:
            pass

    # ---- 触发 ----

    async def emit(self, event: Event) -> None:
        """触发事件，通知所有订阅者。"""
        self._history.append(event.to_dict())

        # 通知匹配的订阅者
        handlers = list(self._subscribers.get(event.event_type.value, []))
        handlers.extend(self._subscribers.get("*", []))

        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                print(f"  [EventBus] 事件处理异常 ({event.event_type.value}): {e}")

    def emit_sync(self, event: Event) -> None:
        """同步触发事件（仅同步回调）。"""
        self._history.append(event.to_dict())
        handlers = list(self._subscribers.get(event.event_type.value, []))
        handlers.extend(self._subscribers.get("*", []))

        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    # 异步回调在同步模式跳过
                    pass
            except Exception as e:
                print(f"  [EventBus] 事件处理异常 ({event.event_type.value}): {e}")

    # ---- 便捷方法 ----

    async def worker_started(self, worker: str, task_id: str, data: dict[str, Any] | None = None) -> None:
        self._event_counter += 1
        await self.emit(Event(
            event_id=f"evt-{self._event_counter}",
            event_type=EventType.WORKER_STARTED,
            source=worker, task_id=task_id,
            data=data or {},
        ))

    async def worker_completed(self, worker: str, task_id: str, milestone: str,
                               elapsed: float = 0, data: dict[str, Any] | None = None) -> None:
        self._event_counter += 1
        await self.emit(Event(
            event_id=f"evt-{self._event_counter}",
            event_type=EventType.WORKER_COMPLETED,
            source=worker, task_id=task_id,
            data={"milestone": milestone, "elapsed": elapsed, **(data or {})},
        ))

    async def milestone_reached(self, worker: str, task_id: str, milestone: str,
                                data: dict[str, Any] | None = None) -> None:
        self._event_counter += 1
        await self.emit(Event(
            event_id=f"evt-{self._event_counter}",
            event_type=EventType.MILESTONE_REACHED,
            source=worker, task_id=task_id,
            data={"milestone": milestone, **(data or {})},
        ))

    async def milestone_failed(self, worker: str, task_id: str, milestone: str,
                               data: dict[str, Any] | None = None) -> None:
        self._event_counter += 1
        await self.emit(Event(
            event_id=f"evt-{self._event_counter}",
            event_type=EventType.MILESTONE_FAILED,
            source=worker, task_id=task_id,
            data={"milestone": milestone, **(data or {})},
        ))

    async def worker_failed(self, worker: str, task_id: str,
                            data: dict[str, Any] | None = None) -> None:
        self._event_counter += 1
        await self.emit(Event(
            event_id=f"evt-{self._event_counter}",
            event_type=EventType.WORKER_FAILED,
            source=worker, task_id=task_id,
            data=data or {},
        ))

    async def human_intervention(self, task_id: str, reason: str,
                                 data: dict[str, Any] | None = None) -> None:
        self._event_counter += 1
        await self.emit(Event(
            event_id=f"evt-{self._event_counter}",
            event_type=EventType.HUMAN_INTERVENTION_REQUIRED,
            source="manager", task_id=task_id,
            data={"reason": reason, **(data or {})},
        ))

    async def error_occurred(self, source: str, task_id: str, error: str,
                             data: dict[str, Any] | None = None) -> None:
        self._event_counter += 1
        await self.emit(Event(
            event_id=f"evt-{self._event_counter}",
            event_type=EventType.ERROR_OCCURRED,
            source=source, task_id=task_id,
            data={"error": error, **(data or {})},
        ))

    async def task_started(self, task_id: str, spec: str = "",
                           data: dict[str, Any] | None = None) -> None:
        self._event_counter += 1
        await self.emit(Event(
            event_id=f"evt-{self._event_counter}",
            event_type=EventType.TASK_STARTED,
            source="manager", task_id=task_id,
            data={"spec": spec, **(data or {})},
        ))

    async def task_completed(self, task_id: str,
                             data: dict[str, Any] | None = None) -> None:
        self._event_counter += 1
        await self.emit(Event(
            event_id=f"evt-{self._event_counter}",
            event_type=EventType.TASK_COMPLETED,
            source="manager", task_id=task_id,
            data=data or {},
        ))

    # ---- 查询 ----

    def history(self, event_type: str = "", task_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """查询事件历史。"""
        results = self._history
        if event_type:
            results = [h for h in results if h.get("event_type") == event_type]
        if task_id:
            results = [h for h in results if h.get("task_id") == task_id]
        return results[-limit:]

    def snapshot(self) -> dict[str, Any]:
        return {
            "total_events": len(self._history),
            "subscribers": {k: len(v) for k, v in self._subscribers.items()},
            "event_types_seen": list(set(h["event_type"] for h in self._history[-100:])),
        }


# ========================================================================== #
# 3. 自检
# ========================================================================== #

async def _self_test():
    """快速自检。"""
    print("=== AgentBus + EventBus 自检 ===")

    # 1. AgentBus
    bus = AgentBus()

    # 授权检查
    assert bus.is_authorized("fixer", "tester")        # PDCA 默认授权
    assert bus.is_authorized("manager", "fixer")       # manager ↔ all
    assert not bus.is_authorized("fixer", "aggregator")  # 反向未授权

    # 消息发布
    ok = bus.handoff("fixer", "tester", "task-001", "修复完成，请测试")
    assert ok
    msgs = bus.receive("tester")
    assert len(msgs) == 1
    assert msgs[0].msg_type == MessageType.TASK_HANDOFF
    assert msgs[0].sender == "fixer"
    print("✓ AgentBus pub/sub")

    # 未授权拒绝
    ok = bus.handoff("tester", "aggregator", "task-001", "不应该到达")
    assert not ok
    print("✓ AgentBus channelPolicy")

    # 2. EventBus
    eb = EventBus()
    received_events: list[Event] = []

    async def handler(event: Event):
        received_events.append(event)

    eb.subscribe(EventType.MILESTONE_REACHED, handler)

    await eb.worker_started("fixer", "task-001")
    await eb.milestone_reached("fixer", "task-001", "FIX_APPLIED")
    await eb.worker_completed("fixer", "task-001", "FIX_APPLIED", elapsed=5.0)

    assert len(received_events) == 1  # 只订阅了 MILESTONE_REACHED
    assert received_events[0].data["milestone"] == "FIX_APPLIED"
    print("✓ EventBus subscribe/emit")

    # 通配符订阅
    wildcard_events: list[Event] = []

    async def wildcard_handler(event: Event):
        wildcard_events.append(event)

    eb.subscribe("*", wildcard_handler)
    await eb.error_occurred("fixer", "task-001", "test error")
    assert len(wildcard_events) == 1
    print("✓ EventBus wildcard")

    # 历史
    history = eb.history(task_id="task-001")
    assert len(history) >= 4
    print("✓ EventBus history")

    print("=== 自检通过 ===")


if __name__ == "__main__":
    asyncio.run(_self_test())