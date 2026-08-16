"""Agent 成员评价器：合格度 + 贡献度 + 成长分 + 治理评级。

对应 design/AGENT-EVALUATION.md 的三层评价模型 + KPI-BENCHMARK.md 的 BSC 学习成长维度：
  Layer 1 合格度 Qualification —— 确定性闸门 KPI（客观，零额外 LLM 成本）
  Layer 2 贡献度 Contribution —— 采纳贡献分（轻量）/ 替换基线法（精确，可选）
  Layer 2.5 成长分 Growth    —— 知识跨任务复用率（BSC 学习与成长，对齐 KPI-BENCHMARK §3.4）
  Layer 3 治理 Governance     —— 综合分 → 留任/培训/降级/裁员

纯 Python 实现，只依赖 state.py + knowledge_tracker.py，不依赖 agent_framework，可独立单测：
  cd software-dev-fullflow/src && python -c "from loop.evaluation import score_team; print(score_team)"

信号来源说明：
  - reject_count / elapsed 等"成员级"信号需 Manager 在 run() 里埋点采集后传入；
  - growth_scores 由 knowledge_tracker.UsageTracker.get_agent_growth_score() 提供；
  - 若不传，则用默认值（0 打回 / 期望时延 / 0 成长分），评价退化为"只看里程碑推进"。
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 让 src 目录在 sys.path，支持 `python loop/evaluation.py` 独立运行（对齐 manager.py）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loop.state import TaskState, STATE_EXECUTOR  # noqa: E402

# --------------------------------------------------------------------------- #
# 常量：角色 → 里程碑必要度（贡献权重）/ 期望时延（秒）
# --------------------------------------------------------------------------- #

MILESTONE_WEIGHT: dict[str, float] = {
    "aggregator": 0.8,     # 聚合质量差会带偏下游，但可重聚合
    "rootcause": 0.9,      # 定位错 → 修复方向错
    "fixer": 1.0,          # 核心生产环节，权重最高
    "tester": 0.95,        # 质量闸门，失守则不合格代码流入发布
    "releaser": 0.9,       # 安全红线（发布/回滚）
    "retrospector": 0.7,   # 组织记忆，价值滞后但长期
}

EXPECTED_DURATION: dict[str, float] = {
    "aggregator": 60.0,
    "rootcause": 120.0,
    "fixer": 300.0,
    "tester": 180.0,
    "releaser": 90.0,
    "retrospector": 60.0,
}

# 合格分各项权重（design §5.1）
QUAL_WEIGHTS: dict[str, float] = {
    "once_pass": 0.30,
    "completeness": 0.25,
    "protocol": 0.20,
    "timeliness": 0.15,
    "auditability": 0.10,
}

# 综合分 = 0.5 * 合格分 + 0.35 * 贡献分 + 0.15 * 成长分（对齐 KPI-BENCHMARK §3.4）
# 当 growth_scores 未传入（默认 0）时，权重自动归一化回 0.6/0.4
OVERALL_QUAL_WEIGHT = 0.50
OVERALL_CONTRIB_WEIGHT = 0.35
OVERALL_GROWTH_WEIGHT = 0.15


@dataclass
class AgentScorecard:
    """单个成员的「成绩单」。"""

    role: str
    qual_score: float = 0.0       # 合格分 0-100
    contrib_score: float = 0.0    # 贡献分 0-100
    growth_score: float = 0.0     # 成长分（知识跨任务复用次数，对齐 KPI-BENCHMARK §3.4）
    overall: float = 0.0          # 综合分 0-100
    rating: str = "Unqualified"   # Qualified / Underperforming / Unqualified
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "qual_score": round(self.qual_score, 1),
            "contrib_score": round(self.contrib_score, 1),
            "growth_score": round(self.growth_score, 1),
            "overall": round(self.overall, 1),
            "rating": self.rating,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------- #
# Layer 1：合格度（Qualification）
# --------------------------------------------------------------------------- #

def _once_pass(reject_count: int) -> float:
    """一次通过率：每多打回一次，折扣越大。"""
    return 1.0 / (1.0 + max(0, reject_count))


def _timeliness(elapsed: Optional[float], expected: float) -> float:
    """时效分：超时越多扣越多，提前完成不额外加分。取值 [0, 1]，未采集按满分。"""
    if elapsed is None or elapsed <= 0 or expected <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (elapsed - expected) / expected))


def qualification_score(
    role: str,
    *,
    reject_count: int = 0,
    complete: bool = True,
    protocol_ok: bool = True,
    elapsed: Optional[float] = None,
    auditable: bool = True,
) -> float:
    """计算某个成员的合格分（0-100）。

    Args:
        reject_count: 该成员被 _verify 打回的总次数。
        complete:     产出物非空且关键字段齐全。
        protocol_ok:  发对里程碑词 + 注册 state.json + 无噪音 @mention。
        elapsed:      该成员本次任务总耗时（秒），None 则不计时效。
        auditable:    产物落盘 + 证据留痕。
    """
    w = QUAL_WEIGHTS
    score = 100.0 * (
        w["once_pass"] * _once_pass(reject_count)
        + w["completeness"] * (1.0 if complete else 0.0)
        + w["protocol"] * (1.0 if protocol_ok else 0.0)
        + w["timeliness"] * _timeliness(elapsed, EXPECTED_DURATION.get(role, 60.0))
        + w["auditability"] * (1.0 if auditable else 0.0)
    )
    return round(score, 1)


# --------------------------------------------------------------------------- #
# Layer 2：贡献度（Contribution）
# --------------------------------------------------------------------------- #

def adoption_score(worker_out: str, upstream: str) -> float:
    """下游 Worker 产出对上游产物的「采纳度」（0-1，确定性、零 LLM 成本）。

    轻量测量：下游产出 token 中有多大比例沿用了上游上下文 token，
    即「下游是在上游基础上继续工作，而非凭空自造」。这是 design §3.3
    语义 Shapley「支持关系」的轻量近似——下游产出与上游重叠越多，说明
    越忠实采纳了上游结论，其「贡献链条」越清晰。
    """

    def tokens(text: str) -> set[str]:
        # 中文按连续汉字切分，英文按字母数字下划线切分，统一小写
        return set(re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]", (text or "").lower()))

    out = tokens(worker_out)
    up = tokens(upstream)
    if not out or not up:
        return 0.0
    return round(len(out & up) / len(out), 3)


def contribution_score(
    role: str,
    *,
    adoption: float = 1.0,
    reject_count: int = 0,
) -> float:
    """计算某个成员的贡献分（0-100），采用「轻量：采纳贡献分」。

    Contrib = 100 * adoption * milestone_weight * reject_penalty
      adoption        下游产出引用该成员产出的程度（语义支持关系的轻量近似）。
      milestone_weight 该成员里程碑在闭环中的必要度（MILESTONE_WEIGHT）。
      reject_penalty   1 / (1 + 打回次数)。

    精确方案（替换基线法，需重跑下游）见 design/AGENT-EVALUATION.md §3.3，
    本骨架只落地零重跑的轻量方案。
    """
    adoption = max(0.0, min(1.0, adoption))
    weight = MILESTONE_WEIGHT.get(role, 0.5)
    penalty = 1.0 / (1.0 + max(0, reject_count))
    return round(100.0 * adoption * weight * penalty, 1)


# --------------------------------------------------------------------------- #
# Layer 3：治理评级
# --------------------------------------------------------------------------- #

def rating_of(overall: float) -> str:
    """综合分 → 评级（三级）。"""
    if overall >= 85:
        return "Qualified"          # 留任
    if overall >= 60:
        return "Underperforming"    # 培训/换模型/换提示词
    return "Unqualified"            # 降级/裁员候选


def governance_action(role: str, rating: str) -> str:
    """评级 → 治理动作（对齐 design §3.4）。"""
    if rating == "Qualified":
        return "retain"              # 留任
    if rating == "Underperforming":
        return "coach"               # 培训
    return "demote_or_fire"          # 降级/裁员


def governance_commands(role: str, rating: str) -> list[str]:
    """评级 → AgentTeams 可执行治理命令（对齐 design §7 落地映射）。

    - retain          : 无操作（可选升权，暂不生成命令）
    - coach           : 换模型 / 换 SOUL 提示词（培训）
    - demote_or_fire  : 先归档记忆（knowledge_export），再删除 Worker（裁员）
    """
    if rating == "Qualified":
        return []                                   # 留任，无需操作
    if rating == "Underperforming":
        return [
            f"agt update worker --name {role} --model deepseek-v4-flash",       # 换更强/换模型
            f"agt update worker --name {role} --soul-file workers/{role}/SOUL.md",  # 换提示词
        ]
    return [
        f"# 归档记忆后裁员（先 knowledge_export {role} → shared/knowledge/）",
        f"agt delete worker --name {role}",
    ]


# --------------------------------------------------------------------------- #
# 聚合：一次任务 → 团队评价报告
# --------------------------------------------------------------------------- #

@dataclass
class TeamEvaluation:
    """一次任务所有成员的评价报告。"""

    task_id: str
    scorecards: dict[str, AgentScorecard] = field(default_factory=dict)

    def report(self) -> str:
        lines = [f"=== 团队评价报告 · 任务 {self.task_id} ==="]
        lines.append(f"{'角色':<14}{'合格分':>8}{'贡献分':>8}{'成长分':>8}{'综合分':>8}  {'评级':<16}{'治理动作'}")
        for role, card in self.scorecards.items():
            action = governance_action(role, card.rating)
            lines.append(
                f"{role:<14}{card.qual_score:>8}{card.contrib_score:>8}"
                f"{card.growth_score:>8}{card.overall:>8}  {card.rating:<16}{action}"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "scorecards": {r: c.to_dict() for r, c in self.scorecards.items()},
        }

    def save_scorecards(self, agents_dir: Path) -> list[Path]:
        """把每个成员的成绩单落盘到 shared/agents/{name}/scorecard.json。

        对齐 design §7：成员成绩单是「可审计留痕」，落 Agent 记忆目录，
        可跨任务累积形成"越评越准"的历史趋势。返回写入的文件路径列表。
        """
        agents_dir = Path(agents_dir)
        paths: list[Path] = []
        for role, card in self.scorecards.items():
            p = agents_dir / role / "scorecard.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(card.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            paths.append(p)
        return paths

    def governance_commands(self) -> list[str]:
        """汇总全体成员的治理命令（按角色稳定排序，留任者不产生命令）。"""
        cmds: list[str] = []
        for role, card in self.scorecards.items():
            cmds.extend(governance_commands(role, card.rating))
        return cmds


def score_team(
    task_state: TaskState,
    *,
    reject_counts: Optional[dict[str, int]] = None,
    durations: Optional[dict[str, float]] = None,
    adoptions: Optional[dict[str, float]] = None,
    protocol_oks: Optional[dict[str, bool]] = None,
    growth_scores: Optional[dict[str, float]] = None,
) -> TeamEvaluation:
    """入口：由一次任务的 TaskState 产出团队评价报告。

    Args:
        task_state:   state.py 的 TaskState（含 milestones 的 by/verdict、artifacts）。
        reject_counts: 成员 → 打回次数（Manager 埋点采集；缺省按 0 处理）。
        durations:     成员 → 总耗时秒（Manager 埋点采集；缺省按期望时延）。
        adoptions:     成员 → 下游采纳度 0-1（缺省按 1.0 全采纳）。
        protocol_oks:  成员 → 协议合规（里程碑词 + 交接 @mention；缺省按 True）。
        growth_scores: 成员 → 成长分（knowledge_tracker 采集；缺省按 0 处理）。
                       成长分 = 该成员沉淀的知识被跨任务 RAG 检索命中的总次数。
    """
    reject_counts = reject_counts or {}
    durations = durations or {}
    adoptions = adoptions or {}
    protocol_oks = protocol_oks or {}
    growth_scores = growth_scores or {}

    # 从 milestones 提取"谁负责了哪个里程碑"（by 字段，state.py 已记录）
    participants: set[str] = set()
    for ms in task_state.milestones.values():
        by = ms.get("by")
        if by:
            participants.add(by)

    # 从 artifacts 提取"该角色是否真的产出了文件"（completeness / auditability 信号）
    artifacts = task_state.artifacts or {}

    # role → 负责的 state 列表（用于判定该角色是否有产物落盘）
    states_by_role: dict[str, list] = {}
    for st, r in STATE_EXECUTOR.items():
        states_by_role.setdefault(r, []).append(st)

    cards: dict[str, AgentScorecard] = {}
    for role in sorted(participants):
        reject = reject_counts.get(role, 0)
        elapsed = durations.get(role)
        # 有产物路径即视为产出完整 + 可审计（骨架简化；精确需解析产物内容字段）
        role_states = states_by_role.get(role, [])
        has_artifact = (
            any(st.value in artifacts for st in role_states) if artifacts else True
        )
        qual = qualification_score(
            role,
            reject_count=reject,
            complete=has_artifact,
            protocol_ok=protocol_oks.get(role, True),
            elapsed=elapsed,
            auditable=has_artifact,
        )
        contrib = contribution_score(
            role,
            adoption=adoptions.get(role, 1.0),
            reject_count=reject,
        )
        growth = growth_scores.get(role, 0.0)

        # 综合分 = 0.50 * 合格分 + 0.35 * 贡献分 + 0.15 * 成长分
        # 当 growth 为 0 时（未传入），权重自动归一化：合格分和贡献分按比例重新分配 15% 的权重
        if growth > 0:
            overall = round(
                OVERALL_QUAL_WEIGHT * qual
                + OVERALL_CONTRIB_WEIGHT * contrib
                + OVERALL_GROWTH_WEIGHT * growth,
                1,
            )
        else:
            # 无成长分时，保持与原公式兼容：0.6 * qual + 0.4 * contrib
            overall = round(0.6 * qual + 0.4 * contrib, 1)

        cards[role] = AgentScorecard(
            role=role,
            qual_score=qual,
            contrib_score=contrib,
            growth_score=growth,
            overall=overall,
            rating=rating_of(overall),
            detail={
                "reject_count": reject,
                "elapsed": elapsed,
                "adoption": adoptions.get(role, 1.0),
                "growth_score": growth,
                "protocol_ok": protocol_oks.get(role, True),
                "milestone_weight": MILESTONE_WEIGHT.get(role, 0.5),
            },
        )

    return TeamEvaluation(task_id=task_state.task_id, scorecards=cards)


# --------------------------------------------------------------------------- #
# 自检（可直接运行，验证骨架逻辑）
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    # 构造一个最小 TaskState 演示：两个成员各完成一个里程碑
    ts = TaskState(task_id="demo-001", spec="演示：评价器自检")
    ts.milestones = {
        "ROOT_CAUSE_FOUND": {"verdict": "PASS", "detail": "ok", "by": "rootcause"},
        "FIX_APPLIED": {"verdict": "PASS", "detail": "ok", "by": "fixer"},
    }
    ts.artifacts = {"ROOT_CAUSE": "rootcause.md", "FIX_APPLY": "fixer.md"}

    # 不带成长分（兼容旧行为）
    report = score_team(
        ts,
        reject_counts={"fixer": 1},          # fixer 被打回一次
        durations={"rootcause": 100.0, "fixer": 400.0},
    )
    print(report.report())
    print("\nJSON:", report.to_dict())

    print("\n" + "=" * 60)

    # 带成长分（新行为：retrospector 沉淀的知识已被跨任务检索 3 次）
    ts2 = TaskState(task_id="demo-002", spec="演示：带成长分")
    ts2.milestones = {
        "ROOT_CAUSE_FOUND": {"verdict": "PASS", "detail": "ok", "by": "rootcause"},
        "FIX_APPLIED": {"verdict": "PASS", "detail": "ok", "by": "fixer"},
        "RETROSPECT_DONE": {"verdict": "PASS", "detail": "ok", "by": "retrospector"},
    }
    ts2.artifacts = {"ROOT_CAUSE": "rootcause.md", "FIX_APPLY": "fixer.md", "RETROSPECT": "retrospect.json"}

    report2 = score_team(
        ts2,
        reject_counts={"fixer": 1},
        durations={"rootcause": 100.0, "fixer": 400.0, "retrospector": 50.0},
        growth_scores={"retrospector": 3.0},  # retrospector 的知识被跨任务复用了 3 次
    )
    print(report2.report())
    print("\nJSON:", report2.to_dict())
