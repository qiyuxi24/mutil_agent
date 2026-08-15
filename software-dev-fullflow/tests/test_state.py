"""state.py 确定性状态机单元测试。

覆盖：
- 正向流转：8 个主状态沿 FORWARD_TRANSITIONS 逐级推进至终态
- 打回：TEST_FAILED / RELEASE_ROLLED_BACK 打回 FIX_APPLY 并累计 iterations
- 序列化：to_dict / from_dict / save / load 往返一致
- 里程碑握手：advance 记录 verdict/detail/by
"""

from pathlib import Path

from loop.state import (
    Milestone,
    State,
    TaskState,
    FORWARD_TRANSITIONS,
    ROLLBACK_TARGET,
    STATE_EXECUTOR,
)


def _full_pdca_states() -> list[State]:
    """按正向表推导出的完整推进序列（从 SPEC_INPUT 到终态 RETROSPECT）。"""
    seq = [State.SPEC_INPUT]
    cur = State.SPEC_INPUT
    while True:
        nxt = FORWARD_TRANSITIONS[cur]
        if nxt == cur:  # 终态自环
            break
        seq.append(nxt)
        cur = nxt
    return seq


class TestForwardFlow:
    def test_full_pdca_closure(self):
        """从 SPEC_INPUT 逐级推进，应历经全部 8 个状态并到达 RETROSPECT 终态。"""
        states = _full_pdca_states()
        assert len(states) == 8
        assert states[0] == State.SPEC_INPUT
        assert states[-1] == State.RETROSPECT

    def test_advance_full_loop(self):
        """TaskState.advance 沿正向里程碑一路推进，最终停在 RETROSPECT 终态。

        注意正向链为 8 状态：SPEC_INPUT→SPEC_DECOMPOSE→ROOT_CAUSE→FIX_APPLY→
        TEST_VERIFY→RELEASE→RELEASE_APPROVE→RETROSPECT。RELEASE_OK 会出现两次
        （一次推进 RELEASE，一次推进 RELEASE_APPROVE）。
        """
        ts = TaskState(task_id="t1", spec="demo")
        for ms in (
            Milestone.TASK_SPEC_READY,      # → SPEC_DECOMPOSE
            Milestone.ROOT_CAUSE_FOUND,     # → ROOT_CAUSE
            Milestone.FIX_APPLIED,          # → FIX_APPLY
            Milestone.TEST_PASSED,          # → TEST_VERIFY
            Milestone.RELEASE_OK,           # → RELEASE
            Milestone.RELEASE_OK,           # → RELEASE_APPROVE
            Milestone.RETROSPECT_DONE,      # → RETROSPECT
        ):
            ts.advance(ms)
        assert ts.state == State.RETROSPECT
        # 终态再推进仍停留
        assert ts.advance(Milestone.RETROSPECT_DONE) == State.RETROSPECT

    def test_milestone_recorded(self):
        """advance 会把 milestone 的 verdict/detail/by 写入 milestones。"""
        ts = TaskState(task_id="t1")
        ts.advance(Milestone.ROOT_CAUSE_FOUND, verdict="PASS", detail="evidence", by="rootcause")
        rec = ts.milestones[Milestone.ROOT_CAUSE_FOUND.value]
        assert rec["verdict"] == "PASS"
        assert rec["detail"] == "evidence"
        assert rec["by"] == "rootcause"

    def test_state_executor_mapping_complete(self):
        """STATE_EXECUTOR 覆盖全部 8 个主状态，且不产生未知角色。"""
        assert set(STATE_EXECUTOR.keys()) == set(State)
        assert len(set(STATE_EXECUTOR.values())) >= 6  # 至少 6 个不同角色


class TestRollback:
    def test_test_failed_rolls_back_to_fix_apply(self):
        """TEST_FAILED 打回 FIX_APPLY，且 iterations +1。"""
        ts = TaskState(task_id="t1", state=State.TEST_VERIFY)
        assert ts.advance(Milestone.TEST_FAILED, verdict="FAIL", detail="regression") == State.FIX_APPLY
        assert ts.state == ROLLBACK_TARGET
        assert ts.iterations == 1

    def test_release_rolled_back_rolls_back_to_fix_apply(self):
        """RELEASE_ROLLED_BACK 打回 FIX_APPLY，且 iterations +1。"""
        ts = TaskState(task_id="t1", state=State.RELEASE_APPROVE)
        assert ts.advance(Milestone.RELEASE_ROLLED_BACK, verdict="FAIL") == State.FIX_APPLY
        assert ts.iterations == 1

    def test_passing_rollback_signal_ignored(self):
        """防御：PASS verdict 不会携带打回信号触发回退。"""
        ts = TaskState(task_id="t1", state=State.ROOT_CAUSE)
        nxt = ts.advance(Milestone.TEST_FAILED, verdict="PASS")  # 异常输入，PASS 不触发打回
        assert nxt == FORWARD_TRANSITIONS[State.ROOT_CAUSE]  # 走正向推进
        assert ts.iterations == 0


class TestSerialization:
    def test_round_trip_dict(self):
        ts = TaskState(task_id="t1", state=State.FIX_APPLY, spec="fix bug", iterations=2)
        ts.advance(Milestone.FIX_APPLIED, by="fixer")
        restored = TaskState.from_dict(ts.to_dict())
        assert restored.task_id == ts.task_id
        assert restored.state == ts.state
        assert restored.iterations == ts.iterations
        assert restored.milestones == ts.milestones

    def test_save_load(self, tmp_path: Path):
        ts = TaskState(task_id="t1", spec="demo", iterations=1)
        ts.advance(Milestone.ROOT_CAUSE_FOUND, by="rootcause")
        p = tmp_path / "nested" / "state.json"  # 验证自动建目录
        ts.save(p)
        loaded = TaskState.load(p)
        assert loaded.to_dict() == ts.to_dict()
