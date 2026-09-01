"""evaluation.py 三层评价模型单元测试。

覆盖：
- 合格分：once_pass / completeness / protocol / timeliness / auditability 权重与边界
- 贡献分：adoption / milestone_weight / reject_penalty 计算
- 治理评级：Qualified / Underperforming / Unqualified 阈值
- 治理命令：retain / coach / demote_or_fire
- 团队聚合：score_team 从 TaskState 产出报告，scorecard 落盘
"""

from pathlib import Path

import pytest

from loop.state import Milestone, TaskState, State
from loop.evaluation import (
    AgentScorecard,
    TeamEvaluation,
    adoption_score,
    contribution_score,
    governance_action,
    governance_commands,
    qualification_score,
    rating_of,
    score_team,
    EXPECTED_DURATION,
    MILESTONE_WEIGHT,
)


class TestQualification:
    def test_perfect_score(self):
        """全绿输入应为满分 100。"""
        assert qualification_score(
            "fixer", reject_count=0, complete=True, protocol_ok=True,
            elapsed=10.0, auditable=True,
        ) == 100.0

    def test_reject_penalty(self):
        """每多一次打回，once_pass 折扣越明显。"""
        s0 = qualification_score("fixer", reject_count=0, complete=True)
        s1 = qualification_score("fixer", reject_count=1, complete=True)
        s2 = qualification_score("fixer", reject_count=2, complete=True)
        assert s0 == 100.0
        assert s1 < s0
        assert s2 < s1

    def test_incomplete_pulls_down(self):
        """产物缺失时 completeness 权重全扣。"""
        full = qualification_score("fixer", complete=True, protocol_ok=True, auditable=True)
        missing = qualification_score("fixer", complete=False, protocol_ok=True, auditable=True)
        assert missing == round(full - 100.0 * 0.25, 1)

    def test_timeliness_overtime(self):
        """超时扣时效分；未采集 elapsed 按满分。"""
        expected = EXPECTED_DURATION["rootcause"]  # 120s
        on_time = qualification_score("rootcause", elapsed=expected, complete=True)
        overtime = qualification_score("rootcause", elapsed=expected * 2, complete=True)
        assert on_time > overtime
        unknown = qualification_score("rootcause", elapsed=None, complete=True)
        assert unknown == 100.0  # 未采集不计时效

    def test_score_bounds(self):
        """分数恒在 [0,100]。"""
        for role in MILESTONE_WEIGHT:
            s = qualification_score(role, reject_count=99, complete=False,
                                    protocol_ok=False, elapsed=1e9, auditable=False)
            assert 0.0 <= s <= 100.0


class TestContribution:
    def test_full_adoption_high(self):
        """全采纳 + 零打回 → 100 * weight。"""
        assert contribution_score("fixer", adoption=1.0, reject_count=0) == 100.0

    def test_low_adoption(self):
        """低采纳度显著拉低贡献分。"""
        assert contribution_score("fixer", adoption=0.0, reject_count=0) == 0.0

    def test_weight_differ_by_role(self):
        """里程碑必要度权重不同 → 同条件贡献分不同。"""
        s_fixer = contribution_score("fixer", adoption=1.0, reject_count=0)
        s_retro = contribution_score("retrospector", adoption=1.0, reject_count=0)
        assert s_fixer == 100.0
        assert s_retro == 100.0 * MILESTONE_WEIGHT["retrospector"]
        assert s_fixer > s_retro

    def test_reject_penalty(self):
        """打回次数越多贡献分越低。"""
        assert contribution_score("tester", adoption=1.0, reject_count=0) > \
               contribution_score("tester", adoption=1.0, reject_count=2)

    def test_adoption_clamped(self):
        """adoption 输入越界被 clamp 到 [0,1]。"""
        assert contribution_score("fixer", adoption=-5, reject_count=0) == 0.0
        assert contribution_score("fixer", adoption=9, reject_count=0) == 100.0


class TestAdoptionScore:
    def test_shared_terms_overlap(self):
        """下游沿用上游 token 越多，采纳度越高。"""
        upstream = "the root cause is a null pointer dereference in parser"
        downstream = "fix the null pointer dereference in parser"
        assert adoption_score(downstream, upstream) > 0.5

    def test_disjoint_zero(self):
        """完全无关产出 → 采纳度 0。"""
        assert adoption_score("completely different output", "hello world 中文无关") == 0.0

    def test_empty_input(self):
        """空输入安全返回 0。"""
        assert adoption_score("", "anything") == 0.0
        assert adoption_score("anything", "") == 0.0


