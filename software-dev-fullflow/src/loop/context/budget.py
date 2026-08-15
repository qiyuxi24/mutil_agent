"""上下文预算 —— 70/30 分区分配 + 按阶段自适应调整。

与 Ralph 反压原则一致：预算控制是确定性的，不依赖 LLM 自律。
"""

from __future__ import annotations

from dataclasses import dataclass

from .estimator import TokenEstimator


@dataclass
class ContextSlice:
    """上下文预算中的一个分区。"""

    name: str
    budget: int                               # 分配的 token 上限
    content: str = ""
    _used: int = 0

    @property
    def used(self) -> int:
        return TokenEstimator.estimate(self.content)

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.used)

    @property
    def utilization(self) -> float:
        """利用率 0.0 ~ 1.0。"""
        return self.used / self.budget if self.budget > 0 else 0.0

    def fits(self, text: str) -> bool:
        """检查 text 是否能放入剩余空间。"""
        return TokenEstimator.estimate(text) <= self.remaining


class ContextBudget:
    """上下文预算管理器。

    核心规则：
      - critical 区（默认 70%）：system prompt + 当前任务 + 关键产出
      - support 区（默认 30%）：历史、背景、辅助信息
      - 70% 利用率触发轻压缩（micro-compact）
      - 85% 利用率触发强制压缩（auto-compact）
    """

    MICRO_COMPACT_THRESHOLD = 0.70   # 轻压缩触发阈值
    AUTO_COMPACT_THRESHOLD = 0.85    # 强制压缩触发阈值
    OUTPUT_BUFFER = 0.10             # 输出缓冲（从总额中预留）

    def __init__(self, total_budget: int = 32000,
                 critical_ratio: float = 0.70, support_ratio: float = 0.30):
        """
        Args:
            total_budget: 总 token 预算（默认 32K）。
            critical_ratio: critical 区占比（0.0~1.0）。
            support_ratio: support 区占比（0.0~1.0），与 critical_ratio 之和应为 1.0。
        """
        if not 0.0 <= critical_ratio <= 1.0:
            raise ValueError(f"critical_ratio 必须在 [0,1]，实际 {critical_ratio}")
        if abs(critical_ratio + support_ratio - 1.0) > 0.01:
            raise ValueError(
                f"critical_ratio + support_ratio 必须 = 1.0，"
                f"实际 {critical_ratio} + {support_ratio}"
            )
        self.total_budget = total_budget
        self._critical_ratio = critical_ratio
        self._support_ratio = support_ratio
        output_reserve = int(total_budget * self.OUTPUT_BUFFER)
        available = total_budget - output_reserve

        self.critical = ContextSlice(
            name="critical",
            budget=int(available * critical_ratio),
        )
        self.support = ContextSlice(
            name="support",
            budget=int(available * support_ratio),
        )
        self.output_reserve = output_reserve

        # 追踪
        self._total_used_ever = 0
        self._compact_count = 0
        self._overflow_count = 0

    # ---- 查询 ----

    @property
    def total_used(self) -> int:
        return self.critical.used + self.support.used

    @property
    def utilization(self) -> float:
        """整体利用率 0.0 ~ 1.0。"""
        return self.total_used / self.total_budget if self.total_budget > 0 else 0.0

    @property
    def needs_micro_compact(self) -> bool:
        return self.utilization >= self.MICRO_COMPACT_THRESHOLD

    @property
    def needs_auto_compact(self) -> bool:
        return self.utilization >= self.AUTO_COMPACT_THRESHOLD

    # ---- 分配 ----

    def allocate(self, text: str, zone: str = "critical") -> str:
        """将 text 分配到指定分区，返回实际放入的内容（可能被截断）。"""
        target = self.critical if zone == "critical" else self.support
        if target.fits(text):
            target.content += text
            return text
        # 超出预算：截断后放入
        self._overflow_count += 1
        truncated = self._truncate_to_fit(text, target.remaining)
        target.content += truncated
        return truncated

    def allocate_critical(self, text: str) -> str:
        """分配关键内容（critical 区）。"""
        return self.allocate(text, "critical")

    def allocate_support(self, text: str) -> str:
        """分配非关键内容（support 区）。"""
        return self.allocate(text, "support")

    # ---- 压缩 ----

    def micro_compact(self) -> int:
        """轻压缩：截断 support 区中旧工具结果，保留最近部分。

        返回释放的 token 数。
        """
        before = self.support.used
        keep_ratio = 0.6
        keep_tokens = int(self.support.budget * keep_ratio)
        if self.support.used <= keep_tokens:
            return 0
        content = self.support.content
        keep_chars = int(len(content) * keep_ratio)
        self.support.content = content[-keep_chars:]
        self._compact_count += 1
        return before - self.support.used

    def reset(self) -> None:
        """重置所有分区（用于新迭代周期）。"""
        self.critical.content = ""
        self.support.content = ""
        self._total_used_ever += self.total_used

    # ---- 内部 ----

    def _truncate_to_fit(self, text: str, max_tokens: int) -> str:
        """按 token 预算截断文本，保留头部和尾部。"""
        if max_tokens <= 0:
            return ""
        head_ratio = 0.7  # 保留 70% 头部
        head_tokens = int(max_tokens * head_ratio)
        tail_tokens = max_tokens - head_tokens

        head_text = self._take_tokens(text, head_tokens)
        if tail_tokens <= 0:
            return head_text + "\n...(truncated)"

        tail_text = self._take_tokens(text, tail_tokens, from_tail=True)
        return f"{head_text}\n...(truncated, {TokenEstimator.estimate(text) - max_tokens} tokens omitted)...\n{tail_text}"

    @staticmethod
    def _take_tokens(text: str, max_tokens: int, from_tail: bool = False) -> str:
        """从文本头部或尾部截取最多 max_tokens 的内容。"""
        if from_tail:
            text = text[::-1]
        result_chars = []
        token_count = 0
        for ch in text:
            ch_tokens = 1.0 / TokenEstimator.ZH_CHARS_PER_TOKEN if '\u4e00' <= ch <= '\u9fff' else 1.0 / TokenEstimator.EN_CHARS_PER_TOKEN
            if token_count + ch_tokens > max_tokens:
                break
            result_chars.append(ch)
            token_count += ch_tokens
        result = ''.join(result_chars)
        return result[::-1] if from_tail else result

    def snapshot(self) -> dict:
        """返回可序列化的快照。"""
        return {
            "total_budget": self.total_budget,
            "critical": {"budget": self.critical.budget, "used": self.critical.used},
            "support": {"budget": self.support.budget, "used": self.support.used},
            "output_reserve": self.output_reserve,
            "utilization": round(self.utilization, 3),
            "compact_count": self._compact_count,
            "overflow_count": self._overflow_count,
        }


