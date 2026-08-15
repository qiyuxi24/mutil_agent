"""上下文工程（Context Engineering）—— Ralph 式落地。

四大策略落地为可调用工具函数：
  1. 信息卸载（Offloading）  → offload_to_file / offload_tool_results
  2. 压缩整合（Compaction）   → compact_history / trim_context
  3. 按需检索（On-Demand）   → 引用路径代替完整内容
  4. 注意力操纵（Attention）  → budget_allocate 分区优先

三层记忆架构（独立于上下文窗口的持久化存储）：
  - ShortTermMemory  → 当前迭代操作记忆（dict + JSON）
  - MediumTermMemory → 跨迭代关系记忆（决策点、改进机会）
  - LongTermMemory   → 累积知识记忆（领域模式、经验教训）

核心原则（Ralph 反压）：
  - 预算控制是确定性的，不依赖 LLM 自律
  - 压缩触发阈值由 token 估算判定，不做 LLM 自评
  - 记忆持久化独立于上下文窗口，不依赖上下文实现记忆

本包拆分为多个子模块以降低单文件复杂度：
  estimator.py     — TokenEstimator（token 估算）
  budget.py        — ContextSlice / ContextBudget / StageBudget / DynamicBudgetAllocator
  memory_tiers.py  — 三层记忆（ShortTerm / MediumTerm / LongTerm）
  agent_memory.py  — AgentMemory（按 Agent 维度的独立记忆）
  semantic_search.py — SemanticMemorySearch（TF-IDF / embedding 降级检索）
  protocol.py      — IterationProtocol（迭代周期）
  metrics.py       — PerformanceMetrics（性能监控）
  manager.py       — ContextManager（编排器）
  utils.py         — 便捷工具函数（ctx-1 四个函数签名）

对外 API 与旧的单文件 context.py 完全一致，`from loop.context import X` 不受影响。
"""

from __future__ import annotations

from .agent_memory import (
    AgentMemory,
    AgentMemoryEntry,
)
from .budget import (
    ContextBudget,
    ContextSlice,
    DynamicBudgetAllocator,
    StageBudget,
)
from .estimator import TokenEstimator
from .manager import ContextManager
from .memory_tiers import (
    LongTermMemory,
    MediumTermMemory,
    MemoryEntry,
    MemoryTier,
    ShortTermMemory,
)
from .metrics import PerformanceMetrics
from .protocol import (
    IterationCriteria,
    IterationPhase,
    IterationProtocol,
)
from .semantic_search import SemanticMemorySearch
from .utils import (
    budget_allocate,
    compact_history,
    offload_to_file,
    trim_context,
)

__all__ = [
    # estimator
    "TokenEstimator",
    # budget
    "ContextSlice", "ContextBudget", "StageBudget", "DynamicBudgetAllocator",
    # memory
    "MemoryTier", "MemoryEntry",
    "ShortTermMemory", "MediumTermMemory", "LongTermMemory",
    "AgentMemoryEntry", "AgentMemory", "SemanticMemorySearch",
    # protocol
    "IterationPhase", "IterationCriteria", "IterationProtocol",
    # metrics
    "PerformanceMetrics",
    # manager
    "ContextManager",
    # utils
    "trim_context", "compact_history", "budget_allocate", "offload_to_file",
]