class TestGovernance:
    def test_rating_thresholds(self):
        assert rating_of(95) == "Qualified"
        assert rating_of(85) == "Qualified"
        assert rating_of(84) == "Underperforming"
        assert rating_of(60) == "Underperforming"
        assert rating_of(59) == "Unqualified"

    def test_governance_action(self):
        assert governance_action("fixer", "Qualified") == "retain"
        assert governance_action("fixer", "Underperforming") == "coach"
        assert governance_action("fixer", "Unqualified") == "demote_or_fire"

    def test_governance_commands(self):
        assert governance_commands("fixer", "Qualified") == []
        assert any("update worker" in c for c in governance_commands("fixer", "Underperforming"))
        assert any("delete worker" in c for c in governance_commands("fixer", "Unqualified"))


class TestTeamEvaluation:
    def _completed_task(self) -> TaskState:
        ts = TaskState(task_id="demo-001", spec="demo")
        ts.advance(Milestone.ROOT_CAUSE_FOUND, by="rootcause")
        ts.advance(Milestone.FIX_APPLIED, by="fixer")
        ts.artifacts = {"ROOT_CAUSE": "rootcause.md", "FIX_APPLY": "fixer.md"}
        return ts

    def test_score_team_participants(self):
        """score_team 应覆盖参与里程碑的所有角色。"""
        ts = self._completed_task()
        report = score_team(ts)
        assert "rootcause" in report.scorecards
        assert "fixer" in report.scorecards

    def test_score_team_reject_counts_affect_overall(self):
        """打回次数影响综合分（合格 + 贡献双重衰减）。"""
        ts = self._completed_task()
        base = score_team(ts).scorecards["fixer"]
        punished = score_team(ts, reject_counts={"fixer": 2}).scorecards["fixer"]
        assert punished.overall < base.overall

    def test_growth_score_applies_015_weight(self):
        """成长分按 0.5/0.35/0.15 计入综合分（对齐 KPI-BENCHMARK §3.4）。

        验证：传 growth_scores 时走完整 0.5/0.35/0.15 公式，
        且 growth>0 时综合分高于 growth=0 的退化分支（0.6/0.4）。

        用低采纳度让 contrib<100，避免满分封顶掩盖 growth 抬升。
        """
        ts = TaskState(task_id="growth-002", spec="demo")
        ts.advance(Milestone.FIX_APPLIED, by="fixer")
        ts.artifacts = {"FIX_APPLY": "fixer.md"}
        # 低采纳度（0.5）→ contrib < 100，综合分未封顶，growth 能体现
        adoptions = {"fixer": 0.5}

        base = score_team(ts, adoptions=adoptions).scorecards["fixer"]
        with_growth = score_team(
            ts, adoptions=adoptions, growth_scores={"fixer": 100.0},
        ).scorecards["fixer"]
        assert with_growth.growth_score == 100.0
        assert with_growth.overall > base.overall
        assert with_growth.overall <= 100.0

        # 精确校验权重：qual=100、contrib=50（采纳度0.5）
        #   growth=0  → 退化公式 0.6*100 + 0.4*50 = 80.0
        #   growth=10 → 完整公式 0.5*100 + 0.35*50 + 0.15*10 = 69.0（0.15 权重生效）
        card0 = score_team(
            ts, adoptions=adoptions, growth_scores={"fixer": 0.0},
        ).scorecards["fixer"]
        card10 = score_team(
            ts, adoptions=adoptions, growth_scores={"fixer": 10.0},
        ).scorecards["fixer"]
        assert card0.qual_score == 100.0
        assert card0.contrib_score == 50.0
        # growth=0 走退化 0.6/0.4
        assert card0.overall == round(0.6 * card0.qual_score + 0.4 * card0.contrib_score, 1)
        # growth=10 走完整 0.5/0.35/0.15，成长分占 0.15 权重
        assert card10.overall == round(
            0.5 * card10.qual_score + 0.35 * card10.contrib_score + 0.15 * card10.growth_score,
            1,
        )
        # 成长分确实抬升：10 分成长贡献 0.15*10=1.5
        assert card10.overall == round(0.5 * 100.0 + 0.35 * 50.0 + 0.15 * 10.0, 1)

    def test_scorecard_persistence(self, tmp_path: Path):
        """scorecard 可落盘到 agents/{role}/scorecard.json。"""
        ts = self._completed_task()
        report = score_team(ts)
        paths = report.save_scorecards(tmp_path)
        assert len(paths) >= 2
        for p in paths:
            assert p.exists()
        # 落盘内容可反序列化
        import json
        card = json.loads((tmp_path / "fixer" / "scorecard.json").read_text(encoding="utf-8"))
        assert card["role"] == "fixer"
        assert 0 <= card["overall"] <= 100

    def test_report_string_renderable(self):
        """report() 能生成可读文本。"""
        ts = self._completed_task()
        text = score_team(ts).report()
        assert "任务 demo-001" in text
        assert "fixer" in text
