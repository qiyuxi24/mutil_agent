"""迭代协议 —— 结构化迭代周期。

每个迭代周期包含五个阶段：ENTRY → EXECUTE → VALIDATE → MEMORY_UPDATE → EXIT。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IterationPhase(Enum):
    """迭代阶段。"""

    ENTRY = "entry"           # 入口：加载记忆、设定预算
    EXECUTE = "execute"       # 执行：核心操作
    VALIDATE = "validate"     # 验证：反压校验
    MEMORY_UPDATE = "memory"  # 记忆更新：持久化结果
    EXIT = "exit"             # 出口：清理、报告


@dataclass
class IterationCriteria:
    """迭代的 entry/exit 条件。"""

    # Entry 条件
    min_context_available: int = 4000       # 最小可用上下文 token
    max_retry_count: int = 3                # 最大重试次数
    require_memory_loaded: bool = True      # 是否需要记忆已加载

    # Exit 条件
    pass_verification: bool = False         # 是否通过反压校验
    max_iterations_reached: bool = False    # 是否达到最大迭代数
    context_overflow: bool = False          # 上下文是否溢出


class IterationProtocol:
    """结构化迭代协议。

    触发条件：
      - 记忆更新触发：每次 EXECUTE 完成后自动触发
      - 上下文刷新触发：utilization >= 70% 时触发 micro_compact
    """

    def __init__(self, max_iterations: int = 10):
        self.max_iterations = max_iterations
        self.current_iteration = 0
        self.current_phase = IterationPhase.ENTRY
        self.phase_history: list[dict[str, Any]] = []
        self.criteria = IterationCriteria()

    # ---- 周期控制 ----

    def can_enter(self, budget) -> tuple[bool, str]:
        """检查是否满足 entry 条件。"""
        if self.current_iteration >= self.max_iterations:
            self.criteria.max_iterations_reached = True
            return False, f"达到最大迭代数 {self.max_iterations}"
        if budget.total_budget - budget.total_used < self.criteria.min_context_available:
            return False, f"可用上下文不足: {budget.total_budget - budget.total_used} < {self.criteria.min_context_available}"
        return True, "OK"

    def can_exit(self, verification_passed: bool) -> tuple[bool, str]:
        """检查是否满足 exit 条件。"""
        if verification_passed:
            self.criteria.pass_verification = True
            return True, "验证通过"
        if self.current_iteration >= self.max_iterations:
            self.criteria.max_iterations_reached = True
            return True, f"达到最大迭代数 {self.max_iterations}"
        return False, "继续迭代"

    def advance_phase(self, next_phase: IterationPhase) -> None:
        """推进到下一阶段。"""
        self.phase_history.append({
            "from": self.current_phase.value,
            "to": next_phase.value,
            "iteration": self.current_iteration,
            "timestamp": time.time(),
        })
        self.current_phase = next_phase

    def next_iteration(self) -> None:
        """进入下一迭代。"""
        self.current_iteration += 1
        self.current_phase = IterationPhase.ENTRY

    def should_refresh_context(self, budget) -> bool:
        """判断是否需要刷新上下文（触发 micro_compact）。"""
        return budget.needs_micro_compact

    def should_persist_memory(self) -> bool:
        """判断是否需要持久化记忆（每次 EXECUTE 后都持久化）。"""
        return self.current_phase in (IterationPhase.EXECUTE, IterationPhase.VALIDATE)

    def snapshot(self) -> dict:
        return {
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "current_phase": self.current_phase.value,
            "criteria": {
                "pass_verification": self.criteria.pass_verification,
                "max_iterations_reached": self.criteria.max_iterations_reached,
                "context_overflow": self.criteria.context_overflow,
            },
            "phase_history_len": len(self.phase_history),
        }
