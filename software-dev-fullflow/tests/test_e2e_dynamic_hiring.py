"""GAP-09 E2E：动态团队演示（TODO 1.2 · 叙事核心卖点"招人/裁员"）。

场景：一次 PDCA 闭环结束后，Manager 用 `evaluation.governance_commands()`
生成治理命令，`apply_governance` 把这些命令落到团队花名册（roster），实现：
  1. 低绩效 Worker → 被 `coach`（培训：换模型/换 SOUL），继续留任
  2. 不合格 Worker → 被 `demote_or_fire`（先归档记忆再裁员），从花名册移除
  3. 空出的角色 → 立即 `create` 新 Worker 补齐（动态招人），保持团队满编

只依赖 `evaluation.py` + `state.py` 的确定性逻辑，不依赖 AgentTeams 真实平台。
运行：`python -m pytest tests/test_e2e_dynamic_hiring.py -v`
"""

from __future__ import annotations

from pathlib import Path

from loop.state import Milestone, TaskState, State, STATE_EXECUTOR
from loop.evaluation import (
    score_team,
    governance_action,
    governance_commands,
    rating_of,
)


# --------------------------------------------------------------------------- #
# 模拟器：把治理命令落到团队花名册（招人/裁员）
# --------------------------------------------------------------------------- #

# 预置 6 Worker 角色（对齐 STATE_EXECUTOR）
BASE_ROLES = ["aggregator", "rootcause", "fixer", "tester", "releaser", "retrospector"]


def apply_governance(roster: list[str], scorecards: dict, cmds: list[str]) -> dict:
    """执行治理命令，返回本轮治理快照。

    Args:
        roster:  当前团队花名册（Worker name 列表，可变，作为模拟器状态）。
        scorecards: 本轮 TeamEvaluation.scorecards（role → AgentScorecard）。
        cmds:    本轮 `evaluation.governance_commands()` 汇总命令。

    治理语义（对齐 evaluation.governance_commands）：
      - 评级 Qualified        → 留任（无命令）
      - 评级 Underperforming  → coach：保留在花名册，仅换模型/换 SOUL
      - 评级 Unqualified      → demote_or_fire：先归档记忆，再从花名册移除
                                 并由 `create` 新 Worker 补齐该角色（动态招人）
    返回快照：{fired: [...], coached: [...], hired: [...], retained: [...]}
    """
    snap = {"fired": [], "coached": [], "hired": [], "retained": []}

    # 1) 依据评级执行治理动作
    for role in list(roster):
        card = scorecards.get(role)
        if card is None:
            continue
        action = governance_action(role, card.rating)
        if action == "demote_or_fire":
            roster.remove(role)
            snap["fired"].append(role)
        elif action == "coach":
            snap["coached"].append(role)
        else:
            snap["retained"].append(role)

    # 2) 对每个被裁角色动态招人补齐（保持团队满编）——叙事"招人"
    for role in snap["fired"]:
        new_name = f"{role}-2"            # 复赛环境：`agt create worker --name {new_name}`
        roster.append(new_name)
        snap["hired"].append(new_name)

    return snap


# --------------------------------------------------------------------------- #
# 构造一个"全员健康 + 有低绩效成员"的闭环 TaskState
# --------------------------------------------------------------------------- #

def _task_with_all_workers() -> TaskState:
    """构造 6 Worker 各完成一个里程碑的完整闭环任务。"""
    ts = TaskState(task_id="dynamic-hiring-001", spec="修复登录接口空用户名500")
    for ms, role in (
        (Milestone.TASK_SPEC_READY, "aggregator"),
        (Milestone.ROOT_CAUSE_FOUND, "rootcause"),
        (Milestone.FIX_APPLIED, "fixer"),
        (Milestone.TEST_PASSED, "tester"),
        (Milestone.RELEASE_OK, "releaser"),
        (Milestone.RETROSPECT_DONE, "retrospector"),
    ):
        ts.advance(ms, by=role)
    ts.artifacts = {st.value: f"{st.value.lower()}.md" for st in State}
    return ts


# --------------------------------------------------------------------------- #
# 测试用例
# --------------------------------------------------------------------------- #

class TestBaselineHealthyTeam:
    def test_healthy_team_all_retained(self):
        """全员绩效达标 → 全部留任，无 coach / fire / hire。"""
        ts = _task_with_all_workers()
        report = score_team(ts)
        assert report.governance_commands() == []

        roster = list(BASE_ROLES)
        snap = apply_governance(roster, report.scorecards, report.governance_commands())
        assert set(snap["retained"]) == set(BASE_ROLES)
        assert snap["fired"] == [] and snap["coached"] == [] and snap["hired"] == []


