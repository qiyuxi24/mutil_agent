"""iteration_log.py 停滞检测单元测试。

覆盖：
- note 有 findings（>0）时 stale_count 归零
- 连续 0 findings：2 次 → structural，4 次 → human
- 中间插入一次 >0 后 stale 重置
- new_findings < 0 抛 ValueError
- show 回读全部记录
- run_id 非法（../、含 /、空）抛 ValueError
- pivot_for 边界（0/1→none，2/3→structural，≥4→human）
- append-only：不覆盖历史行
"""

import json
from pathlib import Path

import pytest

from loop.iteration_log import (
    ESCALATE_HUMAN_AT,
    PIVOT_STRUCTURAL_AT,
    note,
    pivot_for,
    show,
)


class TestIterationLog:
    def test_note_with_findings_resets_stale(self, tmp_path: Path):
        """有 findings（>0）时 stale_count 归零。"""
        note(str(tmp_path), "run-1", "research", 3)
        r = note(str(tmp_path), "run-1", "research", 2)
        assert r == {"stale_count": 0, "pivot": "none"}

    def test_consecutive_zero_findings_escalates(self, tmp_path: Path):
        """连续 0 findings：2 次 → structural，4 次 → human。"""
        r1 = note(str(tmp_path), "run-1", "research", 0)
        assert r1 == {"stale_count": 1, "pivot": "none"}
        r2 = note(str(tmp_path), "run-1", "research", 0)
        assert r2["stale_count"] == 2
        assert r2["pivot"] == "structural"
        r3 = note(str(tmp_path), "run-1", "research", 0)
        assert r3["pivot"] == "structural"
        r4 = note(str(tmp_path), "run-1", "research", 0)
        assert r4["stale_count"] == 4
        assert r4["pivot"] == "human"

    def test_mid_finding_resets_stale(self, tmp_path: Path):
        """中间插入一次 >0 后 stale 重置。"""
        note(str(tmp_path), "run-1", "research", 0)
        note(str(tmp_path), "run-1", "research", 0)
        note(str(tmp_path), "run-1", "research", 1)   # 重置
        r = note(str(tmp_path), "run-1", "research", 0)
        assert r == {"stale_count": 1, "pivot": "none"}

    def test_negative_findings_raise(self, tmp_path: Path):
        with pytest.raises(ValueError):
            note(str(tmp_path), "run-1", "research", -1)

    def test_show_reads_back_all_records(self, tmp_path: Path):
        note(str(tmp_path), "run-1", "research", 2, direction="try B")
        note(str(tmp_path), "run-1", "research", 0)
        text = show(str(tmp_path), "run-1")
        lines = [json.loads(l) for l in text.splitlines() if l.strip()]
        assert len(lines) == 2
        assert lines[0]["new_findings"] == 2
        assert lines[0]["direction"] == "try B"
        assert lines[1]["stale_count"] == 1
        assert lines[1]["pivot"] == "none"

    @pytest.mark.parametrize("bad", ["../evil", "a/b", ""])
    def test_invalid_run_id_raises(self, tmp_path: Path, bad: str):
        with pytest.raises(ValueError):
            note(str(tmp_path), bad, "research", 1)

    def test_pivot_for_boundaries(self):
        assert pivot_for(0) == "none"
        assert pivot_for(1) == "none"
        assert pivot_for(2) == "structural"
        assert pivot_for(3) == "structural"
        assert pivot_for(4) == "human"
        assert pivot_for(10) == "human"
        # 与模块常量一致（防止阈值被误改）
        assert PIVOT_STRUCTURAL_AT == 2
        assert ESCALATE_HUMAN_AT == 4

    def test_append_only_never_overwrites(self, tmp_path: Path):
        """append-only：不覆盖历史行。"""
        for f in (2, 0, 0, 0, 0):
            note(str(tmp_path), "run-1", "research", f)
        raw = show(str(tmp_path), "run-1")
        assert raw.count("\n") == 5  # 5 条记录，无覆盖
        staleness = [json.loads(l)["stale_count"] for l in raw.splitlines() if l.strip()]
        assert staleness == [0, 1, 2, 3, 4]

    def test_run_id_allows_safe_chars(self, tmp_path: Path):
        note(str(tmp_path), "run_1.2-A", "research", 1)
        assert (tmp_path / "runs" / "run_1.2-A.iterations.jsonl").is_file()

    def test_direction_recorded_but_optional(self, tmp_path: Path):
        r = note(str(tmp_path), "run-1", "research", 1)
        assert "direction" not in json.loads(show(str(tmp_path), "run-1").strip())
        note(str(tmp_path), "run-1", "research", 1, direction="x")
        assert json.loads(show(str(tmp_path), "run-1").strip().splitlines()[-1])["direction"] == "x"
        assert r == {"stale_count": 0, "pivot": "none"}
