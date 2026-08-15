"""EventBus 事件驱动总线 —— 替代同步轮询（Layer 2）。

特性：
  - 支持同步/异步回调
  - 支持通配符订阅（"*" 匹配所有事件）
  - 内置事件历史（可审计）
  - 延迟触发（debounce）

对应 AgentTeams 的 controller reconcile loop 事件。
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable


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
