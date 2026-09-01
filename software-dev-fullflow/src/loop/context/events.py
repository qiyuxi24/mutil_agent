"""上下文工程事件常量 —— 类型化事件 schema。

ContextManager 与 PerformanceMetrics 之间通过 `record(event_type, data)` 交换事件。
本模块将散布的魔法字符串收敛为类型化常量，保证双方对事件名称与数据结构
保持一致的契约，便于解耦、复用与测试。
"""

from __future__ import annotations

from typing import Final


class ContextEvent:
    """ContextManager → PerformanceMetrics 的事件名称常量。"""

    # 迭代生命周期
    ITERATION_STARTED: Final[str] = "iteration_started"
    ITERATION_FINISHED: Final[str] = "iteration_finished"
    ITERATION_BLOCKED: Final[str] = "iteration_blocked"
    # 上下文分配
    MICRO_COMPACT: Final[str] = "micro_compact"
    # 记忆持久化
    MEMORY_PERSISTED: Final[str] = "memory_persisted"
