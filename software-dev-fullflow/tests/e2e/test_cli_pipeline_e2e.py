"""P0-CLI: run.py 命令行管道端到端测试。

通过 subprocess 运行 `run.py --mock`，验证完整 PDCA 闭环管线：
  P0-CLI-01: Mock 模式完整 PDCA 闭环（8 阶段 → RETROSPECT）
  P0-CLI-02: 产物文件生成验证（state.json + 8 阶段 md）
  P0-CLI-03: 审计日志留痕
  P0-CLI-04: 评价成绩单落盘
  P0-CLI-05: 绩效评价反哺 → 治理命令输出
  P0-CLI-06: 异常输入处理
  P0-CLI-07: 降级策略验证（委托→mock fallback）

运行方式：
    python -m pytest tests/e2e/test_cli_pipeline_e2e.py -v
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from tests.e2e.conftest import run_cli
from loop.state import State, Milestone, TaskState, STATE_EXECUTOR
from loop.agentteams_loop import AgentTeamsLoop


# ========================================================================== #
# P0-CLI-01: Mock 模式完整 PDCA 闭环
# ========================================================================== #

class TestMockPDCAClosure:
    """P0-CLI-01: Mock 模式完整 PDCA 闭环（通过 AgentTeamsLoop API）。"""

    def test_mock_closure_reaches_retrospect(self, tmp_path):
        """Mock 模式应从 SPEC_INPUT 走到 RETROSPECT。"""
        loop = AgentTeamsLoop(
            task_id="e2e-cli-001",
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            mock=True,
        )
        state = asyncio.run(loop.run())
        assert state.state == State.RETROSPECT
        assert "RETROSPECT_DONE" in state.milestones

    def test_mock_closure_all_6_milestones(self, tmp_path):
        """Mock 模式应达成全部 6 个里程碑。"""
        loop = AgentTeamsLoop(
            task_id="e2e-cli-002",
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            mock=True,
        )
        state = asyncio.run(loop.run())

        expected = [
            "TASK_SPEC_READY", "ROOT_CAUSE_FOUND", "FIX_APPLIED",
            "TEST_PASSED", "RELEASE_OK", "RETROSPECT_DONE",
        ]
        for ms in expected:
            assert ms in state.milestones, f"缺少里程碑 {ms}"
        assert len(state.milestones) == 6

    def test_mock_closure_8_artifacts(self, tmp_path):
        """Mock 模式应产出 8 个阶段产物。"""
        loop = AgentTeamsLoop(
            task_id="e2e-cli-003",
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            mock=True,
        )
        state = asyncio.run(loop.run())
        assert len(state.artifacts) == 8
        for artifact_path in state.artifacts.values():
            assert Path(artifact_path).exists(), f"产物文件不存在: {artifact_path}"

    def test_mock_closure_with_chinese_spec(self, tmp_path):
        """中文任务描述应正常完成闭环。"""
        loop = AgentTeamsLoop(
            task_id="e2e-cli-004",
            spec="并发场景下订单状态不一致，需要定位根因并修复",
            workdir=tmp_path,
            mock=True,
        )
        state = asyncio.run(loop.run())
        assert state.state == State.RETROSPECT

    def test_mock_closure_performance(self, tmp_path):
        """Mock 模式闭环应在 10 秒内完成。"""
        import time
        t0 = time.time()

        loop = AgentTeamsLoop(
            task_id="e2e-cli-005",
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            mock=True,
        )
        state = asyncio.run(loop.run())
        elapsed = time.time() - t0

        assert state.state == State.RETROSPECT
        assert elapsed < 10.0, f"Mock 闭环应在 10 秒内完成，实际 {elapsed:.1f}s"


# ========================================================================== #
# P0-CLI-02: 产物文件验证
# ========================================================================== #

class TestArtifactGeneration:
    """P0-CLI-02: 产物文件生成验证。"""

    def test_state_json_persisted(self, tmp_path):
        """state.json 应持久化最终状态。"""
        loop = AgentTeamsLoop(
            task_id="e2e-artifact-001",
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            mock=True,
        )
        asyncio.run(loop.run())

        state_json = tmp_path / "shared" / "tasks" / "e2e-artifact-001" / "state.json"
        assert state_json.exists(), "state.json 应存在"
        data = json.loads(state_json.read_text(encoding="utf-8"))
        assert data["state"] == "RETROSPECT"

    def test_all_phase_md_files_generated(self, tmp_path):
        """所有 8 个阶段应生成对应的 .md 产物文件。"""
        loop = AgentTeamsLoop(
            task_id="e2e-artifact-002",
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            mock=True,
        )
        asyncio.run(loop.run())

        tasks_dir = tmp_path / "shared" / "tasks" / "e2e-artifact-002"
        md_files = list(tasks_dir.glob("*.md"))
        assert len(md_files) == 8, f"应有 8 个 md 文件，实际 {len(md_files)}: {[f.name for f in md_files]}"

        expected_phases = [
            "spec_input", "spec_decompose", "root_cause",
            "fix_apply", "test_verify", "release",
            "release_approve", "retrospect",
        ]
        for phase in expected_phases:
            f = tasks_dir / f"{phase}.md"
            assert f.exists(), f"缺少产物: {phase}.md"

    def test_audit_jsonl_generated(self, tmp_path):
        """审计日志 JSONL 文件应生成。"""
        loop = AgentTeamsLoop(
            task_id="e2e-artifact-003",
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            mock=True,
        )
        asyncio.run(loop.run())

        audit_dir = tmp_path / "shared" / "audit"
        jsonl_files = list(audit_dir.glob("*.jsonl"))
        assert len(jsonl_files) > 0, "应生成审计日志文件"

        content = jsonl_files[0].read_text(encoding="utf-8")
        assert "TASK_SPEC_READY" in content
        assert "RETROSPECT_DONE" in content

    def test_scorecards_generated(self, tmp_path):
        """评价成绩单应生成（至少 6 个 Agent）。"""
        loop = AgentTeamsLoop(
            task_id="e2e-artifact-004",
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            mock=True,
        )
        asyncio.run(loop.run())

        agents_dir = tmp_path / "shared" / "agents"
        scorecards = list(agents_dir.rglob("scorecard.json"))
        assert len(scorecards) >= 6, f"应至少 6 份成绩单，实际 {len(scorecards)}"


# ========================================================================== #
# P0-CLI-03: 降级策略验证
# ========================================================================== #

class TestDegradationStrategy:
    """P0-CLI-03: 委托模式降级策略验证。"""

    def test_delegated_falls_back_to_mock(self, tmp_path, monkeypatch):
        """委托模式 ping 失败 → 自动降级到 mock 完整闭环。"""
        from loop.agentteams_client import AgentTeamsClient

        async def _ping_false(self):
            return False

        monkeypatch.setattr(AgentTeamsClient, "ping", _ping_false)

        loop = AgentTeamsLoop(
            task_id="e2e-degrade-001",
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            mock=False,  # 委托模式
        )
        state = asyncio.run(loop.run())

        assert state.state == State.RETROSPECT
        assert "RETROSPECT_DONE" in state.milestones

        # 审计日志应记录降级
        audit_dir = tmp_path / "shared" / "audit"
        jsonl = list(audit_dir.glob("*.jsonl"))
        assert jsonl
        text = jsonl[0].read_text(encoding="utf-8")
        assert "degrade_to_mock" in text


# ========================================================================== #
# P0-CLI-04: 状态机正确性（通过 CLI 路径验证）
# ========================================================================== #

class TestStateMachineViaCLI:
    """P0-CLI-04: 状态机正确性验证。"""

    def test_forward_transitions_complete(self, tmp_path):
        """正向流转：SPEC_INPUT → ... → RETROSPECT 全部贯通。"""
        loop = AgentTeamsLoop(
            task_id="e2e-sm-001",
            spec="测试状态机正向流转",
            workdir=tmp_path,
            mock=True,
        )
        state = asyncio.run(loop.run())

        # 验证所有里程碑按顺序出现
        milestone_order = list(state.milestones.keys())
        expected_order = [
            "TASK_SPEC_READY", "ROOT_CAUSE_FOUND", "FIX_APPLIED",
            "TEST_PASSED", "RELEASE_OK", "RETROSPECT_DONE",
        ]
        assert milestone_order == expected_order, \
            f"里程碑顺序错误: {milestone_order}"

    def test_rollback_on_test_failed(self):
        """TEST_FAILED → 打回到 FIX_APPLY。"""
        ts = TaskState(task_id="e2e-sm-002", spec="测试打回")
        # 先推进到 FIX_APPLY
        ts.state = State.FIX_APPLY
        # 模拟测试失败
        ts.advance(Milestone.TEST_FAILED, verdict="FAIL", detail="边界值未覆盖", by="tester")
        assert ts.state == State.FIX_APPLY
        assert ts.iterations == 1

    def test_rollback_on_release_rolled_back(self):
        """RELEASE_ROLLED_BACK → 打回到 FIX_APPLY。"""
        ts = TaskState(task_id="e2e-sm-003", spec="测试回滚")
        ts.state = State.RELEASE_APPROVE
        ts.advance(Milestone.RELEASE_ROLLED_BACK, verdict="FAIL", detail="灰度异常", by="releaser")
        assert ts.state == State.FIX_APPLY
        assert ts.iterations == 1

    def test_retrospect_is_terminal(self):
        """RETROSPECT 是终态，不会继续推进。"""
        ts = TaskState(task_id="e2e-sm-004", spec="测试终态")
        ts.state = State.RETROSPECT
        ts.advance(Milestone.RETROSPECT_DONE, by="retrospector")
        assert ts.state == State.RETROSPECT  # 保持在终态

    def test_state_executor_mapping_complete(self):
        """STATE_EXECUTOR 覆盖所有 8 个状态。"""
        assert len(STATE_EXECUTOR) == 8
        for st in State:
            assert st in STATE_EXECUTOR, f"状态 {st} 缺少执行者映射"


# ========================================================================== #
# P0-CLI-05: 子进程 CLI 直接运行
# ========================================================================== #

class TestSubprocessCLI:
    """P0-CLI-05: 通过 subprocess 直接运行 run.py 验证。"""

    def test_run_py_mock_exits_cleanly(self, tmp_path, venv_python, run_py_path):
        """run.py --mock 应正常退出（exit code 0）。"""
        result = run_cli(
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            venv_python=venv_python,
            run_py_path=run_py_path,
        )
        assert result.returncode == 0, f"CLI 应正常退出，stderr: {result.stderr[:500]}"

    def test_run_py_mock_output_contains_closure(self, tmp_path, venv_python, run_py_path):
        """run.py --mock 输出应包含闭环完成信息。"""
        result = run_cli(
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            venv_python=venv_python,
            run_py_path=run_py_path,
        )
        output = result.stdout + result.stderr
        assert "闭环完成" in output or "RETROSPECT" in output or "总耗时" in output, \
            f"输出应包含闭环信息，实际: {output[:500]}"

    def test_run_py_mock_generates_state_json(self, tmp_path, venv_python, run_py_path):
        """run.py --mock 应生成 state.json。

        注意：run.py 硬编码 DEFAULT_DATA_DIR = src/data/，
        不受 cwd 影响。产物写入 src/data/shared/tasks/<task_id>/。
        本测试验证该路径确实生成了 state.json。
        """
        result = run_cli(
            spec="修复登录接口空用户名500",
            workdir=tmp_path,
            venv_python=venv_python,
            run_py_path=run_py_path,
        )
        # run.py 固定写入 src/data/，不受 workdir 影响
        data_dir = run_py_path.parent / "data" / "shared" / "tasks"
        state_files = list(data_dir.rglob("state.json"))
        assert len(state_files) > 0, \
            f"应生成 state.json，但 {data_dir} 中未找到。" \
            f" stdout: {result.stdout[:200]}"


# ========================================================================== #
# P0-CLI-06: 并发与稳定性
# ========================================================================== #

class TestConcurrencyAndStability:
    """P0-CLI-06: 并发与稳定性测试。"""

    def test_multiple_sequential_runs_stable(self, tmp_path):
        """连续多次 Mock 闭环应稳定通过。"""
        for i in range(3):
            loop = AgentTeamsLoop(
                task_id=f"e2e-stable-{i}",
                spec="修复登录接口空用户名500",
                workdir=tmp_path,
                mock=True,
            )
            state = asyncio.run(loop.run())
            assert state.state == State.RETROSPECT, f"第 {i+1} 次运行未到达 RETROSPECT"

    async def test_concurrent_mock_closures(self, tmp_path):
        """并发运行多个 Mock 闭环应互不干扰。"""
        async def run_one(idx: int) -> State:
            # 每个并发任务有独立 workdir
            subdir = tmp_path / f"concurrent-{idx}"
            subdir.mkdir(parents=True, exist_ok=True)
            loop = AgentTeamsLoop(
                task_id=f"e2e-concurrent-{idx}",
                spec=f"并发任务 {idx}: 修复问题",
                workdir=subdir,
                mock=True,
            )
            return await loop.run()

        tasks = [run_one(i) for i in range(3)]
        results = await asyncio.gather(*tasks)

        for i, state in enumerate(results):
            assert state.state == State.RETROSPECT, \
                f"并发任务 {i} 未到达 RETROSPECT，实际 {state.state.value}"

    def test_state_json_isolation(self, tmp_path):
        """不同任务的 state.json 应相互隔离。"""
        task_ids = []
        for i in range(3):
            tid = f"e2e-isolate-{i}"
            task_ids.append(tid)
            loop = AgentTeamsLoop(
                task_id=tid,
                spec=f"隔离任务 {i}",
                workdir=tmp_path,
                mock=True,
            )
            asyncio.run(loop.run())

        for tid in task_ids:
            state_json = tmp_path / "shared" / "tasks" / tid / "state.json"
            assert state_json.exists(), f"任务 {tid} 的 state.json 应存在"
            data = json.loads(state_json.read_text(encoding="utf-8"))
            assert data["task_id"] == tid
            assert data["state"] == "RETROSPECT"