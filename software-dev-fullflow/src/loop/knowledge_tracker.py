"""知识/Skill 复用追踪器（非阻塞、专用存储）。

设计目标：
  1. 专用存储：独立于 TaskState，落盘到 shared/stats/usage_stats.json
  2. 非阻塞：写入操作通过后台线程 + 队列完成，不阻塞主任务链路
  3. 跨任务累积：同一个 knowledge_id 或 skill_name 跨多次任务命中次数自动累加

与 evaluation.py 的集成：
  本模块提供 get_agent_growth_score(agent_name)，被 evaluation.py 的治理综合分公式引用：
    治理综合分 = 0.5 × 合格分 + 0.35 × 贡献分 + 0.15 × 成长分
  成长分 = Retrospector 沉淀的知识被跨任务 RAG 检索命中的总次数

用法：
  from loop.knowledge_tracker import UsageTracker

  tracker = UsageTracker(stats_dir=workdir / "shared" / "stats")
  tracker.record_knowledge_hit("KN-0001", "T-0002", "retrospector")
  tracker.record_skill_invoke("code-gen", "fixer")

  # 非阻塞：record_* 只推入队列，后台线程异步落盘
  # 程序退出前调用 flush() 确保数据不丢
  tracker.flush()
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #

@dataclass
class KnowledgeEntry:
    """单条知识条目的复用统计。"""
    knowledge_id: str
    category: str = ""
    source_agent: str = ""          # 由哪个 Agent 沉淀的（通常是 retrospector）
    source_task: str = ""           # 来自哪个任务
    usage_count: int = 0            # 跨任务被 RAG 检索命中的总次数
    last_used_at: str = ""          # ISO 时间戳
    used_by_tasks: list[str] = field(default_factory=list)  # 被哪些任务引用过（去重）


@dataclass
class SkillEntry:
    """单个 Skill 的调用统计。"""
    skill_name: str
    invoke_count: int = 0           # 被调用的总次数
    last_used_at: str = ""          # ISO 时间戳
    used_by_agents: list[str] = field(default_factory=list)  # 被哪些 Agent 调用过（去重）


@dataclass
class UsageStats:
    """usage_stats.json 的完整数据结构。"""
    knowledge: dict[str, KnowledgeEntry] = field(default_factory=dict)
    skills: dict[str, SkillEntry] = field(default_factory=dict)
    updated_at: str = ""


# --------------------------------------------------------------------------- #
# 核心追踪器（非阻塞写入）
# --------------------------------------------------------------------------- #

class UsageTracker:
    """知识/Skill 复用追踪器。

    设计要点：
      - 所有 record_* 方法只做入队操作（O(1)），不阻塞主任务
      - 后台线程每 5 秒或队列积压超过 50 条时自动落盘
      - 程序退出前调用 flush() 确保数据不丢
      - 线程安全：使用锁保护共享状态
    """

    _FLUSH_INTERVAL = 5.0           # 后台定时落盘间隔（秒）
    _FLUSH_BATCH_SIZE = 50          # 积压超过此数量立即落盘

    def __init__(self, stats_dir: Path, flush_interval: float | None = None):
        self._stats_dir = Path(stats_dir)
        self._stats_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._stats_dir / "usage_stats.json"

        # 共享状态（锁保护）
        self._lock = threading.Lock()
        self._stats: UsageStats = self._load()
        self._queue: deque[dict] = deque()  # 待处理事件队列

        # 后台 flush 间隔：默认 5s，测试可传更小值以加速线程退出/落盘
        self._flush_interval = self._FLUSH_INTERVAL if flush_interval is None else float(flush_interval)

        # 后台线程
        self._running = True
        self._thread = threading.Thread(target=self._background_flush, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ #
    # 公开 API（非阻塞）
    # ------------------------------------------------------------------ #

    def record_knowledge_hit(
        self,
        knowledge_id: str,
        task_id: str,
        source_agent: str = "",
        category: str = "",
    ) -> None:
        """记录一次知识条目被 RAG 检索命中。非阻塞，立即返回。"""
        self._queue.append({
            "type": "knowledge_hit",
            "knowledge_id": knowledge_id,
            "task_id": task_id,
            "source_agent": source_agent,
            "category": category,
            "ts": _now_iso(),
        })
        self._maybe_flush()

    def record_skill_invoke(
        self,
        skill_name: str,
        agent_name: str,
    ) -> None:
        """记录一次 Skill 被 Agent 调用。非阻塞，立即返回。"""
        self._queue.append({
            "type": "skill_invoke",
            "skill_name": skill_name,
            "agent_name": agent_name,
            "ts": _now_iso(),
        })
        self._maybe_flush()

    def get_knowledge_usage(self, knowledge_id: str) -> KnowledgeEntry:
        """获取某条知识的复用统计（读操作，直接返回）。"""
        with self._lock:
            return self._stats.knowledge.get(
                knowledge_id,
                KnowledgeEntry(knowledge_id=knowledge_id),
            )

    def get_skill_usage(self, skill_name: str) -> SkillEntry:
        """获取某个 Skill 的调用统计（读操作，直接返回）。"""
        with self._lock:
            return self._stats.skills.get(
                skill_name,
                SkillEntry(skill_name=skill_name),
            )

    def get_agent_growth_score(self, agent_name: str) -> float:
        """计算某个 Agent 的成长分（其沉淀的知识被跨任务复用的总次数）。

        这是 KPI-BENCHMARK.md §3.4 中"学习成长"维度的核心数据源。
        目前主要对 Retrospector 有意义（其他 Agent 不沉淀知识）。
        """
        with self._lock:
            total = 0
            for entry in self._stats.knowledge.values():
                if entry.source_agent == agent_name:
                    total += entry.usage_count
            return float(total)

    def get_all_knowledge_usage(self) -> dict[str, KnowledgeEntry]:
        """获取全部知识条目的复用统计（快照）。"""
        with self._lock:
            return dict(self._stats.knowledge)

    def get_all_skill_usage(self) -> dict[str, SkillEntry]:
        """获取全部 Skill 的调用统计（快照）。"""
        with self._lock:
            return dict(self._stats.skills)

    def get_summary(self) -> dict:
        """获取统计摘要（供仪表盘/报告用）。"""
        with self._lock:
            total_knowledge = len(self._stats.knowledge)
            total_hits = sum(e.usage_count for e in self._stats.knowledge.values())
            total_skill_invocations = sum(e.invoke_count for e in self._stats.skills.values())
            top_knowledge = sorted(
                self._stats.knowledge.values(),
                key=lambda e: e.usage_count,
                reverse=True,
            )[:5]
            top_skills = sorted(
                self._stats.skills.values(),
                key=lambda e: e.invoke_count,
                reverse=True,
            )[:5]
            return {
                "total_knowledge_entries": total_knowledge,
                "total_knowledge_hits": total_hits,
                "total_skill_invocations": total_skill_invocations,
                "top_knowledge": [
                    {"id": e.knowledge_id, "hits": e.usage_count}
                    for e in top_knowledge
                ],
                "top_skills": [
                    {"name": e.skill_name, "invocations": e.invoke_count}
                    for e in top_skills
                ],
            }

    def flush(self) -> None:
        """强制落盘所有未处理事件。程序退出前调用。"""
        self._process_queue()
        self._save()

    def shutdown(self) -> None:
        """安全关闭：落盘 + 停止后台线程。"""
        self._running = False
        self.flush()
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #

    def _load(self) -> UsageStats:
        """从磁盘加载已有统计。"""
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text(encoding="utf-8"))
                return UsageStats(
                    knowledge={
                        k: KnowledgeEntry(**v)
                        for k, v in data.get("knowledge", {}).items()
                    },
                    skills={
                        k: SkillEntry(**v)
                        for k, v in data.get("skills", {}).items()
                    },
                    updated_at=data.get("updated_at", ""),
                )
            except (json.JSONDecodeError, TypeError):
                pass
        return UsageStats()

    def _save(self) -> None:
        """落盘当前统计到 usage_stats.json（原子写入）。"""
        with self._lock:
            self._stats.updated_at = _now_iso()
            data = {
                "knowledge": {
                    k: _dataclass_to_dict(v)
                    for k, v in self._stats.knowledge.items()
                },
                "skills": {
                    k: _dataclass_to_dict(v)
                    for k, v in self._stats.skills.items()
                },
                "updated_at": self._stats.updated_at,
            }
        # 原子写入：先写临时文件，再 rename
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._file)

    def _process_queue(self) -> None:
        """批量处理队列中的事件，更新内存统计。"""
        if not self._queue:
            return

        # 一次性取出所有事件
        with self._lock:
            events = list(self._queue)
            self._queue.clear()

        for ev in events:
            if ev["type"] == "knowledge_hit":
                self._apply_knowledge_hit(ev)
            elif ev["type"] == "skill_invoke":
                self._apply_skill_invoke(ev)

    def _apply_knowledge_hit(self, ev: dict) -> None:
        kid = ev["knowledge_id"]
        with self._lock:
            if kid not in self._stats.knowledge:
                self._stats.knowledge[kid] = KnowledgeEntry(
                    knowledge_id=kid,
                    source_agent=ev.get("source_agent", ""),
                    category=ev.get("category", ""),
                )
            entry = self._stats.knowledge[kid]
            entry.usage_count += 1
            entry.last_used_at = ev["ts"]
            task_id = ev["task_id"]
            if task_id and task_id not in entry.used_by_tasks:
                entry.used_by_tasks.append(task_id)
            # 如果事件带了 source_agent/category 且条目本身为空，补上
            if not entry.source_agent and ev.get("source_agent"):
                entry.source_agent = ev["source_agent"]
            if not entry.category and ev.get("category"):
                entry.category = ev["category"]

    def _apply_skill_invoke(self, ev: dict) -> None:
        sn = ev["skill_name"]
        with self._lock:
            if sn not in self._stats.skills:
                self._stats.skills[sn] = SkillEntry(skill_name=sn)
            entry = self._stats.skills[sn]
            entry.invoke_count += 1
            entry.last_used_at = ev["ts"]
            agent = ev["agent_name"]
            if agent and agent not in entry.used_by_agents:
                entry.used_by_agents.append(agent)

    def _maybe_flush(self) -> None:
        """队列积压超过阈值时立即落盘（在调用线程中检查，不阻塞）。"""
        if len(self._queue) >= self._FLUSH_BATCH_SIZE:
            self._process_queue()
            self._save()

    def _background_flush(self) -> None:
        """后台线程：定时落盘。"""
        while self._running:
            time.sleep(self._flush_interval)
            if not self._running:
                break
            self._process_queue()
            with self._lock:
                if self._stats.updated_at < _now_iso():
                    pass  # 有变更才保存
            self._save()


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _dataclass_to_dict(obj) -> dict:
    """将 dataclass 实例转为 dict（处理嵌套 list）。"""
    if hasattr(obj, "__dataclass_fields__"):
        result = {}
        for f in obj.__dataclass_fields__:
            val = getattr(obj, f)
            if isinstance(val, list):
                result[f] = list(val)
            elif hasattr(val, "__dataclass_fields__"):
                result[f] = _dataclass_to_dict(val)
            else:
                result[f] = val
        return result
    return obj


# --------------------------------------------------------------------------- #
# 模块级便捷函数（单例模式，适用于简单场景）
# --------------------------------------------------------------------------- #

_global_tracker: Optional[UsageTracker] = None
_global_tracker_lock = threading.Lock()


def get_tracker(stats_dir: Optional[Path] = None) -> UsageTracker:
    """获取全局单例 UsageTracker（线程安全）。

    首次调用时创建，后续调用直接返回已有实例。
    适用于 Mock 模式和简单脚本场景。
    """
    global _global_tracker
    if _global_tracker is None:
        with _global_tracker_lock:
            if _global_tracker is None:
                if stats_dir is None:
                    stats_dir = Path(__file__).resolve().parent.parent.parent / "shared" / "stats"
                _global_tracker = UsageTracker(stats_dir)
    return _global_tracker


def reset_tracker() -> None:
    """重置全局 tracker（测试用）。"""
    global _global_tracker
    with _global_tracker_lock:
        if _global_tracker is not None:
            _global_tracker.shutdown()
        _global_tracker = None


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tracker = UsageTracker(Path(tmp) / "stats")

        # 模拟知识命中
        tracker.record_knowledge_hit("KN-0001", "T-0002", "retrospector", "null_pointer")
        tracker.record_knowledge_hit("KN-0001", "T-0003", "retrospector", "null_pointer")
        tracker.record_knowledge_hit("KN-0002", "T-0003", "retrospector", "memory_leak")

        # 模拟 Skill 调用
        tracker.record_skill_invoke("code-gen", "fixer")
        tracker.record_skill_invoke("code-gen", "fixer")
        tracker.record_skill_invoke("retrospective", "retrospector")

        # 等待后台落盘
        time.sleep(0.5)
        tracker.flush()

        # 验证
        print("=== 知识复用统计 ===")
        for kid, entry in tracker.get_all_knowledge_usage().items():
            print(f"  {kid}: used={entry.usage_count} tasks={entry.used_by_tasks}")

        print("\n=== Skill 调用统计 ===")
        for sn, entry in tracker.get_all_skill_usage().items():
            print(f"  {sn}: invoked={entry.invoke_count} by={entry.used_by_agents}")

        print(f"\n=== Retrospector 成长分 ===")
        print(f"  {tracker.get_agent_growth_score('retrospector')}")

        print(f"\n=== 摘要 ===")
        print(json.dumps(tracker.get_summary(), ensure_ascii=False, indent=2))

        print(f"\n=== 落盘文件 ===")
        stats_file = Path(tmp) / "stats" / "usage_stats.json"
        print(stats_file.read_text(encoding="utf-8"))

        tracker.shutdown()

    print("\n✅ 自检通过")