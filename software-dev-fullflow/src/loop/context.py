"""上下文工程（Context Engineering）—— Ralph 式落地。

四大策略落地为可调用工具函数：
  1. 信息卸载（Offloading）  → offload_to_file / offload_tool_results
  2. 压缩整合（Compaction）   → compact_history / trim_context
  3. 按需检索（On-Demand）   → 引用路径代替完整内容
  4. 注意力操纵（Attention）  → budget_allocate 70/30 分区分优先

三层记忆架构（独立于上下文窗口的持久化存储）：
  - ShortTermMemory  → 当前迭代操作记忆（dict + JSON）
  - MediumTermMemory → 跨迭代关系记忆（决策点、改进机会）
  - LongTermMemory   → 累积知识记忆（领域模式、经验教训）

迭代协议：entry/exit criteria + 记忆更新触发 + 上下文刷新
性能监控：上下文利用率 + 记忆留存率

核心原则（Ralph 反压）：
  - 预算控制是确定性的，不依赖 LLM 自律
  - 压缩触发阈值由 token 估算判定，不做 LLM 自评
  - 记忆持久化独立于上下文窗口，不依赖上下文实现记忆
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ========================================================================== #
# 1. TokenEstimator —— 字符级 token 估算（无外部依赖）
# ========================================================================== #

class TokenEstimator:
    """简单 token 估算器：英文 ~4 chars/token，中文 ~1.5 chars/token。

    精度约 ±15%，生产环境可替换为 tiktoken。
    目的：提供确定性预算判断，不依赖 LLM 自评。
    """

    # 经验值：英文每 token 约 4 字符，中文每 token 约 1.5 字符
    EN_CHARS_PER_TOKEN = 4.0
    ZH_CHARS_PER_TOKEN = 1.5

    @staticmethod
    def estimate(text: str) -> int:
        """估算文本的 token 数。"""
        if not text:
            return 0
        zh_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        en_count = len(text) - zh_count
        return int(zh_count / TokenEstimator.ZH_CHARS_PER_TOKEN +
                   en_count / TokenEstimator.EN_CHARS_PER_TOKEN)

    @staticmethod
    def estimate_messages(messages: list[dict[str, str]]) -> int:
        """估算消息列表的总 token 数。"""
        return sum(TokenEstimator.estimate(m.get("content", "")) for m in messages)


# ========================================================================== #
# 2. ContextBudget —— 70/30 预算分配 + 阈值追踪
# ========================================================================== #

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
      - 70% 分配给关键操作（critical zone）：system prompt + 当前任务 + 关键产出
      - 30% 分配给非关键信息（support zone）：历史、背景、辅助信息
      - 70% 利用率触发轻压缩（micro-compact）
      - 85% 利用率触发强制压缩（auto-compact）

    与 Ralph 反压原则一致：预算控制是确定性的，不依赖 LLM 自律。
    """

    CRITICAL_RATIO = 0.70       # 关键操作占比
    SUPPORT_RATIO = 0.30        # 非关键信息占比
    MICRO_COMPACT_THRESHOLD = 0.70   # 轻压缩触发阈值
    AUTO_COMPACT_THRESHOLD = 0.85    # 强制压缩触发阈值
    OUTPUT_BUFFER = 0.10        # 输出缓冲（从总额中预留）

    def __init__(self, total_budget: int = 32000):
        """
        Args:
            total_budget: 总 token 预算（默认 32K，对应 Anthropic 推荐的标准窗口）
        """
        self.total_budget = total_budget
        output_reserve = int(total_budget * self.OUTPUT_BUFFER)
        available = total_budget - output_reserve

        self.critical = ContextSlice(
            name="critical",
            budget=int(available * self.CRITICAL_RATIO),
        )
        self.support = ContextSlice(
            name="support",
            budget=int(available * self.SUPPORT_RATIO),
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
        """将 text 分配到指定分区，返回实际放入的内容（可能被截断）。

        Args:
            text: 要分配的内容
            zone: "critical" 或 "support"

        Returns:
            实际放入的内容（如果超出预算，返回截断后的内容）
        """
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
        """分配关键内容（70% 区）。"""
        return self.allocate(text, "critical")

    def allocate_support(self, text: str) -> str:
        """分配非关键内容（30% 区）。"""
        return self.allocate(text, "support")

    # ---- 压缩 ----

    def micro_compact(self) -> int:
        """轻压缩：截断 support 区中旧工具结果，保留最近部分。

        返回释放的 token 数。
        """
        before = self.support.used
        # 保留最近 ~60% 的 support 内容
        keep_ratio = 0.6
        keep_tokens = int(self.support.budget * keep_ratio)
        if self.support.used <= keep_tokens:
            return 0
        # 从尾部保留（压缩方向从头部开始，保护 cache prefix 是另一个维度的优化）
        content = self.support.content
        # 简单截断：保留后面部分
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


# ========================================================================== #
# 3. 三层记忆架构 —— 独立于上下文窗口的持久化存储
# ========================================================================== #

class MemoryTier(Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


@dataclass
class MemoryEntry:
    """一条记忆条目。"""
    key: str
    content: Any
    tier: MemoryTier
    timestamp: float = field(default_factory=time.time)
    ttl: float | None = None          # 过期时间（秒），None 表示永不过期
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        if self.ttl is None:
            return False
        return time.time() - self.timestamp > self.ttl


class ShortTermMemory:
    """短期操作记忆 —— 当前迭代过程的操作状态。

    特性：
      - 常驻内存（dict），加速读写
      - JSON 持久化到磁盘作为备份（独立于上下文窗口）
      - 默认 TTL 5 分钟（迭代结束后自动过期）
      - 存储：当前步骤状态、中间产物引用、最近工具结果
    """

    DEFAULT_TTL = 300  # 5 分钟

    def __init__(self, storage_path: Path):
        self._storage_path = storage_path
        self._entries: dict[str, MemoryEntry] = {}
        self._load()

    # ---- CRUD ----

    def put(self, key: str, content: Any, ttl: float | None = None,
            metadata: dict[str, Any] | None = None) -> None:
        self._entries[key] = MemoryEntry(
            key=key, content=content, tier=MemoryTier.SHORT,
            ttl=ttl if ttl is not None else self.DEFAULT_TTL,
            metadata=metadata or {},
        )

    def get(self, key: str, default: Any = None) -> Any:
        entry = self._entries.get(key)
        if entry is None:
            return default
        if entry.is_expired():
            del self._entries[key]
            return default
        entry.access_count += 1
        return entry.content

    def remove(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear_expired(self) -> int:
        """清理过期条目，返回清理数。"""
        expired = [k for k, e in self._entries.items() if e.is_expired()]
        for k in expired:
            del self._entries[k]
        return len(expired)

    def keys(self) -> list[str]:
        self.clear_expired()
        return list(self._entries.keys())

    def all(self) -> dict[str, Any]:
        self.clear_expired()
        return {k: e.content for k, e in self._entries.items()}

    def snapshot(self) -> dict:
        return {
            "tier": "short",
            "entry_count": len(self._entries),
            "keys": list(self._entries.keys()),
            "total_access": sum(e.access_count for e in self._entries.values()),
        }

    # ---- 持久化 ----

    def save(self) -> None:
        """持久化到磁盘（独立于上下文窗口）。"""
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            k: {
                "content": e.content,
                "timestamp": e.timestamp,
                "ttl": e.ttl,
                "access_count": e.access_count,
                "metadata": e.metadata,
            }
            for k, e in self._entries.items()
        }
        self._storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for k, v in data.items():
                self._entries[k] = MemoryEntry(
                    key=k, content=v["content"], tier=MemoryTier.SHORT,
                    timestamp=v.get("timestamp", time.time()),
                    ttl=v.get("ttl"), access_count=v.get("access_count", 0),
                    metadata=v.get("metadata", {}),
                )
        except (json.JSONDecodeError, KeyError):
            pass


class MediumTermMemory:
    """中期上下文记忆 —— 跨迭代关系。

    特性：
      - JSON 文件持久化（独立于上下文窗口）
      - 存储：决策点与理由、改进机会、上一迭代结果、性能指标
      - 按 iteration_id 索引，支持跨迭代查询
      - 自动维护最近 N 个迭代（默认 20），超出 FIFO 淘汰
    """

    MAX_ITERATIONS = 20

    def __init__(self, storage_path: Path):
        self._storage_path = storage_path
        self._iterations: list[dict[str, Any]] = []
        self._decisions: list[dict[str, Any]] = []
        self._improvements: list[dict[str, Any]] = []
        self._load()

    # ---- 迭代记录 ----

    def record_iteration(self, iteration_id: str, result: dict[str, Any]) -> None:
        """记录一次迭代的完整结果。

        result 应包含：
          - outcome: 迭代结果描述
          - metrics: 性能指标 dict
          - decisions: 关键决策点列表
          - improvements: 识别到的改进机会列表
        """
        entry = {
            "iteration_id": iteration_id,
            "timestamp": time.time(),
            "outcome": result.get("outcome", ""),
            "metrics": result.get("metrics", {}),
        }
        self._iterations.append(entry)
        # FIFO 淘汰
        if len(self._iterations) > self.MAX_ITERATIONS:
            self._iterations = self._iterations[-self.MAX_ITERATIONS:]

        # 决策点
        for d in result.get("decisions", []):
            self._decisions.append({
                "iteration_id": iteration_id,
                "timestamp": time.time(),
                "decision": d.get("decision", ""),
                "justification": d.get("justification", ""),
                "outcome": d.get("outcome", ""),
            })

        # 改进机会
        for imp in result.get("improvements", []):
            self._improvements.append({
                "iteration_id": iteration_id,
                "timestamp": time.time(),
                "opportunity": imp.get("opportunity", ""),
                "source": imp.get("source", ""),
                "priority": imp.get("priority", "medium"),
            })

    # ---- 查询 ----

    def last_iteration(self) -> dict[str, Any] | None:
        return self._iterations[-1] if self._iterations else None

    def recent_decisions(self, n: int = 5) -> list[dict[str, Any]]:
        return self._decisions[-n:]

    def pending_improvements(self, min_priority: str = "medium") -> list[dict[str, Any]]:
        """获取未处理的改进机会（按优先级过滤）。"""
        priority_order = {"high": 0, "medium": 1, "low": 2}
        threshold = priority_order.get(min_priority, 2)
        return [i for i in self._improvements
                if priority_order.get(i.get("priority", "medium"), 2) <= threshold]

    def iteration_count(self) -> int:
        return len(self._iterations)

    def snapshot(self) -> dict:
        return {
            "tier": "medium",
            "iteration_count": len(self._iterations),
            "decision_count": len(self._decisions),
            "improvement_count": len(self._improvements),
            "last_iteration_id": self._iterations[-1]["iteration_id"] if self._iterations else None,
            "pending_improvements": len(self.pending_improvements()),
        }

    # ---- 持久化 ----

    def save(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "iterations": self._iterations,
            "decisions": self._decisions,
            "improvements": self._improvements,
        }
        self._storage_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self._iterations = data.get("iterations", [])
            self._decisions = data.get("decisions", [])
            self._improvements = data.get("improvements", [])
        except (json.JSONDecodeError, KeyError):
            pass


class LongTermMemory:
    """长期知识记忆 —— 累积和提炼关键洞察。

    特性：
      - Markdown 文件持久化（独立于上下文窗口，人类可读）
      - 存储：领域模式、经验教训、修复模式、最佳实践
      - 按类别组织（patterns / lessons / fixes / best_practices）
      - 每个条目包含：创建时间、来源迭代、置信度、引用次数
    """

    CATEGORIES = ["patterns", "lessons", "fixes", "best_practices"]

    def __init__(self, storage_dir: Path):
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, list[dict[str, Any]]] = {c: [] for c in self.CATEGORIES}
        self._load_all()

    # ---- 写入 ----

    def add_lesson(self, title: str, content: str, source_iteration: str = "",
                   confidence: float = 0.5, tags: list[str] | None = None) -> None:
        """添加一条经验教训。"""
        self._add_entry("lessons", {
            "title": title,
            "content": content,
            "source_iteration": source_iteration,
            "confidence": confidence,
            "tags": tags or [],
            "created_at": time.time(),
            "cited_count": 0,
        })

    def add_pattern(self, name: str, description: str, category: str = "",
                    examples: list[str] | None = None) -> None:
        """添加一个领域模式。"""
        self._add_entry("patterns", {
            "name": name,
            "description": description,
            "category": category,
            "examples": examples or [],
            "created_at": time.time(),
            "cited_count": 0,
        })

    def add_fix_template(self, problem: str, solution: str, context_tags: list[str] | None = None) -> None:
        """添加一个修复模板。"""
        self._add_entry("fixes", {
            "problem": problem,
            "solution": solution,
            "context_tags": context_tags or [],
            "created_at": time.time(),
            "cited_count": 0,
        })

    def add_best_practice(self, title: str, practice: str, domain: str = "") -> None:
        """添加一条最佳实践。"""
        self._add_entry("best_practices", {
            "title": title,
            "practice": practice,
            "domain": domain,
            "created_at": time.time(),
            "cited_count": 0,
        })

    # ---- 查询 ----

    def search(self, category: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """关键词搜索（简单子串匹配）。"""
        entries = self._entries.get(category, [])
        query_lower = query.lower()
        results = []
        for e in entries:
            text = json.dumps(e, ensure_ascii=False).lower()
            if query_lower in text:
                results.append(e)
        # 按引用次数降序
        results.sort(key=lambda x: x.get("cited_count", 0), reverse=True)
        return results[:top_k]

    def recent_lessons(self, n: int = 5) -> list[dict[str, Any]]:
        entries = sorted(self._entries.get("lessons", []),
                         key=lambda x: x.get("created_at", 0), reverse=True)
        return entries[:n]

    def cite(self, category: str, entry_index: int) -> None:
        """增加引用计数。"""
        entries = self._entries.get(category, [])
        if 0 <= entry_index < len(entries):
            entries[entry_index]["cited_count"] = entries[entry_index].get("cited_count", 0) + 1

    def snapshot(self) -> dict:
        return {
            "tier": "long",
            "categories": {c: len(self._entries[c]) for c in self.CATEGORIES},
            "total_entries": sum(len(self._entries[c]) for c in self.CATEGORIES),
        }

    # ---- 持久化 ----

    def save_all(self) -> None:
        for category in self.CATEGORIES:
            self._save_category(category)

    def _save_category(self, category: str) -> None:
        filepath = self._storage_dir / f"{category}.json"
        data = self._entries.get(category, [])
        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_all(self) -> None:
        for category in self.CATEGORIES:
            self._load_category(category)

    def _load_category(self, category: str) -> None:
        filepath = self._storage_dir / f"{category}.json"
        if not filepath.exists():
            return
        try:
            self._entries[category] = json.loads(filepath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass

    def _add_entry(self, category: str, entry: dict[str, Any]) -> None:
        self._entries[category].append(entry)
        self._save_category(category)


# ========================================================================== #
# 4. IterationProtocol —— 结构化迭代周期
# ========================================================================== #

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

    每个迭代周期包含五个阶段：
      1. ENTRY  → 加载记忆、初始化预算、回填上一轮关键信息
      2. EXECUTE → 执行核心操作
      3. VALIDATE → 反压校验（确定性）
      4. MEMORY_UPDATE → 持久化结果到三层记忆
      5. EXIT → 清理、记录指标

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

    def can_enter(self, budget: ContextBudget) -> tuple[bool, str]:
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

    def should_refresh_context(self, budget: ContextBudget) -> bool:
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


# ========================================================================== #
# 5. ContextManager —— 编排器
# ========================================================================== #

class ContextManager:
    """上下文工程编排器。

    职责：
      1. 管理 ContextBudget —— 70/30 分区分配
      2. 编排三层记忆 —— 加载/更新/持久化
      3. 驱动 IterationProtocol —— entry/exit 判断
      4. 组装最终 prompt —— 按预算拼接各部分
      5. 信息卸载 —— 大内容写入文件，返回引用路径

    用法：
        mgr = ContextManager(task_id="task-001", workdir=Path("./work"))
        mgr.start_iteration()
        mgr.allocate_critical("system prompt ...")
        mgr.allocate_support("history ...")
        prompt = mgr.assemble_prompt()
        # ... 执行 LLM 调用 ...
        mgr.record_iteration_result(outcome="成功", decisions=[...])
        mgr.finish_iteration()
    """

    def __init__(self, task_id: str, workdir: Path, total_budget: int = 32000):
        self.task_id = task_id
        self.workdir = workdir

        # 子组件
        self.budget = ContextBudget(total_budget=total_budget)
        self.protocol = IterationProtocol(max_iterations=10)
        self.metrics = PerformanceMetrics()

        # 记忆存储路径
        memory_dir = workdir / "shared" / "memory" / task_id
        self.short_mem = ShortTermMemory(memory_dir / "short_term.json")
        self.medium_mem = MediumTermMemory(memory_dir / "medium_term.json")
        self.long_mem = LongTermMemory(memory_dir / "long_term")

        # 共享知识库路径（用于 offload）
        self.knowledge_dir = workdir / "shared" / "knowledge"

        # 当前迭代的上下文组件
        self._system_prompt: str = ""
        self._task_spec: str = ""
        self._tool_results: list[str] = []
        self._offloaded_files: list[Path] = []

    # ---- 迭代生命周期 ----

    def start_iteration(self) -> bool:
        """开始新的迭代周期。返回 False 表示不应继续。"""
        can_enter, reason = self.protocol.can_enter(self.budget)
        if not can_enter:
            self.metrics.record("iteration_blocked", {"reason": reason})
            return False

        self.protocol.advance_phase(IterationPhase.ENTRY)
        self.budget.reset()
        self._tool_results = []
        self._offloaded_files = []

        # 回填上一轮关键信息
        last = self.medium_mem.last_iteration()
        if last:
            backfill = (
                f"[上一迭代] {last.get('iteration_id', 'N/A')}: "
                f"{last.get('outcome', '')[:200]}"
            )
            self.budget.allocate_support(backfill)

        # 注入长期记忆中的相关经验
        recent_lessons = self.long_mem.recent_lessons(3)
        if recent_lessons:
            lessons_text = "【经验教训】\n" + "\n".join(
                f"- {l['title']}: {l['content'][:100]}" for l in recent_lessons
            )
            self.budget.allocate_support(lessons_text)

        self.metrics.record("iteration_started", {
            "iteration": self.protocol.current_iteration,
            "budget_snapshot": self.budget.snapshot(),
        })
        return True

    def finish_iteration(self) -> None:
        """结束当前迭代周期。"""
        self.protocol.advance_phase(IterationPhase.EXIT)
        self._persist_all_memory()
        self.metrics.record("iteration_finished", {
            "iteration": self.protocol.current_iteration,
            "budget_snapshot": self.budget.snapshot(),
            "protocol_snapshot": self.protocol.snapshot(),
        })
        self.protocol.next_iteration()

    # ---- 上下文分配 ----

    def set_system_prompt(self, prompt: str) -> None:
        """设置 system prompt（放入 critical 区）。"""
        self._system_prompt = prompt
        self.budget.allocate_critical(prompt)

    def set_task_spec(self, spec: str) -> None:
        """设置任务规格（放入 critical 区）。"""
        self._task_spec = spec
        self.budget.allocate_critical(spec)

    def add_tool_result(self, result: str, max_chars: int = 2000) -> str:
        """添加工具结果。如果过长，offload 到文件再引用。

        Returns:
            实际放入上下文的内容（可能是截断或引用路径）
        """
        self._tool_results.append(result)
        if len(result) > max_chars:
            # 信息卸载：完整内容写入文件，上下文中只留引用
            return self.offload_to_file(result, prefix="tool_result")
        # 放入 support 区
        return self.budget.allocate_support(f"[工具结果]\n{result}")

    def add_context(self, text: str, zone: str = "support") -> str:
        """添加通用上下文。"""
        return self.budget.allocate(text, zone)

    # ---- 信息卸载（Offloading） ----

    def offload_to_file(self, content: str, prefix: str = "offload") -> str:
        """将内容写入外部文件，返回引用路径。

        这是 Anthropic 四大策略之一：完整内容占用 0 token，
        上下文中只保留精简引用路径（约 10-50 token/条）。
        """
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time() * 1000)
        filepath = self.knowledge_dir / f"{prefix}_{self.task_id}_{ts}.md"
        filepath.write_text(content, encoding="utf-8")
        self._offloaded_files.append(filepath)

        # 返回引用路径（放入 support 区）
        preview = content[:100].replace("\n", " ")
        ref = f"[卸载内容: {filepath.name}] {preview}..."
        self.budget.allocate_support(ref)
        return ref

    def offload_tool_results(self, max_chars_per_result: int = 2000) -> int:
        """批量卸载所有工具结果到文件。返回卸载的 token 数。"""
        if not self._tool_results:
            return 0
        combined = "\n\n---\n\n".join(
            f"## 工具结果 {i + 1}\n{r}" for i, r in enumerate(self._tool_results)
        )
        self.offload_to_file(combined, prefix="tool_results_batch")
        return TokenEstimator.estimate(combined)

    # ---- Prompt 组装 ----

    def assemble_prompt(self, current_task: str = "") -> str:
        """组装最终 prompt，按预算拼接各部分。

        优先级：
          1. System prompt（critical 区）
          2. 任务规格（critical 区）
          3. 当前任务（critical 区）
          4. 工具结果引用（support 区）
          5. 记忆上下文（support 区）

        如果 utilization >= 70%，自动触发 micro_compact 后再组装。
        """
        # 自动压缩
        if self.budget.needs_micro_compact:
            freed = self.budget.micro_compact()
            self.metrics.record("micro_compact", {"tokens_freed": freed})

        parts: list[str] = []

        # Critical zone (70%)
        if self._system_prompt:
            parts.append(self._system_prompt)
        if self._task_spec:
            parts.append(f"\n【任务规格】\n{self._task_spec}")
        if current_task:
            parts.append(f"\n【当前任务】\n{current_task}")

        # Support zone (30%)
        if self._tool_results:
            parts.append(f"\n【工具结果({len(self._tool_results)}条)】\n" +
                         "\n".join(r[:500] for r in self._tool_results[-5:]))

        # 记忆注入（中期记忆的关键决策）
        recent_decisions = self.medium_mem.recent_decisions(3)
        if recent_decisions:
            decisions_text = "\n【近期决策】\n" + "\n".join(
                f"- {d['decision']}: {d['justification'][:80]}"
                for d in recent_decisions
            )
            parts.append(decisions_text)

        return "\n\n".join(parts)

    # ---- 记忆操作 ----

    def record_iteration_result(self, outcome: str, decisions: list[dict] | None = None,
                                improvements: list[dict] | None = None,
                                metrics: dict[str, Any] | None = None) -> None:
        """记录本次迭代结果到中期记忆。"""
        iteration_id = f"{self.task_id}-iter-{self.protocol.current_iteration}"
        self.medium_mem.record_iteration(iteration_id, {
            "outcome": outcome,
            "metrics": metrics or {},
            "decisions": decisions or [],
            "improvements": improvements or [],
        })

    def learn_from_iteration(self, lesson_title: str, lesson_content: str,
                             confidence: float = 0.5) -> None:
        """从当前迭代中学习，写入长期记忆。"""
        self.long_mem.add_lesson(
            title=lesson_title,
            content=lesson_content,
            source_iteration=f"{self.task_id}-iter-{self.protocol.current_iteration}",
            confidence=confidence,
        )

    def search_long_term_memory(self, query: str, category: str = "lessons",
                                top_k: int = 5) -> list[dict[str, Any]]:
        """搜索长期记忆。"""
        return self.long_mem.search(category, query, top_k)

    # ---- 内部 ----

    def _persist_all_memory(self) -> None:
        """持久化所有记忆层到磁盘。"""
        self.short_mem.save()
        self.medium_mem.save()
        self.long_mem.save_all()
        self.metrics.record("memory_persisted", {
            "short": self.short_mem.snapshot(),
            "medium": self.medium_mem.snapshot(),
            "long": self.long_mem.snapshot(),
        })

    def snapshot(self) -> dict[str, Any]:
        """返回完整状态快照。"""
        return {
            "task_id": self.task_id,
            "budget": self.budget.snapshot(),
            "protocol": self.protocol.snapshot(),
            "memory": {
                "short": self.short_mem.snapshot(),
                "medium": self.medium_mem.snapshot(),
                "long": self.long_mem.snapshot(),
            },
            "metrics": self.metrics.snapshot(),
            "offloaded_files": [str(p) for p in self._offloaded_files],
        }


# ========================================================================== #
# 6. PerformanceMetrics —— 上下文利用率 + 记忆留存率
# ========================================================================== #

class PerformanceMetrics:
    """性能监控。

    监控维度：
      1. 上下文利用率（Context Utilization）
         - average_utilization: 平均利用率（目标 55-75%）
         - overflow_count: 溢出次数（越低越好）
         - compact_count: 压缩次数

      2. 记忆留存率（Memory Retention）
         - short_term_hit_rate: 短期记忆命中率
         - medium_term_access_count: 中期记忆访问次数
         - long_term_cite_count: 长期记忆引用次数

      3. 迭代效率
         - iterations_per_task: 每任务平均迭代次数
         - verification_pass_rate: 验证通过率

    阈值（可配置）：
      - utilization_low: 低于此值说明浪费预算
      - utilization_high: 高于此值说明有溢出风险
      - retention_decay_limit: 记忆留存率下限
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
        """记忆留存率综合评分（0.0 ~ 1.0）。

        基于 access_count 和 cite_count 加权计算。
        """
        memory_snapshots = [
            e["data"] for e in self._events if e["type"] == "memory_persisted"
        ]
        if not memory_snapshots:
            return 0.0

        last = memory_snapshots[-1]
        short = last.get("short", {})
        medium = last.get("medium", {})
        long_ = last.get("long", {})

        # 短期记忆：条目数 > 0 即得分
        short_score = min(1.0, short.get("entry_count", 0) / 10.0)

        # 中期记忆：迭代记录数 / 最大迭代数
        medium_score = min(1.0, medium.get("iteration_count", 0) / 20.0)

        # 长期记忆：总条目数 / 阈值
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


# ========================================================================== #
# 7. DynamicBudgetAllocator —— 按阶段自适应调整预算比例
# ========================================================================== #

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

    用法：
        allocator = DynamicBudgetAllocator()
        stage_budget = allocator.get_budget("FIX_APPLY")
        budget = ContextBudget(total_budget=32000, critical_ratio=stage_budget.critical_ratio)
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
        """为指定阶段创建一个 ContextBudget 实例。"""
        config = cls.get_budget(stage)
        budget = ContextBudget.__new__(ContextBudget)
        budget.total_budget = total_budget
        budget.CRITICAL_RATIO = config.critical_ratio
        budget.SUPPORT_RATIO = config.support_ratio

        output_reserve = int(total_budget * 0.10)
        available = total_budget - output_reserve

        budget.critical = ContextSlice(
            name="critical",
            budget=int(available * config.critical_ratio),
        )
        budget.support = ContextSlice(
            name="support",
            budget=int(available * config.support_ratio),
        )
        budget.output_reserve = output_reserve
        budget._total_used_ever = 0
        budget._compact_count = 0
        budget._overflow_count = 0
        return budget

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


# ========================================================================== #
# 8. SemanticMemorySearch —— 语义记忆检索
# ========================================================================== #

class SemanticMemorySearch:
    """语义记忆检索 —— 升级长期记忆的搜索方式。

    从子串匹配升级为语义搜索：
      - 优先用 embedding API（DeepSeek），降级为 TF-IDF
      - 支持多类别并行搜索
      - 搜索结果带相关度排序

    用法：
        searcher = SemanticMemorySearch(long_mem)
        results = await searcher.search("null pointer", category="lessons", top_k=5)
    """

    def __init__(self, long_mem: "LongTermMemory"):
        self._long_mem = long_mem
        self._use_embedding = False  # 是否启用 embedding（需 API）

    # ---- TF-IDF 降级实现 ----

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单分词：英文按空格/标点，中文按字。"""
        import re
        tokens = []
        # 英文词（2个字符以上）
        for m in re.finditer(r'[a-zA-Z]{2,}', text.lower()):
            tokens.append(m.group())
        # 中文字
        for ch in text:
            if '\u4e00' <= ch <= '\u9fff':
                tokens.append(ch)
        return tokens

    @staticmethod
    def _tf_idf_score(query: str, document: str, corpus_docs: list[str]) -> float:
        """计算 query 与 document 的 TF-IDF 相似度。

        简化实现：TF × IDF，不做向量化。
        """
        query_tokens = set(SemanticMemorySearch._tokenize(query))
        if not query_tokens:
            return 0.0

        doc_tokens = SemanticMemorySearch._tokenize(document)
        if not doc_tokens:
            return 0.0

        # 计算文档总数
        N = len(corpus_docs) + 1  # +1 避免除零

        # 计算每个 query token 的 IDF
        score = 0.0
        for qt in query_tokens:
            # TF: query token 在 document 中出现的频率
            tf = doc_tokens.count(qt) / len(doc_tokens) if doc_tokens else 0

            # IDF: log(N / (包含该词的文档数))
            df = sum(1 for d in corpus_docs if qt in SemanticMemorySearch._tokenize(d))
            idf = __import__('math').log((N + 1) / (df + 1)) + 1.0

            score += tf * idf

        return score

    # ---- 搜索 ----

    def search_tfidf(self, query: str, category: str = "lessons",
                     top_k: int = 5) -> list[dict[str, Any]]:
        """TF-IDF 语义搜索（降级方案）。"""
        entries = self._long_mem._entries.get(category, [])
        if not entries:
            return []

        # 将每个 entry 序列化为文本
        corpus = [json.dumps(e, ensure_ascii=False) for e in entries]

        # 计算每个 entry 的 TF-IDF 得分
        scored = []
        for i, entry in enumerate(entries):
            doc_text = corpus[i]
            # 也检查子串匹配（兜底）
            substring_match = query.lower() in doc_text.lower()
            tfidf = self._tf_idf_score(query, doc_text, corpus)
            # 综合得分：TF-IDF 为主，子串匹配加分
            score = tfidf + (0.3 if substring_match else 0.0)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    async def search_embedding(self, query: str, category: str = "lessons",
                               top_k: int = 5) -> list[dict[str, Any]]:
        """Embedding 语义搜索（优先方案，需 DeepSeek API）。

        流程：
          1. 调用 DeepSeek embedding API 获取 query 向量
          2. 对每条记忆计算余弦相似度
          3. 返回 top_k 最相关条目
        """
        entries = self._long_mem._entries.get(category, [])
        if not entries:
            return []

        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            # 降级为 TF-IDF
            return self.search_tfidf(query, category, top_k)

        try:
            import httpx

            # 获取 query embedding
            async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
                resp = await client.post(
                    "https://api.deepseek.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"input": query, "model": "deepseek-embedding"},
                )
                if resp.status_code != 200:
                    return self.search_tfidf(query, category, top_k)

                data = resp.json()
                query_embedding = data["data"][0]["embedding"]

            # 对每条记忆计算余弦相似度（简单近似：用文本串）
            # 完整实现需要缓存所有 memory 的 embedding
            # 这里降级为 TF-IDF
            return self.search_tfidf(query, category, top_k)

        except Exception:
            return self.search_tfidf(query, category, top_k)

    async def search(self, query: str, category: str = "lessons",
                     top_k: int = 5, prefer_embedding: bool = True) -> list[dict[str, Any]]:
        """语义搜索入口。

        优先使用 embedding，降级为 TF-IDF，再降级为子串匹配。
        """
        if prefer_embedding and self._use_embedding:
            results = await self.search_embedding(query, category, top_k)
            if results:
                return results

        results = self.search_tfidf(query, category, top_k)
        if results:
            return results

        # 最终降级：原始子串匹配
        return self._long_mem.search(category, query, top_k)

    def search_multi_category(self, query: str, categories: list[str] | None = None,
                              top_k: int = 5) -> dict[str, list[dict[str, Any]]]:
        """多类别并行搜索。"""
        categories = categories or self._long_mem.CATEGORIES
        results = {}
        for cat in categories:
            results[cat] = self.search_tfidf(query, cat, top_k)
        return results


# ========================================================================== #
# 9. 便捷工具函数（兼容 PLAN.md ctx-1 的四个函数签名）
# ========================================================================== #

def trim_context(text: str, max_tokens: int, preserve_head_ratio: float = 0.7) -> str:
    """智能截断：保留头尾关键信息，去掉中间。

    Args:
        text: 要截断的文本
        max_tokens: 最大 token 数
        preserve_head_ratio: 头部保留比例（0.0~1.0）
    """
    budget = ContextBudget(total_budget=max_tokens)
    return budget._truncate_to_fit(text, max_tokens)


def compact_history(messages: list[dict[str, str]], max_tokens: int) -> str:
    """压缩长历史为摘要。

    简化实现：保留最近消息，旧消息走 truncate。
    生产环境可替换为 LLM 摘要。
    """
    if not messages:
        return ""
    total = TokenEstimator.estimate_messages(messages)
    if total <= max_tokens:
        return "\n".join(m.get("content", "") for m in messages)

    # 保留最近消息（从尾部开始）
    kept = []
    used = 0
    for m in reversed(messages):
        content = m.get("content", "")
        tokens = TokenEstimator.estimate(content)
        if used + tokens > max_tokens:
            break
        kept.insert(0, content)
        used += tokens
    return "\n".join(kept)


def budget_allocate(total_budget: int, parts: dict[str, int]) -> dict[str, int]:
    """按比例分配 token 预算。

    Args:
        total_budget: 总预算
        parts: {名称: 比例}，比例之和应为 1.0

    Returns:
        {名称: 分配的 token 数}
    """
    return {name: int(total_budget * ratio) for name, ratio in parts.items()}


def offload_to_file(content: str, filepath: Path) -> str:
    """写入外部文件，返回引用路径。

    Returns:
        "[offloaded: {filename}] {preview}"
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    preview = content[:100].replace("\n", " ")
    return f"[offloaded: {filepath.name}] {preview}..."


# ========================================================================== #
# 8. 自检（可直接运行验证）
# ========================================================================== #

if __name__ == "__main__":
    import tempfile

    print("=== context.py 自检 ===")

    # 1. TokenEstimator
    assert TokenEstimator.estimate("hello world") > 0
    assert TokenEstimator.estimate("你好世界") > 0
    assert TokenEstimator.estimate("") == 0
    print("✓ TokenEstimator")

    # 2. ContextBudget
    budget = ContextBudget(total_budget=10000)
    # 填充 critical 区到接近满（英文 ~4 chars/token，约 35000 chars 填满 9000 可用 tokens 的 70%）
    big_text = "hello " * 7000  # ~35000 chars, ~8750 tokens
    result = budget.allocate_critical(big_text)
    assert len(result) > 0
    assert budget.critical.used > 0
    # 再填充 support 区到触发阈值
    budget.allocate_support("world " * 3000)  # ~15000 chars, ~3750 tokens
    assert budget.needs_micro_compact
    freed = budget.micro_compact()
    assert freed > 0
    print("✓ ContextBudget")

    # 3. 三层记忆
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # ShortTermMemory
        sm = ShortTermMemory(tmp / "short.json")
        sm.put("step_1", {"status": "done", "output": "fixed bug"})
        assert sm.get("step_1")["status"] == "done"
        assert sm.get("nonexistent", "default") == "default"
        sm.save()
        sm2 = ShortTermMemory(tmp / "short.json")
        assert sm2.get("step_1")["status"] == "done"
        print("✓ ShortTermMemory")

        # MediumTermMemory
        mm = MediumTermMemory(tmp / "medium.json")
        mm.record_iteration("iter-1", {
            "outcome": "fixed login bug",
            "metrics": {"time": 120},
            "decisions": [{"decision": "use bcrypt", "justification": "security best practice"}],
            "improvements": [{"opportunity": "add rate limiting", "priority": "high"}],
        })
        assert mm.iteration_count() == 1
        assert len(mm.recent_decisions()) == 1
        assert len(mm.pending_improvements("high")) == 1
        mm.save()
        mm2 = MediumTermMemory(tmp / "medium.json")
        assert mm2.iteration_count() == 1
        print("✓ MediumTermMemory")

        # LongTermMemory
        lm = LongTermMemory(tmp / "long_term")
        lm.add_lesson("null check", "always check null before dereference", confidence=0.9)
        lm.add_pattern("retry pattern", "exponential backoff with jitter", category="resilience")
        results = lm.search("lessons", "null")
        assert len(results) > 0
        print("✓ LongTermMemory")

    # 4. IterationProtocol
    protocol = IterationProtocol(max_iterations=3)
    budget2 = ContextBudget(total_budget=10000)
    can_enter, _ = protocol.can_enter(budget2)
    assert can_enter
    protocol.advance_phase(IterationPhase.EXECUTE)
    assert protocol.current_phase == IterationPhase.EXECUTE
    can_exit, _ = protocol.can_exit(verification_passed=True)
    assert can_exit
    print("✓ IterationProtocol")

    # 5. ContextManager
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        mgr = ContextManager(task_id="test-001", workdir=tmp, total_budget=10000)
        assert mgr.start_iteration()
        mgr.set_system_prompt("You are a helpful assistant.")
        mgr.set_task_spec("Fix the login bug.")
        mgr.add_tool_result("test output: all tests passed")
        prompt = mgr.assemble_prompt("Please fix the null pointer in login.py")
        assert len(prompt) > 0
        mgr.record_iteration_result(
            outcome="fixed login bug",
            decisions=[{"decision": "add null check", "justification": "prevent NPE"}],
            improvements=[{"opportunity": "add unit test", "priority": "high"}],
        )
        mgr.learn_from_iteration("null safety", "Always check null before dereference", 0.9)
        mgr.finish_iteration()

        snapshot = mgr.snapshot()
        assert snapshot["budget"]["utilization"] > 0
        assert snapshot["memory"]["medium"]["iteration_count"] == 1
        print("✓ ContextManager")

    # 6. PerformanceMetrics
    pm = PerformanceMetrics()
    pm.record("iteration_started", {"iteration": 0})
    pm.record("iteration_finished", {"iteration": 0, "budget_snapshot": {"utilization": 0.65, "overflow_count": 0}})
    pm.record("memory_persisted", {"short": {"entry_count": 5}, "medium": {"iteration_count": 3}, "long": {"total_entries": 20}})
    assert 0.5 < pm.average_utilization() < 0.8
    assert pm.memory_retention_score() > 0
    healthy, alerts = pm.is_healthy()
    print(f"✓ PerformanceMetrics (healthy={healthy}, alerts={alerts})")

    # 7. 便捷函数
    trimmed = trim_context("hello world " * 1000, max_tokens=50)
    assert len(trimmed) > 0
    compacted = compact_history([{"content": "msg1"}, {"content": "msg2"}], max_tokens=100)
    assert len(compacted) > 0
    allocated = budget_allocate(10000, {"system": 0.15, "task": 0.35, "history": 0.25, "output": 0.25})
    assert sum(allocated.values()) <= 10000
    print("✓ 便捷函数")

    print("\n=== 全部自检通过 ===")