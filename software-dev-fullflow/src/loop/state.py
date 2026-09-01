"""PDCA 闭环状态机核心。

对应 design/PDCA-CLOSED-LOOP.md：官方闭环 8 环节 → 8 个主状态 + 里程碑握手。
本文件是**确定性状态图**（enum + 转移表），Manager 只负责"根据状态派活"，不负责"记住状态"
（状态在 shared/tasks/{id}/state.json，可审计）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class Milestone(str, Enum):
    """里程碑握手协议 —— 跨 Agent 交接点。"""

    TASK_SPEC_READY = "TASK_SPEC_READY"      # Aggregator 完成，→RootCause
    ROOT_CAUSE_FOUND = "ROOT_CAUSE_FOUND"    # RootCause 完成，→Fixer
    FIX_APPLIED = "FIX_APPLIED"              # Fixer 完成，→Tester
    TEST_PASSED = "TEST_PASSED"              # Tester 通过，→Releaser
    RELEASE_OK = "RELEASE_OK"                # Releaser 审批通过，→Retrospector
    RETROSPECT_DONE = "RETROSPECT_DONE"      # Retrospector 完成，闭环结束

    # 打回信号（非正向里程碑）
    TEST_FAILED = "TEST_FAILED"              # → 打回 Fixer（FIX_APPLY）
    RELEASE_ROLLED_BACK = "RELEASE_ROLLED_BACK"  # → 打回 Fixer（FIX_APPLY）


class State(str, Enum):
    """PDCA 闭环 8 个主状态。"""

    # P 计划
    SPEC_INPUT = "SPEC_INPUT"           # 任务输入（聚合多源缺陷/需求）
    SPEC_DECOMPOSE = "SPEC_DECOMPOSE"   # 任务拆解 → TASK_SPEC_READY
    # D 执行
    ROOT_CAUSE = "ROOT_CAUSE"           # 根因定位 → ROOT_CAUSE_FOUND
    FIX_APPLY = "FIX_APPLY"             # 修复编码 → FIX_APPLIED
    # C 检查
    TEST_VERIFY = "TEST_VERIFY"         # 测试验证 → TEST_PASSED / TEST_FAILED
    # A 处置
    RELEASE = "RELEASE"                 # 发布（灰度/金丝雀）
    RELEASE_APPROVE = "RELEASE_APPROVE" # 审批 → RELEASE_OK / RELEASE_ROLLED_BACK
    RETROSPECT = "RETROSPECT"           # 复盘沉淀 → RETROSPECT_DONE


# 状态 → 默认执行者（角色解耦：Leader 可在任务级覆盖，见 TaskState.executor_for）
# 「一套完整班子」默认执行者映射（2026-08-16 重构）。
# 同一阶段可能有多个员工参与（如 FIX_APPLY 可由 frontend/backend/fixer 任一人），
# 这里给「首选默认」，Leader 可每阶段动态挑人覆盖。
STATE_EXECUTOR: dict[State, str] = {
    State.SPEC_INPUT: "aggregator",
    State.SPEC_DECOMPOSE: "aggregator",
    State.ROOT_CAUSE: "rootcause",
    State.FIX_APPLY: "fixer",
    State.TEST_VERIFY: "tester",
    State.RELEASE: "releaser",
    State.RELEASE_APPROVE: "releaser",
    State.RETROSPECT: "retrospector",
}

# 一套完整班子（新增员工角色，供 Leader 挑人时使用）
TEAM_ROSTER = [
    "leader", "aggregator", "rootcause",
    "frontend", "backend", "fixer",
    "tester", "releaser", "retrospector",
    "doc-manager",
]

# 状态 → 期望的里程碑（该状态完成的标志）
STATE_EXPECTED_MILESTONE: dict[State, Milestone] = {
    State.SPEC_INPUT: Milestone.TASK_SPEC_READY,
    State.SPEC_DECOMPOSE: Milestone.TASK_SPEC_READY,
    State.ROOT_CAUSE: Milestone.ROOT_CAUSE_FOUND,
    State.FIX_APPLY: Milestone.FIX_APPLIED,
    State.TEST_VERIFY: Milestone.TEST_PASSED,
    State.RELEASE: Milestone.RELEASE_OK,
    State.RELEASE_APPROVE: Milestone.RELEASE_OK,
    State.RETROSPECT: Milestone.RETROSPECT_DONE,
}

# 正向状态流转（到达预期里程碑后进入下一个状态）
FORWARD_TRANSITIONS: dict[State, State] = {
    State.SPEC_INPUT: State.SPEC_DECOMPOSE,
    State.SPEC_DECOMPOSE: State.ROOT_CAUSE,
    State.ROOT_CAUSE: State.FIX_APPLY,
    State.FIX_APPLY: State.TEST_VERIFY,
    State.TEST_VERIFY: State.RELEASE,
    State.RELEASE: State.RELEASE_APPROVE,
    State.RELEASE_APPROVE: State.RETROSPECT,
    State.RETROSPECT: State.RETROSPECT,  # 终态
}

# 打回目标（TEST_FAILED / RELEASE_ROLLED_BACK → FIX_APPLY）
ROLLBACK_TARGET = State.FIX_APPLY


@dataclass
class TaskState:
    """单个任务的闭环状态（持久化到 shared/tasks/{id}/state.json）。"""

    task_id: str
    state: State = State.SPEC_INPUT
    spec: str = ""                       # 原始任务/需求描述
    milestones: dict[str, dict] = field(default_factory=dict)  # milestone -> {verdict, detail, by}
    artifacts: dict[str, str] = field(default_factory=dict)    # state -> 产物路径
    iterations: int = 0                   # 打回次数（用于限制死循环）
    created_at: str = ""
    updated_at: str = ""
    # 阶段参与者：{state.value: [员工名,...]} —— Leader 每阶段动态挑人的记录
    stage_participants: dict[str, list[str]] = field(default_factory=dict)

    def executor_for(self, state: State, participants: dict[str, str] | None = None) -> str:
        """返回某阶段的执行者。

        优先级：Leader 每阶段覆盖（participants[state.value]）> 默认 STATE_EXECUTOR。
        这是「Leader 按阶段决定参与员工」的落地点。
        """
        if participants and state.value in participants:
            return participants[state.value]
        return STATE_EXECUTOR.get(state, "unknown")

    def record_participant(self, state: State, participant: str) -> None:
        """记录某阶段由哪个员工执行（阶段参与者字段）。"""
        key = state.value
        if key not in self.stage_participants:
            self.stage_participants[key] = []
        if participant not in self.stage_participants[key]:
            self.stage_participants[key].append(participant)

    def advance(self, milestone: Milestone, verdict: str = "PASS", detail: str = "", by: str = "") -> State:
        """根据收到的里程碑推进/打回状态机。返回新状态。"""
        self.milestones[milestone.value] = {
            "verdict": verdict,
            "detail": detail,
            "by": by,
        }
        if by:
            self.record_participant(self.state, by)
        if verdict == "PASS":
            if milestone in (Milestone.TEST_FAILED, Milestone.RELEASE_ROLLED_BACK):
                # 防御：PASS 不会带打回信号
                pass
            # 推进到下一状态
            nxt = FORWARD_TRANSITIONS.get(self.state, self.state)
            self.state = nxt
        else:
            # 打回（FAIL）
            self.iterations += 1
            self.state = ROLLBACK_TARGET
        return self.state

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TaskState":
        d = dict(d)
        d["state"] = State(d["state"])
        return cls(**d)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "TaskState":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