class TestCoachLowPerformer:
    def _underperforming_task(self) -> TaskState:
        """fixer 一次打回 + 中等偏低采纳 → Underperforming（培训候选）。"""
        ts = _task_with_all_workers()
        # 打回 1 次 + adoption 0.5 → overall≈61 ∈ [60,85) → Underperforming
        report = score_team(
            ts,
            reject_counts={"fixer": 1},
            adoptions={"fixer": 0.5},
        )
        return ts, report

    def test_low_performer_gets_coach_command(self):
        """Underperforming → 治理命令应含"换模型/换 SOUL"培训动作。"""
        ts, report = self._underperforming_task()
        card = report.scorecards["fixer"]
        assert card.rating == "Underperforming"
        cmds = governance_commands("fixer", card.rating)
        assert any("update worker" in c for c in cmds), f"培训命令缺失: {cmds}"
        assert all("delete worker" not in c for c in cmds)

    def test_coach_keeps_worker_on_roster(self):
        """coach 不裁员：fixer 继续留在花名册。"""
        ts, report = self._underperforming_task()
        roster = list(BASE_ROLES)
        snap = apply_governance(roster, report.scorecards, report.governance_commands())
        assert "fixer" in roster, "被 coach 的 Worker 应继续留任"
        assert "fixer" in snap["coached"]
        assert "fixer" not in snap["fired"] and "fixer" not in snap["hired"]


class TestFireAndHire:
    def _unqualified_task(self) -> TaskState:
        """tester 极端差绩效 → Unqualified（裁员 + 招人补齐）。"""
        ts = _task_with_all_workers()
        report = score_team(
            ts,
            reject_counts={"tester": 8},       # 几乎每次都被打回
            adoptions={"tester": 0.0},         # 完全不采纳上游
        )
        return ts, report

    def test_unqualified_gets_fire_command(self):
        """Unqualified → 治理命令含"归档记忆 + delete worker"。"""
        ts, report = self._unqualified_task()
        card = report.scorecards["tester"]
        assert card.rating == "Unqualified"
        cmds = governance_commands("tester", card.rating)
        assert any("delete worker" in c for c in cmds), f"裁员命令缺失: {cmds}"
        assert any("knowledge_export" in c for c in cmds), "应先归档记忆再裁员"

    def test_fired_removed_and_new_worker_hired(self):
        """裁掉 tester → 花名册移除，并 create 新 Worker 补齐（动态招人）。"""
        ts, report = self._unqualified_task()
        roster = list(BASE_ROLES)
        snap = apply_governance(roster, report.scorecards, report.governance_commands())
        # 旧 tester 被裁
        assert "tester" not in roster
        assert "tester" in snap["fired"]
        # 新 Worker 补齐，团队保持满编
        assert "tester-2" in roster
        assert "tester-2" in snap["hired"]
        assert len(roster) == len(BASE_ROLES), "招人后应保持满编"


class TestMixedGovernanceCycle:
    def _mixed_task(self) -> TaskState:
        """混合：fixer 低绩效(coach) + tester 不合格(fire/hire) + 其余留任。"""
        ts = _task_with_all_workers()
        return score_team(
            ts,
            reject_counts={"fixer": 1, "tester": 8},
            adoptions={"fixer": 0.5, "tester": 0.0},
        )

    def test_full_cycle(self):
        """一条闭环同时产生 coach + fire + hire，其余留任，团队满编。"""
        report = self._mixed_task()
        assert report.scorecards["fixer"].rating == "Underperforming"
        assert report.scorecards["tester"].rating == "Unqualified"

        roster = list(BASE_ROLES)
        snap = apply_governance(roster, report.scorecards, report.governance_commands())

        assert snap["fired"] == ["tester"]
        assert snap["coached"] == ["fixer"]
        assert snap["hired"] == ["tester-2"]
        assert set(snap["retained"]) == {"aggregator", "rootcause", "releaser", "retrospector"}
        assert len(roster) == len(BASE_ROLES), "治理后团队应仍满编"
        assert "tester" not in roster and "tester-2" in roster and "fixer" in roster


class TestRatingBoundary:
    def test_boundary_85_qualified(self):
        """overall=85 边界应为 Qualified（留任，无治理命令）。"""
        ts = _task_with_all_workers()
        report = score_team(ts)
        # 用 reject/adoption 调节到 85 附近，直接断言评级函数边界
        assert rating_of(85) == "Qualified"
        assert rating_of(84) == "Underperforming"
        assert rating_of(59) == "Unqualified"

    def test_governance_action_mapping(self):
        """治理动作三态映射正确。"""
        assert governance_action("x", "Qualified") == "retain"
        assert governance_action("x", "Underperforming") == "coach"
        assert governance_action("x", "Unqualified") == "demote_or_fire"
