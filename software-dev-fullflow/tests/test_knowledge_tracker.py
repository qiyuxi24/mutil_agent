"""A2 · 知识/Skill 复用追踪器（UsageTracker）单元测试。

覆盖「知识使用频率统计」作为独立记忆组件的关键契约：
  - 知识命中计数累计 + 跨任务去重
  - Skill 调用计数累计 + 跨 Agent 去重
  - get_agent_growth_score 成长分汇总（对齐 KPI-BENCHMARK §3.4）
  - get_summary Top 榜排序
  - 落盘 → 重载恢复（幂等）
  - 损坏 JSON 容错回退
  - flush / shutdown 不丢数据
  - 后台线程正确关闭（无悬挂线程）
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from loop.knowledge_tracker import (
    UsageTracker,
    get_tracker,
    reset_tracker,
)


@pytest.fixture
def tracker(tmp_path: Path):
    """创建一个隔离的 UsageTracker，禁用后台线程并结束自动清理。

    测试通过显式 flush() 同步落盘验证核心逻辑，不依赖 5s 后台 flush 间隔，
    避免拖慢测试（后台线程关闭后实例即无后台开销）。
    """
    t = UsageTracker(tmp_path / "stats", flush_interval=0.01)
    yield t
    t.shutdown()


def _stats_file(tmp_path: Path) -> Path:
    return tmp_path / "stats" / "usage_stats.json"


def _quiet_tracker(stats_dir: Path) -> UsageTracker:
    """创建快速 flush 的 UsageTracker（后台线程 10ms 间隔，shutdown 秒退）。"""
    return UsageTracker(stats_dir, flush_interval=0.01)


# --------------------------------------------------------------------------- #
# 知识命中
# --------------------------------------------------------------------------- #

class TestKnowledgeHits:
    def test_record_and_query(self, tracker: UsageTracker):
        """记录一次知识命中后，usage_count 应为 1，且能查询到。"""
        tracker.record_knowledge_hit("KN-0001", "T-0002", "retrospector", "null_pointer")
        tracker.flush()
        entry = tracker.get_knowledge_usage("KN-0001")
        assert entry.usage_count == 1
        assert entry.source_agent == "retrospector"
        assert entry.category == "null_pointer"

    def test_count_accumulates_across_hits(self, tracker: UsageTracker):
        """同一条知识多次命中，usage_count 累加。"""
        tracker.record_knowledge_hit("KN-0001", "T-0002", "retrospector")
        tracker.record_knowledge_hit("KN-0001", "T-0003", "retrospector")
        tracker.record_knowledge_hit("KN-0001", "T-0004", "retrospector")
        tracker.flush()
        assert tracker.get_knowledge_usage("KN-0001").usage_count == 3

    def test_used_by_tasks_deduplicated(self, tracker: UsageTracker):
        """同一任务多次命中，used_by_tasks 只记录一次。"""
        tracker.record_knowledge_hit("KN-0001", "T-0002", "retrospector")
        tracker.record_knowledge_hit("KN-0001", "T-0002", "retrospector")
        tracker.record_knowledge_hit("KN-0001", "T-0003", "retrospector")
        tracker.flush()
        entry = tracker.get_knowledge_usage("KN-0001")
        assert set(entry.used_by_tasks) == {"T-0002", "T-0003"}

    def test_missing_knowledge_returns_empty_entry(self, tracker: UsageTracker):
        """查询不存在的知识返回默认空条目，不抛异常。"""
        entry = tracker.get_knowledge_usage("KN-9999")
        assert entry.usage_count == 0
        assert entry.knowledge_id == "KN-9999"

    def test_last_used_at_updated(self, tracker: UsageTracker):
        """命中后 last_used_at 被写入非空时间戳。"""
        tracker.record_knowledge_hit("KN-0001", "T-0002")
        tracker.flush()
        assert tracker.get_knowledge_usage("KN-0001").last_used_at != ""


# --------------------------------------------------------------------------- #
# Skill 调用
# --------------------------------------------------------------------------- #

class TestSkillInvocations:
    def test_record_and_query(self, tracker: UsageTracker):
        """记录一次 Skill 调用后，invoke_count 应为 1。"""
        tracker.record_skill_invoke("code-gen", "fixer")
        tracker.flush()
        entry = tracker.get_skill_usage("code-gen")
        assert entry.invoke_count == 1
        assert entry.used_by_agents == ["fixer"]

    def test_count_accumulates_and_agents_dedup(self, tracker: UsageTracker):
        """Skill 多次调用累加；同 Agent 多次调用去重记录。"""
        tracker.record_skill_invoke("code-gen", "fixer")
        tracker.record_skill_invoke("code-gen", "fixer")
        tracker.record_skill_invoke("code-gen", "tester")
        tracker.flush()
        entry = tracker.get_skill_usage("code-gen")
        assert entry.invoke_count == 3
        assert set(entry.used_by_agents) == {"fixer", "tester"}

    def test_missing_skill_returns_empty_entry(self, tracker: UsageTracker):
        """查询不存在的 Skill 返回默认空条目。"""
        entry = tracker.get_skill_usage("no-such-skill")
        assert entry.invoke_count == 0


# --------------------------------------------------------------------------- #
# 成长分（对齐 KPI-BENCHMARK §3.4）
# --------------------------------------------------------------------------- #

class TestGrowthScore:
    def test_growth_score_sums_only_matching_agent(self, tracker: UsageTracker):
        """成长分 = 该 Agent 沉淀的知识被跨任务命中的总次数。"""
        tracker.record_knowledge_hit("KN-0001", "T-0002", "retrospector")
        tracker.record_knowledge_hit("KN-0001", "T-0003", "retrospector")
        tracker.record_knowledge_hit("KN-0002", "T-0003", "retrospector")
        tracker.record_knowledge_hit("KN-0003", "T-0004", "rootcause")  # 别的 Agent
        tracker.flush()
        assert tracker.get_agent_growth_score("retrospector") == 3.0
        assert tracker.get_agent_growth_score("rootcause") == 1.0

    def test_growth_score_zero_when_no_knowledge(self, tracker: UsageTracker):
        """无任何知识命中的 Agent，成长分为 0。"""
        assert tracker.get_agent_growth_score("nobody") == 0.0


# --------------------------------------------------------------------------- #
# 摘要
# --------------------------------------------------------------------------- #

class TestSummary:
    def test_summary_top_knowledge_sorted(self, tracker: UsageTracker):
        """get_summary 的 top_knowledge 按 usage_count 降序。"""
        tracker.record_knowledge_hit("KN-001", "T-1")
        tracker.record_knowledge_hit("KN-001", "T-2")
        tracker.record_knowledge_hit("KN-002", "T-1")
        tracker.flush()
        summary = tracker.get_summary()
        assert summary["total_knowledge_entries"] == 2
        assert summary["total_knowledge_hits"] == 3
        hits = [e["hits"] for e in summary["top_knowledge"]]
        assert hits == sorted(hits, reverse=True)

    def test_summary_top_skills_sorted(self, tracker: UsageTracker):
        """get_summary 的 top_skills 按 invoke_count 降序。"""
        tracker.record_skill_invoke("skill-a", "fixer")
        tracker.record_skill_invoke("skill-a", "fixer")
        tracker.record_skill_invoke("skill-b", "tester")
        tracker.flush()
        summary = tracker.get_summary()
        assert summary["total_skill_invocations"] == 3
        inv = [e["invocations"] for e in summary["top_skills"]]
        assert inv == sorted(inv, reverse=True)


# --------------------------------------------------------------------------- #
# 持久化
# --------------------------------------------------------------------------- #

class TestPersistence:
    def test_save_and_reload_is_idempotent(self, tmp_path: Path):
        """flush 落盘后，新实例重载应恢复相同统计（幂等）。"""
        t1 = _quiet_tracker(tmp_path / "stats")
        t1.record_knowledge_hit("KN-0001", "T-0002", "retrospector", "null_pointer")
        t1.record_skill_invoke("code-gen", "fixer")
        t1.flush()
        t1.shutdown()

        t2 = _quiet_tracker(tmp_path / "stats")
        try:
            assert t2.get_knowledge_usage("KN-0001").usage_count == 1
            assert t2.get_skill_usage("code-gen").invoke_count == 1
            assert t2.get_agent_growth_score("retrospector") == 1.0
        finally:
            t2.shutdown()

    def test_flush_writes_valid_json(self, tmp_path: Path):
        """落盘文件应是合法 JSON，且含 knowledge / skills / updated_at。"""
        t = _quiet_tracker(tmp_path / "stats")
        t.record_knowledge_hit("KN-0001", "T-1")
        t.flush()
        t.shutdown()
        data = json.loads(_stats_file(tmp_path).read_text(encoding="utf-8"))
        assert "knowledge" in data
        assert "skills" in data
        assert "updated_at" in data
        assert "KN-0001" in data["knowledge"]

    def test_corrupted_json_falls_back_to_empty(self, tmp_path: Path):
        """损坏的 usage_stats.json 应回退为空统计，不抛异常。"""
        stats_dir = tmp_path / "stats"
        stats_dir.mkdir(parents=True, exist_ok=True)
        (_stats_file(tmp_path)).write_text("{invalid json!!", encoding="utf-8")
        t = _quiet_tracker(stats_dir)
        try:
            assert t.get_all_knowledge_usage() == {}
        finally:
            t.shutdown()

    def test_missing_file_starts_empty(self, tmp_path: Path):
        """无历史文件时从空统计开始，正常可用。"""
        t = _quiet_tracker(tmp_path / "stats")
        try:
            assert t.get_all_knowledge_usage() == {}
            assert t.get_all_skill_usage() == {}
        finally:
            t.shutdown()


# --------------------------------------------------------------------------- #
# flush / shutdown / 线程
# --------------------------------------------------------------------------- #

class TestLifecycle:
    def test_flush_processes_queued_events(self, tracker: UsageTracker):
        """flush() 立即处理队列中所有事件并落盘。"""
        for i in range(5):
            tracker.record_knowledge_hit(f"KN-{i:04d}", "T-1")
        tracker.flush()
        assert len(tracker.get_all_knowledge_usage()) == 5

    def test_shutdown_keeps_data(self, tmp_path: Path):
        """shutdown() 后数据仍保留在磁盘，可重新加载。"""
        t = _quiet_tracker(tmp_path / "stats")
        t.record_knowledge_hit("KN-0001", "T-1")
        t.shutdown()
        t2 = _quiet_tracker(tmp_path / "stats")
        try:
            assert t2.get_knowledge_usage("KN-0001").usage_count == 1
        finally:
            t2.shutdown()

    def test_background_thread_terminates(self, tmp_path: Path):
        """shutdown() 后后台线程应退出（daemon + join），不悬挂。"""
        t = UsageTracker(tmp_path / "stats", flush_interval=0.01)
        thread = t._thread
        assert thread.is_alive()
        t.shutdown()
        thread.join(timeout=3.0)
        assert not thread.is_alive()


# --------------------------------------------------------------------------- #
# 全局单例
# --------------------------------------------------------------------------- #

class TestGlobalTracker:
    def test_get_tracker_returns_singleton(self, tmp_path: Path):
        """get_tracker 首次创建，后续返回同一实例。"""
        reset_tracker()
        try:
            a = get_tracker(tmp_path / "stats")
            b = get_tracker(tmp_path / "stats")
            assert a is b
        finally:
            reset_tracker()

    def test_reset_tracker_clears_singleton(self, tmp_path: Path):
        """reset_tracker 后再次 get_tracker 返回新实例。"""
        reset_tracker()
        try:
            a = get_tracker(tmp_path / "stats")
            reset_tracker()
            b = get_tracker(tmp_path / "stats")
            assert a is not b
        finally:
            reset_tracker()
