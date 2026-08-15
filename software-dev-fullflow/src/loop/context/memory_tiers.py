"""三层记忆 —— 独立于上下文窗口的持久化存储。

- ShortTermMemory  → 当前迭代操作记忆（dict + JSON，TTL 5 分钟）
- MediumTermMemory → 跨迭代关系记忆（决策点、改进机会）
- LongTermMemory   → 累积知识记忆（领域模式、经验教训）
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


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

    常驻内存（dict）+ JSON 持久化备份，默认 TTL 5 分钟。
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

    JSON 文件持久化，按 iteration_id 索引，FIFO 淘汰最近 N 个迭代（默认 20）。
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
        """记录一次迭代的完整结果。"""
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

    Markdown/JSON 文件持久化（人类可读），按类别组织。
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

    def entries(self, category: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """公开访问入口，供语义检索等模块使用（替代私有 _entries 访问）。"""
        if category is None:
            return self._entries
        return {category: self._entries.get(category, [])}
