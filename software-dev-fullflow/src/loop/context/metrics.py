"""性能监控 —— 上下文利用率 + 记忆留存率。"""

from __future__ import annotations

import time
from typing import Any


class PerformanceMetrics:
    """性能监控。

    监控维度：
      1. 上下文利用率（average_utilization / overflow_count / compact_count）
      2. 记忆留存率（short_term_hit_rate / medium_term_access_count / long_term_cite_count）
      3. 迭代效率（iterations_per_task / verification_pass_rate）
    """

    def __init__(self):
        self._events: list[dict[str, Any]] = []
        self._thresholds = {
            "utilization_low": 0.30,       # 利用率低于 30% 说明浪费
            "utilization_high": 0.85,      # 利用率高于 85% 有溢出风险
            "utilization_target": 0.55,    # 目标利用率
            "retention_decay_limit": 0.50,  # 记忆留存率下限
        }

    # ---- 记录 ----

    def record(self, event_type: str, data: dict[str, Any]) -> None:
        self._events.append({
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        })

    # ---- 查询 ----

    def average_utilization(self) -> float:
        """计算平均上下文利用率。"""
        utilizations = []
        for e in self._events:
            if e["type"] == "iteration_finished":
                budget = e["data"].get("budget_snapshot", {})
                util = budget.get("utilization", 0)
                if util > 0:
                    utilizations.append(util)
        if not utilizations:
            return 0.0
        return sum(utilizations) / len(utilizations)

    def overflow_rate(self) -> float:
        """溢出率。"""
        total_iterations = sum(1 for e in self._events if e["type"] == "iteration_finished")
        if total_iterations == 0:
            return 0.0
        overflows = sum(
            e["data"].get("budget_snapshot", {}).get("overflow_count", 0)
            for e in self._events if e["type"] == "iteration_finished"
        )
        return overflows / total_iterations

    def compact_frequency(self) -> float:
        """平均每次迭代的压缩次数。"""
        total_iterations = sum(1 for e in self._events if e["type"] == "iteration_finished")
        if total_iterations == 0:
            return 0.0
        compacts = sum(1 for e in self._events if e["type"] == "micro_compact")
        return compacts / total_iterations

    def memory_retention_score(self) -> float:
        """记忆留存率综合评分（0.0 ~ 1.0）。"""
        memory_snapshots = [
            e["data"] for e in self._events if e["type"] == "memory_persisted"
        ]
        if not memory_snapshots:
            return 0.0

        last = memory_snapshots[-1]
        short = last.get("short", {})
        medium = last.get("medium", {})
        long_ = last.get("long", {})

        short_score = min(1.0, short.get("entry_count", 0) / 10.0)
        medium_score = min(1.0, medium.get("iteration_count", 0) / 20.0)
        long_score = min(1.0, long_.get("total_entries", 0) / 50.0)

        return (short_score * 0.3 + medium_score * 0.3 + long_score * 0.4)

    def is_healthy(self) -> tuple[bool, list[str]]:
        """健康检查。返回 (是否健康, 告警列表)。"""
        alerts = []
        avg_util = self.average_utilization()

        if avg_util < self._thresholds["utilization_low"]:
            alerts.append(f"利用率过低: {avg_util:.1%} < {self._thresholds['utilization_low']:.0%}")
        if avg_util > self._thresholds["utilization_high"]:
            alerts.append(f"利用率过高: {avg_util:.1%} > {self._thresholds['utilization_high']:.0%}")

        retention = self.memory_retention_score()
        if retention < self._thresholds["retention_decay_limit"]:
            alerts.append(f"记忆留存率过低: {retention:.1%} < {self._thresholds['retention_decay_limit']:.0%}")

        return len(alerts) == 0, alerts

    def report(self) -> str:
        """生成可读报告。"""
        healthy, alerts = self.is_healthy()
        return (
            f"=== 上下文工程性能报告 ===\n"
            f"平均上下文利用率: {self.average_utilization():.1%}\n"
            f"溢出率:           {self.overflow_rate():.2f}/迭代\n"
            f"平均压缩次数:     {self.compact_frequency():.2f}/迭代\n"
            f"记忆留存率:       {self.memory_retention_score():.1%}\n"
            f"健康状态:         {'✅ 健康' if healthy else '⚠️ 告警'}\n"
            + (f"告警:             {'; '.join(alerts)}\n" if alerts else "")
            + f"事件总数:         {len(self._events)}\n"
        )

    def snapshot(self) -> dict[str, Any]:
        healthy, alerts = self.is_healthy()
        return {
            "average_utilization": round(self.average_utilization(), 3),
            "overflow_rate": round(self.overflow_rate(), 3),
            "compact_frequency": round(self.compact_frequency(), 3),
            "memory_retention_score": round(self.memory_retention_score(), 3),
            "healthy": healthy,
            "alerts": alerts,
            "event_count": len(self._events),
        }
