"""AgentBus 消息总线（Layer 2）。

publish/subscribe 模式，支持 Worker 间直接通信：
  - channelPolicy 约束：只有授权 peer 之间可通信
  - 消息类型：TASK_HANDOFF / FEEDBACK / QUERY / ALERT

对应 AgentTeams 的 Matrix 房间 @mention 接力。

EventBus 事件驱动已拆分为独立模块 `loop/event_bus.py`（为兼容 `from loop.agent_bus import EventBus`
在此 re-export）。
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# 兼容性 re-export：EventBus 实际在 event_bus.py
from .event_bus import Event, EventBus, EventHandler, EventType  # noqa: F401


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
