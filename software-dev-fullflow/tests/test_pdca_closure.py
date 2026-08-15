"""GAP-09 集成测试：Mock 模式完整 PDCA 闭环（不依赖 AgentTeams 平台）。

覆盖：
  1. `run_pdca_task(mock=True)` 走完整 6 Worker 闭环 → 最终 RETROSPECT
  2. 6 个里程碑全部达成 + 6 个阶段产物落盘
  3. **闭环结束后 state.json 持久化最终状态**（锁定修复：
     `agentteams_loop.run()` 之前在 finally 只 close audit，未 save 最终状态机，
     导致 state.json 停在 SPEC_INPUT。已修复为 run() 结束统一 save）
  4. 审计日志留痕（mock 阶段写 milestone 事件）
  5. 评价成绩单落盘（shared/agents/<name>/scorecard.json）

所有测试为同步 + `asyncio.run()`，不依赖 pytest-asyncio 插件。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from loop.agentteams_loop import AgentTeamsLoop, run_pdca_task
from loop.state import State

EXPECTED_MILESTONES = [
    "TASK_SPEC_READY",
    "ROOT_CAUSE_FOUND",
    "FIX_APPLIED",
    "TEST_PASSED",
    "RELEASE_OK",
    "RETROSPECT_DONE",
]


def test_mock_full_pdca_closure(tmp_path: Path):
    """Mock 模式完整闭环：RETROSPECT 终态 + 6 里程碑。"""
    state = asyncio.run(run_pdca_task(
        spec="修复登录页面空指针异常",
        workdir=tmp_path,
        mock=True,
        task_id="t-closure",
    ))
    assert state.state == State.RETROSPECT
    assert state.milestones["RETROSPECT_DONE"]["verdict"] == "PASS"
    for ms in EXPECTED_MILESTONES:
        assert ms in state.milestones, f"缺少里程碑 {ms}"
    assert len(state.milestones) == 6
    # 产物落盘：mock 走 8 个状态（SPEC_INPUT/SPEC_DECOMPOSE/ROOT_CAUSE/FIX_APPLY/
    # TEST_VERIFY/RELEASE/RELEASE_APPROVE/RETROSPECT），每状态产出一个 md
    assert len(state.artifacts) == 8


def test_state_json_persists_final_state(tmp_path: Path):
    """修复回归锁：闭环结束后 state.json 必须保存最终状态（非初始 SPEC_INPUT）。

    这是 GAP-03/叙事"共享状态落地"的证据：观测层状态机在闭环后持久化，
    供外部读取最终结果。修复前 state.json 只保存了 run() 开头的初始状态。
    """
    task_id = "t-persist"
    loop = AgentTeamsLoop(
        task_id=task_id, spec="修复登录接口空用户名500",
        workdir=tmp_path, mock=True,
    )
    asyncio.run(loop.run())

    state_json = tmp_path / "shared" / "tasks" / task_id / "state.json"
    assert state_json.exists(), "闭环后 state.json 应存在"
    data = json.loads(state_json.read_text(encoding="utf-8"))
    assert data["state"] == "RETROSPECT", f"最终状态应为 RETROSPECT，实际 {data['state']}"
    assert "RETROSPECT_DONE" in data["milestones"]
    assert len(data["milestones"]) == 6


def test_audit_trail_written(tmp_path: Path):
    """闭环留痕：审计日志包含里程碑事件。"""
    task_id = "t-audit"
    loop = AgentTeamsLoop(
        task_id=task_id, spec="修复登录接口空用户名500",
        workdir=tmp_path, mock=True,
    )
    asyncio.run(loop.run())

    audit_dir = tmp_path / "shared" / "audit"
    jsonl = list(audit_dir.glob("*.jsonl"))
    assert jsonl, "应生成审计日志文件"
    text = jsonl[0].read_text(encoding="utf-8")
    # mock 模式也会写 milestone 事件（agentteams_loop._run_mock 调 log_milestone）
    assert "RETROSPECT_DONE" in text
    assert "TASK_SPEC_READY" in text


def test_scorecards_persisted(tmp_path: Path):
    """评价成绩单落盘：闭环结束自动输出 6 个 Agent 的 scorecard。"""
    task_id = "t-score"
    loop = AgentTeamsLoop(
        task_id=task_id, spec="修复登录接口空用户名500",
        workdir=tmp_path, mock=True,
    )
    asyncio.run(loop.run())

    agents_dir = tmp_path / "shared" / "agents"
    scorecards = list(agents_dir.rglob("scorecard.json"))
    # 6 个 Agent + manager 也可能写
    assert len(scorecards) >= 6, f"应至少 6 份成绩单，实际 {len(scorecards)}"
