"""上下文工程编排器 —— ContextManager。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .budget import ContextBudget
from .memory_tiers import (
    LongTermMemory,
    MediumTermMemory,
    ShortTermMemory,
)
from .metrics import PerformanceMetrics
from .protocol import IterationPhase, IterationProtocol


class ContextManager:
    """上下文工程编排器。

    职责：
      1. 管理 ContextBudget —— critical/support 分区分配
      2. 编排三层记忆 —— 加载/更新/持久化
      3. 驱动 IterationProtocol —— entry/exit 判断
      4. 组装最终 prompt —— 按预算拼接各部分
      5. 信息卸载 —— 大内容写入文件，返回引用路径
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

        完整内容占用 0 token，上下文中只保留精简引用路径。
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
        from .estimator import TokenEstimator
        return TokenEstimator.estimate(combined)

    # ---- Prompt 组装 ----

    def assemble_prompt(self, current_task: str = "") -> str:
        """组装最终 prompt，按预算拼接各部分。"""
        # 自动压缩
        if self.budget.needs_micro_compact:
            freed = self.budget.micro_compact()
            self.metrics.record("micro_compact", {"tokens_freed": freed})

        parts: list[str] = []

        # Critical zone
        if self._system_prompt:
            parts.append(self._system_prompt)
        if self._task_spec:
            parts.append(f"\n【任务规格】\n{self._task_spec}")
        if current_task:
            parts.append(f"\n【当前任务】\n{current_task}")

        # Support zone
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
