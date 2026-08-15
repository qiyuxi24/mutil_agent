"""验证 GAP-05/06/07 已实现的确定性逻辑（无需真实 AgentTeams 平台）。

覆盖：
  - GAP-05: TaskCheckpoint 里程碑去重（latest_milestone_set 保留打回历史）
  - GAP-06: task_id 唯一性契约（checkpoint 按 task_id 隔离、UUID hex 唯一）
  - GAP-07: 断点续传核心 —— TaskCheckpoint 序列化/反序列化 round-trip、
            elapsed 累计、status 恢复
  - 自适应轮询间隔 `_adaptive_poll_interval` 的分段策略

这些纯函数/数据类不依赖 Matrix/agt，可在无平台环境下确定性验证，
作为 GAP-05/06/07 已实现代码的回归锁。
"""

from __future__ import annotations

from pathlib import Path
import json
import uuid

from loop.agentteams_client import TaskCheckpoint, TaskInfo, AgentTeamsClient


# --------------------------------------------------------------------------- #
# GAP-06: task_id 唯一性契约
# --------------------------------------------------------------------------- #

def test_task_id_uuid_hex_uniqueness():
    """GAP-06: create_task 用 uuid4().hex[:12]，并发不冲突（唯一性契约）。"""
    ids = {uuid.uuid4().hex[:12] for _ in range(10000)}
    assert len(ids) == 10000, "UUID hex[:12] 在 1w 次内不应冲突"


def test_task_info_isolated_by_task_id():
    """TaskInfo 的 task_id 独立，不同任务不共享状态。"""
    a = TaskInfo(task_id="abc", spec="spec-a")
    b = TaskInfo(task_id="def", spec="spec-b")
    assert a.task_id != b.task_id
    assert a.bound_room_id == "" and b.bound_room_id == ""
    # 修改 a 不影响 b（dataclass 值类型隔离）
    a.bound_room_id = "!roomA"
    assert b.bound_room_id == ""


# --------------------------------------------------------------------------- #
# GAP-07: 断点续传 —— TaskCheckpoint 序列化 round-trip
# --------------------------------------------------------------------------- #

def _make_ms(milestone: str, worker: str, ts_ms: int) -> dict[str, str]:
    return {
        "milestone": milestone,
        "worker": worker,
        "content": f"{milestone} from {worker}",
        "ts_ms": str(ts_ms),
        "room_id": f"!room-{worker}",
    }


def test_checkpoint_round_trip(tmp_path: Path):
    """GAP-07: checkpoint 序列化/反序列化后字段完整不丢。"""
    cp = TaskCheckpoint(
        task_id="task-123",
        seen_milestones=[
            _make_ms("TASK_SPEC_READY", "aggregator", 1000),
            _make_ms("ROOT_CAUSE_FOUND", "rootcause", 2000),
        ],
        bound_room_id="!room-xyz",
        baseline_ts=500,
        last_poll_ts=123.45,
        elapsed=45.6,
        status="running",
    )
    # to_dict → json → from_dict
    d = json.loads(json.dumps(cp.to_dict()))
    restored = TaskCheckpoint.from_dict(d)

    assert restored.task_id == "task-123"
    assert restored.bound_room_id == "!room-xyz"
    assert restored.baseline_ts == 500
    assert restored.last_poll_ts == 123.45
    assert restored.elapsed == 45.6
    assert restored.status == "running"
    assert len(restored.seen_milestones) == 2
    assert restored.seen_milestones[0]["milestone"] == "TASK_SPEC_READY"
    assert restored.seen_milestones[1]["ts_ms"] == "2000"


def test_checkpoint_round_trip_empty_seen(tmp_path: Path):
    """空里程碑也能序列化/反序列化。"""
    cp = TaskCheckpoint(task_id="t", baseline_ts=0)
    restored = TaskCheckpoint.from_dict(cp.to_dict())
    assert restored.seen_milestones == []


def test_checkpoint_survives_partial_dict():
    """from_dict 对缺失字段宽容（兼容旧版 checkpoint 文件）。"""
    restored = TaskCheckpoint.from_dict({"task_id": "only-id"})
    assert restored.task_id == "only-id"
    assert restored.seen_milestones == []
    assert restored.status == "running"


# --------------------------------------------------------------------------- #
# GAP-05: latest_milestone_set 去重 + 保留打回历史
# --------------------------------------------------------------------------- #

def test_latest_milestone_set_dedup_keeps_backtrack_history():
    """GAP-05: latest_milestone_set 取每个里程碑最新一次，但 seen 保留全部历史（打回）。"""
    cp = TaskCheckpoint(
        task_id="task-rb",
        seen_milestones=[
            _make_ms("TEST_FAILED", "tester", 3000),       # 打回
            _make_ms("FIX_APPLIED", "fixer", 4000),        # 重新修复
            _make_ms("TEST_PASSED", "tester", 5000),       # 再通过
            _make_ms("TEST_PASSED", "tester", 5000),       # 同 key 重复（应去重显示）
        ],
    )
    latest = cp.latest_milestone_set()
    assert latest == {"TEST_FAILED", "FIX_APPLIED", "TEST_PASSED"}
    # seen_milestones 完整保留（打回历史可用于评价归因）
    assert len(cp.seen_milestones) == 4


def test_latest_milestone_set_completion_detection():
    """RETROSPECT_DONE 出现即判定闭环完成。"""
    cp = TaskCheckpoint(
        task_id="task-done",
        seen_milestones=[
            _make_ms("TASK_SPEC_READY", "aggregator", 1),
            _make_ms("RETROSPECT_DONE", "retrospector", 99),
        ],
    )
    assert "RETROSPECT_DONE" in cp.latest_milestone_set()


# --------------------------------------------------------------------------- #
# GAP-05/07: 自适应轮询间隔（分段策略）
# --------------------------------------------------------------------------- #

def test_adaptive_poll_interval_segments():
    """_adaptive_poll_interval 按耗时分段：初期密、后期疏。"""
    f = AgentTeamsClient._adaptive_poll_interval
    # 0~5min → base
    assert f(elapsed=0, base=10) == 10
    assert f(elapsed=299, base=10) == 10
    # 5~15min → base×2
    assert f(elapsed=300, base=10) == 20
    assert f(elapsed=899, base=10) == 20
    # 15~30min → base×3
    assert f(elapsed=900, base=10) == 30
    assert f(elapsed=1799, base=10) == 30
    # 30min+ → base×6
    assert f(elapsed=1800, base=10) == 60
    assert f(elapsed=99999, base=10) == 60


def test_adaptive_poll_interval_base_scaling():
    """base 参数可配（可传 5/10/20），各段按 base 等比。"""
    f = AgentTeamsClient._adaptive_poll_interval
    assert f(elapsed=0, base=5) == 5
    assert f(elapsed=600, base=5) == 10   # 5min+ → base×2
    assert f(elapsed=2000, base=5) == 30  # 30min+ → base×6