class StageBudget:
    """单个阶段的预算配置。"""

    def __init__(self, critical_ratio: float, support_ratio: float):
        assert abs(critical_ratio + support_ratio - 1.0) < 0.01, \
            f"critical + support 必须 = 1.0，实际 {critical_ratio} + {support_ratio}"
        self.critical_ratio = critical_ratio
        self.support_ratio = support_ratio


class DynamicBudgetAllocator:
    """按阶段自适应调整 critical/support 比例。

    替代静态 70/30 分配，根据当前 PDCA 阶段动态调整：
      - SPEC_INPUT: 50/50（聚合需要大量背景）
      - ROOT_CAUSE: 75/25（定位需要精确上下文）
      - FIX_APPLY: 80/20（编码需要精确规格）
      - TEST_VERIFY: 60/40（测试需要广泛覆盖）
      - RELEASE: 70/30
      - RETROSPECT: 40/60（复盘需要全量回顾）
    """

    # 各阶段预算配置
    STAGE_CONFIGS: dict[str, StageBudget] = {
        "SPEC_INPUT": StageBudget(critical_ratio=0.50, support_ratio=0.50),
        "SPEC_DECOMPOSE": StageBudget(critical_ratio=0.50, support_ratio=0.50),
        "ROOT_CAUSE": StageBudget(critical_ratio=0.75, support_ratio=0.25),
        "FIX_APPLY": StageBudget(critical_ratio=0.80, support_ratio=0.20),
        "TEST_VERIFY": StageBudget(critical_ratio=0.60, support_ratio=0.40),
        "RELEASE": StageBudget(critical_ratio=0.70, support_ratio=0.30),
        "RELEASE_APPROVE": StageBudget(critical_ratio=0.70, support_ratio=0.30),
        "RETROSPECT": StageBudget(critical_ratio=0.40, support_ratio=0.60),
    }

    # 默认配置（未匹配阶段使用）
    DEFAULT_BUDGET = StageBudget(critical_ratio=0.70, support_ratio=0.30)

    @classmethod
    def get_budget(cls, stage: str) -> StageBudget:
        """获取指定阶段的预算配置。"""
        return cls.STAGE_CONFIGS.get(stage.upper(), cls.DEFAULT_BUDGET)

    @classmethod
    def create_context_budget(cls, stage: str, total_budget: int = 32000) -> "ContextBudget":
        """为指定阶段创建一个 ContextBudget 实例。

        通过构造参数传入阶段比例，避免修改类级常量，保证各实例互不影响。
        """
        config = cls.get_budget(stage)
        return ContextBudget(
            total_budget=total_budget,
            critical_ratio=config.critical_ratio,
            support_ratio=config.support_ratio,
        )

    @classmethod
    def stage_summary(cls) -> str:
        """返回各阶段预算配置的可读摘要。"""
        lines = ["=== 动态预算分配（按阶段）==="]
        for stage, config in cls.STAGE_CONFIGS.items():
            lines.append(
                f"  {stage:<20} critical {config.critical_ratio:.0%} / "
                f"support {config.support_ratio:.0%}"
            )
        return "\n".join(lines)
