"""A1 · 通用可复用记忆系统 —— AgentMemoryRegistry 单测。

覆盖「可复用记忆」作为统一框架的关键契约：
  - 按 agent_name 懒创建 / 复用 AgentMemory
  - 统一读写 / 检索 / 沉淀（consolidate_all / snapshot_all）
  - 各 Agent 记忆隔离，互不覆盖
"""
from __future__ import annotations

from pathlib import Path

from loop.context import AgentMemoryEntry, AgentMemoryRegistry


def _make_registry(tmp_path: Path, names: list[str] | None = None) -> AgentMemoryRegistry:
    return AgentMemoryRegistry(storage_dir=tmp_path, agent_names=names)


class TestAgentMemoryRegistry:
    def test_lazy_get_creates_and_caches(self, tmp_path: Path):
        """get() 懒创建并缓存同一 AgentMemory 实例。"""
        reg = _make_registry(tmp_path)
        m1 = reg.get("fixer")
        m2 = reg.get("fixer")
        assert m1 is m2
        assert reg.has("fixer")
        assert not reg.has("tester")

    def test_pre_registered_names(self, tmp_path: Path):
        """传入 agent_names 时预创建。"""
        reg = _make_registry(tmp_path, names=["fixer", "tester"])
        assert reg.names() == ["fixer", "tester"]

    def test_names_returns_sorted(self, tmp_path: Path):
        """names() 返回排序后的名单。"""
        reg = _make_registry(tmp_path, names=["tester", "fixer", "aggregator"])
        assert reg.names() == ["aggregator", "fixer", "tester"]

    def test_all_returns_all_memories(self, tmp_path: Path):
        """all() 返回 {name: AgentMemory} 全量。"""
        reg = _make_registry(tmp_path, names=["fixer", "tester"])
        all_mems = reg.all()
        assert set(all_mems.keys()) == {"fixer", "tester"}
        assert all_mems["fixer"] is reg.get("fixer")

    def test_record_and_recall(self, tmp_path: Path):
        """record 写入后 recall 能检索到。"""
        reg = _make_registry(tmp_path, names=["fixer"])
        reg.record("fixer", AgentMemoryEntry(
            task_id="T-1", phase="fix", outcome="success",
            patterns=["拆解根因后一次修复成功"],
        ))
        results = reg.recall("fixer", "根因")
        assert results, "应检索到历史经验"
        assert results[0]["source"] == "iteration"

    def test_memory_isolation_between_agents(self, tmp_path: Path):
        """各 Agent 记忆隔离：A 的记录不影响 B。"""
        reg = _make_registry(tmp_path, names=["fixer", "tester"])
        reg.record("fixer", AgentMemoryEntry(task_id="T-1", phase="fix", outcome="success"))
        assert reg.get("fixer").snapshot()["iteration_count"] == 1
        assert reg.get("tester").snapshot()["iteration_count"] == 0

    def test_consolidate_all(self, tmp_path: Path):
        """consolidate_all 沉淀各 Agent 长期记忆。"""
        reg = _make_registry(tmp_path, names=["fixer"])
        # 写入重复错误模式触发沉淀
        for i in range(3):
            reg.record("fixer", AgentMemoryEntry(
                task_id=f"T-{i}", phase="fix", outcome="fail",
                mistakes=["空指针"], fixes=["判空"],
            ))
        results = reg.consolidate_all()
        assert "fixer" in results
        assert results["fixer"] > 0
        # 长期记忆已写入
        assert reg.get("fixer").snapshot()["long_term_entries"] > 0

    def test_snapshot_all(self, tmp_path: Path):
        """snapshot_all 返回所有 Agent 快照。"""
        reg = _make_registry(tmp_path, names=["fixer", "tester"])
        snap = reg.snapshot_all()
        assert set(snap.keys()) == {"fixer", "tester"}
        assert "agent_name" in snap["fixer"]

    def test_memory_dir_layout(self, tmp_path: Path):
        """记忆目录按 shared/agents/<name>/memory 布局。"""
        reg = _make_registry(tmp_path, names=["fixer"])
        mem = reg.get("fixer")
        assert mem.memory_dir == tmp_path / "agents" / "fixer" / "memory"
        assert mem.memory_dir.exists()

    def test_to_dict_summary(self, tmp_path: Path):
        """to_dict 返回注册表摘要。"""
        reg = _make_registry(tmp_path, names=["fixer", "tester"])
        summary = reg.to_dict()
        assert summary["agent_count"] == 2
        assert set(summary["agents"].keys()) == {"fixer", "tester"}
