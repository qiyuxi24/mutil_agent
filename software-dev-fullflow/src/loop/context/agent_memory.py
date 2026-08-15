"""按 Agent 维度的独立记忆（跨任务持久化）。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AgentMemoryEntry:
    """Agent 记忆中的一条记录。"""

    timestamp: float = field(default_factory=time.time)
    task_id: str = ""
    iteration: int = 0
    phase: str = ""                     # 迭代阶段（root_cause / fix / test / release / retrospect）
    outcome: str = ""                   # 成功/失败/部分成功
    mistakes: list[str] = field(default_factory=list)      # 踩过的坑
    fixes: list[str] = field(default_factory=list)         # 修正方法
    patterns: list[str] = field(default_factory=list)      # 发现的模式
    metrics: dict[str, Any] = field(default_factory=dict)  # 性能指标
    retry_count: int = 0                # 重试次数
    notes: str = ""                     # 自由备注


class AgentMemory:
    """单个 Agent 的独立记忆系统（跨任务持久化）。

    每个 Agent 拥有独立的记忆空间：
      shared/agents/{agent_name}/memory/
        ├── YYYY-MM-DD.md          # 每日工作日志（人类可读）
        ├── MEMORY.md              # 长期记忆（稳定知识、模式、偏好）
        └── iterations.jsonl       # 迭代记录（结构化，供检索）
    """

    MAX_DAILY_ENTRIES = 50          # 每日日志最大条目数
    MAX_ITERATION_RECORDS = 200     # 迭代记录最大保留数
    MAX_LONG_TERM_ENTRIES = 30      # 长期记忆最大条目数

    def __init__(self, agent_name: str, storage_dir: Path):
        """
        Args:
            agent_name: Agent 名称（如 "fixer", "rootcause"）
            storage_dir: 共享存储根目录（如 workdir / "shared"）
        """
        self.agent_name = agent_name
        self.memory_dir = storage_dir / "agents" / agent_name / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # 迭代记录（JSONL 格式，便于追加和流式读取）
        self._iterations_path = self.memory_dir / "iterations.jsonl"
        self._iterations: list[AgentMemoryEntry] = []
        self._load_iterations()

        # 长期记忆（Markdown，人类可读）
        self._long_term_path = self.memory_dir / "MEMORY.md"
        self._long_term_entries: list[dict[str, Any]] = []
        self._load_long_term()

    # ---- 迭代记录 ----

    def record_iteration(self, entry: AgentMemoryEntry) -> None:
        """记录一次迭代结果。"""
        self._iterations.append(entry)
        # FIFO 淘汰
        if len(self._iterations) > self.MAX_ITERATION_RECORDS:
            self._iterations = self._iterations[-self.MAX_ITERATION_RECORDS:]
        # 追加写入 JSONL
        self._append_iteration_line(entry)
        # 写入每日日志
        self._write_daily_log(entry)

    def record_ralph_retry(self, task_id: str, iteration: int, phase: str,
                           mistake: str, fix: str) -> None:
        """记录 Ralph 自我迭代中的一次重试（踩坑+修正）。

        合并到最近的同任务同阶段记录，避免 JSONL 重复行。
        """
        # 合并到最近的同任务同阶段记录
        for existing in reversed(self._iterations):
            if existing.task_id == task_id and existing.phase == phase:
                existing.mistakes.append(mistake)
                existing.fixes.append(fix)
                existing.retry_count += 1
                # 重写整个 JSONL 文件（避免追加重复行导致 reload 时重复计数）
                self._rewrite_iterations()
                self._write_daily_log(existing)
                return
        # 没有找到则新建一条记录
        entry = AgentMemoryEntry(
            task_id=task_id,
            iteration=iteration,
            phase=phase,
            outcome="retry",
            mistakes=[mistake],
            fixes=[fix],
            retry_count=1,
        )
        self.record_iteration(entry)

    # ---- 长期记忆沉淀 ----

    def consolidate_to_long_term(self) -> int:
        """将近期迭代记录提炼为长期记忆条目。

        自动分析最近迭代中的模式，写入 MEMORY.md。
        返回新增的长期记忆条目数。
        """
        if not self._iterations:
            return 0

        recent = self._iterations[-20:]  # 分析最近 20 条
        new_entries = 0

        # 1. 提取高频错误模式
        mistake_counts: dict[str, int] = {}
        for e in recent:
            for m in e.mistakes:
                mistake_counts[m] = mistake_counts.get(m, 0) + 1
        for mistake, count in mistake_counts.items():
            if count >= 2 and not self._has_long_term_entry("mistake", mistake):
                fixes = []
                for e in recent:
                    for i, m in enumerate(e.mistakes):
                        if m == mistake and i < len(e.fixes):
                            fixes.append(e.fixes[i])
                self._add_long_term_entry({
                    "type": "mistake_pattern",
                    "title": f"常见错误: {mistake[:80]}",
                    "content": mistake,
                    "fixes": list(set(fixes))[:3],
                    "frequency": count,
                    "last_seen": recent[-1].timestamp,
                })
                new_entries += 1

        # 2. 提取成功模式
        success_entries = [e for e in recent if e.outcome == "success"]
        for e in success_entries:
            for p in e.patterns:
                if not self._has_long_term_entry("pattern", p):
                    self._add_long_term_entry({
                        "type": "success_pattern",
                        "title": f"成功模式: {p[:80]}",
                        "content": p,
                        "source_task": e.task_id,
                        "last_seen": e.timestamp,
                    })
                    new_entries += 1

        if new_entries > 0:
            self._save_long_term()

        return new_entries

    # ---- 检索 ----

    def recall(self, query: str, phase: str = "", top_k: int = 5) -> list[dict[str, Any]]:
        """检索相关历史经验（关键词 + 子串匹配）。"""
        results: list[tuple[float, dict[str, Any]]] = []

        # 搜索迭代记录
        for e in self._iterations:
            if phase and e.phase != phase:
                continue
            score = 0.0
            text = json.dumps({
                "outcome": e.outcome,
                "mistakes": e.mistakes,
                "fixes": e.fixes,
                "patterns": e.patterns,
                "notes": e.notes,
            }, ensure_ascii=False).lower()
            query_lower = query.lower()
            if query_lower in text:
                score += 0.5
            # 关键词匹配加分
            for kw in query_lower.split():
                if kw in text:
                    score += 0.3
            if score > 0:
                results.append((score, {
                    "source": "iteration",
                    "task_id": e.task_id,
                    "phase": e.phase,
                    "outcome": e.outcome,
                    "mistakes": e.mistakes[:5],
                    "fixes": e.fixes[:5],
                    "patterns": e.patterns[:5],
                    "timestamp": e.timestamp,
                }))

        # 搜索长期记忆
        for entry in self._long_term_entries:
            text = json.dumps(entry, ensure_ascii=False).lower()
            query_lower = query.lower()
            if query_lower in text:
                results.append((0.4, {"source": "long_term", **entry}))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in results[:top_k]]

    def recent_mistakes(self, phase: str = "", n: int = 5) -> list[str]:
        """获取最近的错误（供 Ralph 迭代参考，避免重复踩坑）。"""
        mistakes = []
        for e in reversed(self._iterations):
            if phase and e.phase != phase:
                continue
            for m in e.mistakes:
                if m not in mistakes:
                    mistakes.append(m)
            if len(mistakes) >= n:
                break
        return mistakes[:n]

    def recent_fixes(self, phase: str = "", n: int = 5) -> list[str]:
        """获取最近的修正方法。"""
        fixes = []
        for e in reversed(self._iterations):
            if phase and e.phase != phase:
                continue
            for f in e.fixes:
                if f not in fixes:
                    fixes.append(f)
            if len(fixes) >= n:
                break
        return fixes[:n]

    # ---- 快照 ----

    def snapshot(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "iteration_count": len(self._iterations),
            "long_term_entries": len(self._long_term_entries),
            "recent_phases": list(set(e.phase for e in self._iterations[-10:])),
            "total_retries": sum(e.retry_count for e in self._iterations),
            "memory_dir": str(self.memory_dir),
        }

    # ---- 内部：迭代记录持久化（JSONL） ----

    def _append_iteration_line(self, entry: AgentMemoryEntry) -> None:
        """追加一行 JSON 到 iterations.jsonl。"""
        line = json.dumps({
            "timestamp": entry.timestamp,
            "task_id": entry.task_id,
            "iteration": entry.iteration,
            "phase": entry.phase,
            "outcome": entry.outcome,
            "mistakes": entry.mistakes,
            "fixes": entry.fixes,
            "patterns": entry.patterns,
            "metrics": entry.metrics,
            "retry_count": entry.retry_count,
            "notes": entry.notes,
        }, ensure_ascii=False)
        with open(self._iterations_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _rewrite_iterations(self) -> None:
        """重写整个 iterations.jsonl（用于合并已有记录后避免重复行）。"""
        lines = []
        for entry in self._iterations:
            lines.append(json.dumps({
                "timestamp": entry.timestamp,
                "task_id": entry.task_id,
                "iteration": entry.iteration,
                "phase": entry.phase,
                "outcome": entry.outcome,
                "mistakes": entry.mistakes,
                "fixes": entry.fixes,
                "patterns": entry.patterns,
                "metrics": entry.metrics,
                "retry_count": entry.retry_count,
                "notes": entry.notes,
            }, ensure_ascii=False))
        self._iterations_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _load_iterations(self) -> None:
        if not self._iterations_path.exists():
            return
        try:
            for line in self._iterations_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                data = json.loads(line)
                self._iterations.append(AgentMemoryEntry(
                    timestamp=data.get("timestamp", 0),
                    task_id=data.get("task_id", ""),
                    iteration=data.get("iteration", 0),
                    phase=data.get("phase", ""),
                    outcome=data.get("outcome", ""),
                    mistakes=data.get("mistakes", []),
                    fixes=data.get("fixes", []),
                    patterns=data.get("patterns", []),
                    metrics=data.get("metrics", {}),
                    retry_count=data.get("retry_count", 0),
                    notes=data.get("notes", ""),
                ))
        except (json.JSONDecodeError, KeyError):
            pass

    # ---- 内部：每日日志（Markdown） ----

    def _write_daily_log(self, entry: AgentMemoryEntry) -> None:
        """追加到每日工作日志。"""
        from datetime import datetime
        today = datetime.fromtimestamp(entry.timestamp).strftime("%Y-%m-%d")
        log_path = self.memory_dir / f"{today}.md"

        header = ""
        if not log_path.exists():
            header = f"# {self.agent_name} · 工作日志 · {today}\n\n"

        ts = datetime.fromtimestamp(entry.timestamp).strftime("%H:%M:%S")
        lines = [
            f"## [{ts}] 任务 {entry.task_id} · 迭代 {entry.iteration} · {entry.phase}",
            f"- 结果: {entry.outcome}",
            f"- 重试次数: {entry.retry_count}",
        ]
        if entry.mistakes:
            lines.append(f"- 踩坑: {', '.join(entry.mistakes[:5])}")
        if entry.fixes:
            lines.append(f"- 修正: {', '.join(entry.fixes[:5])}")
        if entry.patterns:
            lines.append(f"- 发现模式: {', '.join(entry.patterns[:5])}")
        if entry.notes:
            lines.append(f"- 备注: {entry.notes}")
        lines.append("")

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(header + "\n".join(lines) + "\n")

        # 限制每日条目数
        self._trim_daily_log(log_path)

    def _trim_daily_log(self, log_path: Path) -> None:
        """限制每日日志条目数，保留最近 N 条。"""
        content = log_path.read_text(encoding="utf-8")
        sections = content.split("\n## [")
        if len(sections) <= self.MAX_DAILY_ENTRIES + 1:  # +1 for header
            return
        # 保留 header + 最近 N 条
        kept = [sections[0]] + sections[-(self.MAX_DAILY_ENTRIES):]
        log_path.write_text("\n## [".join(kept), encoding="utf-8")

    # ---- 内部：长期记忆（Markdown + JSON） ----

    def _add_long_term_entry(self, entry: dict[str, Any]) -> None:
        entry["created_at"] = time.time()
        self._long_term_entries.append(entry)
        # FIFO 淘汰
        if len(self._long_term_entries) > self.MAX_LONG_TERM_ENTRIES:
            self._long_term_entries = self._long_term_entries[-self.MAX_LONG_TERM_ENTRIES:]

    def _has_long_term_entry(self, entry_type: str, content: str) -> bool:
        content_lower = content.lower()
        for e in self._long_term_entries:
            if e.get("type") == entry_type and content_lower in e.get("content", "").lower():
                return True
        return False

    def _save_long_term(self) -> None:
        """保存长期记忆到 MEMORY.md（人类可读）+ memory.json（结构化）。"""
        # Markdown 格式
        md_lines = [
            f"# {self.agent_name} · 长期记忆",
            f"",
            f"> 最后更新: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"> 总条目: {len(self._long_term_entries)}",
            f"",
        ]

        by_type: dict[str, list[dict]] = {}
        for e in self._long_term_entries:
            t = e.get("type", "other")
            by_type.setdefault(t, []).append(e)

        for t, entries in by_type.items():
            md_lines.append(f"## {t}")
            md_lines.append("")
            for e in entries:
                title = e.get("title", "无标题")
                md_lines.append(f"### {title}")
                if e.get("fixes"):
                    md_lines.append(f"- 修正方法: {', '.join(e['fixes'][:3])}")
                if e.get("frequency"):
                    md_lines.append(f"- 出现频率: {e['frequency']} 次")
                if e.get("source_task"):
                    md_lines.append(f"- 来源任务: {e['source_task']}")
                md_lines.append("")

        self._long_term_path.write_text("\n".join(md_lines), encoding="utf-8")

        # JSON 备份（供检索）
        json_path = self.memory_dir / "memory.json"
        json_path.write_text(
            json.dumps(self._long_term_entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_long_term(self) -> None:
        json_path = self.memory_dir / "memory.json"
        if not json_path.exists():
            return
        try:
            self._long_term_entries = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
