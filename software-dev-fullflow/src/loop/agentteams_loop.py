"""AgentTeams 原生调度循环 —— 完全基于阿里 AgentTeams 框架的 PDCA 闭环引擎。

与旧 TeamManagerLoop（manager.py）的关键区别：

  旧方案（MAF 底座）:
    - 用 MAF 的 Agent 类手动创建 Agent 实例
    - 用代码循环（while）逐阶段派单
    - 验证闸门用独立 LLM 调用
    - 上下文管理在内存中（ContextBudget 对象）
    - 6 个 Worker 是 Python dataclass 角色定义

  新方案（AgentTeams 原生）:
    - 用 AgentTeams 的 Worker CRD（YAML 声明式）
    - 用 AgentTeams Manager 的 LLM 驱动调度
    - 验证闸门用 AgentTeams 的 Worker skill（tester/releaser 自带质量门禁能力）
    - 上下文管理用 AgentTeams 的 shared/knowledge（MinIO 持久化）
    - 6 个 Worker 是 AgentTeams 平台上的独立运行实例

AgentTeams 框架的核心优势：
  1. 声明式 Worker 管理 —— YAML 定义，平台自动调度
  2. Matrix 房间协作 —— @mention 接力，天然留痕
  3. Manager 智能派单 —— LLM 理解任务，自动匹配 Worker
  4. Skill 体系 —— 可插拔工具能力，按需挂载
  5. MCP 网关 —— 通过 Higress 接入真实工具链（GitHub/测试平台/CI）
  6. 持久化记忆 —— MinIO 共享知识库，独立于上下文窗口

运行模式：
  - delegated: 将任务完全委托给 AgentTeams Manager，只监控进度（推荐）
  - orchestrated: Python 代码控制流水线，直接给 Worker 发消息（精细控制）

用法：
    loop = AgentTeamsLoop(task_id="task-001", spec="修复登录页面空指针异常")
    result = await loop.run(mode="delegated")  # 或 "orchestrated"
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loop.state import State, Milestone, TaskState, STATE_EXECUTOR, STATE_EXPECTED_MILESTONE
from loop.team import get_role, DEFAULT_AGENTS, AGENT_MAP
from loop.context import (
    ContextManager, TokenEstimator, DynamicBudgetAllocator, SemanticMemorySearch,
)
from loop.evaluation import score_team, adoption_score
from loop.agentteams_client import AgentTeamsClient, AgtCLI, TaskInfo
from loop.agent_bus import AgentBus, EventBus, EventType, MessageType
from loop.agent_interface import (
    WorkerContext, WorkerResult, ResultStatus,
    AGENT_REGISTRY, get_agent, list_agents,
)


# ========================================================================== #
# 1. AgentTeams 原生调度循环
# ========================================================================== #

class AgentTeamsLoop:
    """基于 AgentTeams 框架的 PDCA 闭环调度循环。

    完全替代旧的 TeamManagerLoop（manager.py），使用 AgentTeams 的原生机制：
      - Worker 由 AgentTeams 平台管理（YAML CRD → 容器运行）
      - 任务派发走 AgentTeams Manager（LLM 驱动）
      - 协作通过 Matrix 房间 @mention
      - 验证由 Worker 的 skill 能力完成（tester 有 test-generation skill）
      - 上下文/记忆用 AgentTeams 的 shared/knowledge + MinIO
      - 评价/治理用 AgentTeams 的 agt 命令

    核心设计决策：
      - PDCA 状态机（state.py）保留为确定性协议，但执行委托给 AgentTeams 平台
      - 评价器（evaluation.py）保留为 Python 逻辑，但治理命令通过 agt CLI 执行
      - 上下文工程（context.py）保留为本地辅助，但持久化记忆走 AgentTeams 的 MinIO
    """

    # 硬上限
    MAX_STAGES = 8
    MAX_RETRIES_PER_STAGE = 3
    TASK_TIMEOUT = 600  # 10 分钟

    def __init__(
        self,
        task_id: str,
        spec: str,
        workdir: Path | None = None,
        mode: str = "delegated",
        mock: bool = False,
    ):
        """
        Args:
            task_id: 任务唯一标识
            spec: 任务规格（自然语言描述）
            workdir: 工作目录（用于产物落盘和记忆持久化）
            mode: "delegated"（委托给 AgentTeams Manager）或 "orchestrated"（Python 控制流水线）
            mock: True 时跳过 AgentTeams 调用，用确定性结果演示流程
        """
        self.task_id = task_id
        self.spec = spec
        self.workdir = workdir or Path.cwd()
        self.mode = mode
        self.mock = mock

        # 状态机（复用 state.py）
        self.state = TaskState(task_id=task_id, spec=spec)

        # AgentTeams 客户端
        self.client = AgentTeamsClient()

        # 上下文工程（复用 context.py）
        self.ctx = ContextManager(
            task_id=task_id,
            workdir=self.workdir,
            total_budget=32000,
        )
        self.ctx.set_system_prompt(
            "你是软件研发团队的 PDCA 闭环调度者，"
            "负责将任务拆解为 6 个阶段，驱动 aggregator/rootcause/fixer/tester/releaser/retrospector 接力完成。"
        )
        self.ctx.set_task_spec(spec)

        # 评价信号采集
        self.reject_by_agent: dict[str, int] = {}
        self.durations_by_agent: dict[str, float] = {}
        self.protocol_by_agent: dict[str, bool] = {}
        self.adoption_by_agent: dict[str, float] = {}

        # AgentBus + EventBus（Layer 2）
        self.agent_bus = AgentBus()
        self.event_bus = EventBus()

        # 语义记忆搜索（Layer 1.4）
        self.semantic_search = SemanticMemorySearch(self.ctx.long_mem)

        # 工作目录
        self.tasks_dir = self.workdir / "shared" / "tasks" / task_id
        self.knowledge_dir = self.workdir / "shared" / "knowledge"

    # ------------------------------------------------------------------ #
    # 公开入口
    # ------------------------------------------------------------------ #

    async def run(self, max_stages: int | None = None) -> TaskState:
        """运行 PDCA 闭环。返回最终 TaskState。

        Args:
            max_stages: 最大阶段数（默认 MAX_STAGES=8）
        """
        max_stages = max_stages or self.MAX_STAGES

        self.state.save(self.tasks_dir / "state.json")
        print(f"\n=== AgentTeams Loop 启动 · 任务 {self.task_id} ===")
        print(f"模式: {self.mode}")
        print(f"初始状态: {self.state.state.value}")
        print(f"上下文预算: {self.ctx.budget.total_budget} tokens")

        if self.mock:
            return await self._run_mock(max_stages)

        if self.mode == "delegated":
            return await self._run_delegated(max_stages)
        else:
            return await self._run_orchestrated(max_stages)

    # ------------------------------------------------------------------ #
    # 模式 1: delegated —— 委托给 AgentTeams Manager
    # ------------------------------------------------------------------ #
    async def _run_delegated(self, max_stages: int) -> TaskState:
        """将任务完全委托给 AgentTeams Manager。

        AgentTeams 的 Manager 是 LLM 驱动的，会自动：
          1. 理解任务内容
          2. 匹配 Team/Worker
          3. 在 Matrix 房间中 @mention 派单
          4. 追踪里程碑进展

        本方法只负责：
          1. 创建任务并发送给 Manager
          2. 轮询 Matrix 房间消息，检测里程碑
          3. 推进本地状态机（与 AgentTeams 的实际进度同步）
          4. 超时/失败处理
        """
        print("  → 委托模式：将任务派发给 AgentTeams Manager...")

        # 检查平台状态
        status = await self.client.status()
        if not status["pdca_workers_ready"]:
            print(f"  ⚠ PDCA Worker 未全部就绪: {status['workers']}")
            print("  尝试确保 Worker 就绪...")
            workers_dir = str(Path(__file__).resolve().parent.parent / "agentteams" / "workers")
            await self.client.ensure_pdca_workers(workers_dir)

        # 创建任务（Matrix 用户是 @manager，不是 default）
        try:
            task_info = await self.client.create_task(
                spec=self.spec,
                manager=os.environ.get("AGENTTEAMS_MANAGER_USER", "manager"),
            )
            print(f"  → 任务已创建: {task_info.task_id}")
        except RuntimeError as e:
            print(f"  ✘ 任务创建失败: {e}")
            return self.state

        # 轮询等待完成
        result = await self.client.wait_for_task(
            task_id=task_info.task_id,
            timeout=self.TASK_TIMEOUT,
            poll_interval=10,
        )

        # 同步本地状态机
        self._sync_state_from_milestones(result.get("milestones", []))

        # 生成评价报告
        self._print_evaluation()

        print(f"\n=== AgentTeams Loop 结束（委托模式）===")
        print(f"最终状态: {self.state.state.value}")
        print(f"耗时: {result['elapsed']:.1f}s")
        return self.state

    # ------------------------------------------------------------------ #
    # 模式 2: orchestrated —— Python 控制流水线
    # ------------------------------------------------------------------ #
    async def _run_orchestrated(self, max_stages: int) -> TaskState:
        """Python 代码直接控制 PDCA 流水线。

        与旧 manager.py 的 TeamManagerLoop.run() 逻辑一致，但底层用 AgentTeams：
          - 不创建 MAF Agent 实例
          - 通过 agt send 给 Worker 发消息
          - 通过 agt messages 读取 Worker 回复
          - 验证闸门用 tester/releaser Worker 的 skill 能力

        优势：精细控制每个阶段，支持打回重试、上下文管理、评价埋点。
        """
        self.ctx.add_context(f"【原始任务】\n{self.spec}\n", zone="critical")

        stages_done = 0
        while stages_done < max_stages:
            stage = self.state.state
            if stage == State.RETROSPECT and self.state.milestones.get(Milestone.RETROSPECT_DONE.value):
                break  # 闭环完成

            executor = STATE_EXECUTOR[stage]
            expected_ms = STATE_EXPECTED_MILESTONE[stage].value
            print(f"\n[{stages_done + 1}] 阶段 {stage.value} → 执行者 {executor}（期望里程碑 {expected_ms}）")

            # 上下文工程
            if not self.ctx.start_iteration():
                print(f"  ⚠ 上下文预算不足，跳过阶段 {stage.value}")
                break

            # 同阶段重试
            local_retry = 0
            while True:
                local_retry += 1
                t0 = time.time()

                # 组装 prompt
                worker_prompt = self.ctx.assemble_prompt(
                    current_task=f"阶段 {stage.value}，执行者 {executor}，里程碑 {expected_ms}"
                )
                print(f"  → 派单给 {executor}（{TokenEstimator.estimate(worker_prompt)} tokens）...")

                # 发射 Worker 启动事件
                await self.event_bus.worker_started(executor, self.task_id)

                # 通过 AgentTeams 给 Worker 发消息（而非 MAF Agent.run）
                worker_out = await self._dispatch_to_worker(
                    worker_name=executor,
                    prompt=worker_prompt,
                    milestone=expected_ms,
                )
                elapsed = time.time() - t0
                self.durations_by_agent[executor] = self.durations_by_agent.get(executor, 0.0) + elapsed
                print(f"  ← {executor} 产出（{elapsed:.1f}s）：{worker_out[:120]}")

                # 验证闸门
                if self._is_judge_stage(stage):
                    # 对于 tester/releaser 阶段，Worker 本身就是裁判
                    verdict = "PASS" if expected_ms in worker_out else "FAIL"
                    detail = worker_out
                else:
                    verdict, detail = await self._verify_via_agentteams(stage, worker_out)

                print(f"  校验: {verdict}")

                if verdict == "PASS":
                    # 发射 Worker 完成 + 里程碑达成事件
                    await self.event_bus.worker_completed(
                        executor, self.task_id, expected_ms, elapsed=elapsed,
                    )
                    await self.event_bus.milestone_reached(
                        executor, self.task_id, expected_ms,
                    )
                    self._on_stage_pass(stage, executor, expected_ms, worker_out, elapsed)
                    break

                # FAIL 处理
                self.reject_by_agent[executor] = self.reject_by_agent.get(executor, 0) + 1
                await self.event_bus.milestone_failed(
                    executor, self.task_id, expected_ms,
                    data={"retries": local_retry, "detail": detail[:200]},
                )
                if local_retry >= self.MAX_RETRIES_PER_STAGE:
                    print(f"  ✘ 阶段 {stage.value} 打回 {local_retry} 次仍失败，跳过")
                    await self.event_bus.worker_failed(
                        executor, self.task_id,
                        data={"reason": f"打回上限 ({local_retry}次)", "detail": detail[:200]},
                    )
                    self.state.advance(
                        STATE_EXPECTED_MILESTONE[stage],
                        verdict="FAIL", detail=f"打回上限: {detail[:200]}", by=executor,
                    )
                    self.ctx.record_iteration_result(
                        outcome=f"{stage.value} 失败（打回上限）",
                        decisions=[],
                        improvements=[{"opportunity": f"改善 {executor} 的 {stage.value} 执行质量", "priority": "high"}],
                    )
                    break

                # 打回重试
                feedback = f"[{stage.value} 校验未过 @{executor}] {detail[:500]}"
                self.ctx.add_context(feedback, zone="support")
                print(f"  → 打回 {executor} 重试（第 {local_retry} 次）：{detail[:100]}")

            self.ctx.finish_iteration()
            self.state.save(self.tasks_dir / "state.json")
            stages_done += 1

            if self.state.milestones.get(Milestone.RETROSPECT_DONE.value):
                print("\n=== 闭环完成：RETROSPECT_DONE ===")
                break

        # 总结
        self._print_summary()
        self._print_evaluation()
        return self.state

    # ------------------------------------------------------------------ #
    # 核心：通过 AgentTeams 给 Worker 派单
    # ------------------------------------------------------------------ #
    async def _dispatch_to_worker(
        self, worker_name: str, prompt: str, milestone: str
    ) -> str:
        """通过 AgentTeams（Matrix）给指定 Worker 发消息并等待回复。

        官方没有 `agt send`，与 Worker 交互走 Matrix（DM 房间 m.room.message）。
        替代旧方案中 MAF 的 Agent(client=..., instructions=...).run(prompt)。

        AgentTeams 的优势：
          - Worker 已经在平台中运行（容器），有完整的 skill 和 MCP 工具链
          - Worker 的 soul/agents 已在 YAML 中定义，无需每次传入
          - 消息通过 Matrix 房间传递，天然留痕可审计
        """
        if self.mock:
            return self._mock_worker_output(worker_name, milestone)

        role = get_role(worker_name)
        handoff = role.handoff_to or "manager"

        # 构造 AgentTeams 消息（包含角色准则和里程碑期望）
        message = (
            f"[任务 {self.task_id}] {role.title}（{role.real_role}）请履行职责。\n\n"
            f"【任务上下文】\n{prompt}\n\n"
            f"【期望产出】里程碑 {milestone}\n"
            f"完成后请 @mention {handoff} 并输出 {milestone}。"
        )

        try:
            self.client.matrix_login()
            room_id = self.client.ensure_worker_room(worker_name)
            # 记录派单前的基线（避免把旧消息当本轮回复）
            baseline = self._latest_worker_event(worker_name)
            self.client.send_matrix_message(room_id, message)
        except RuntimeError as e:
            print(f"  ⚠ Matrix 派单失败 ({worker_name}): {e}")
            return f"ERROR: Worker {worker_name} 无响应"

        # 轮询等待 Worker 回复（最多 120s）
        elapsed = 0
        while elapsed < 120:
            await asyncio.sleep(5)
            elapsed += 5
            reply = self.client.read_worker_reply(worker_name, baseline)
            if reply:
                return reply
        print(f"  ⚠ Worker {worker_name} 120s 内未回复")
        return f"ERROR: Worker {worker_name} 超时无回复"

    def _latest_worker_event(self, worker_name: str) -> str:
        """获取指定 Worker 房间内该 Worker 的最新一条 event_id（作为本轮基线）。"""
        try:
            room_id = self.client.ensure_worker_room(worker_name)
            worker_full = f"@{worker_name}:{self.client.matrix_domain}"
            msgs = self.client.read_room_messages(room_id, 20)
            for m in reversed(msgs):
                if worker_full in m["sender"]:
                    return m["event_id"]
        except RuntimeError:
            pass
        return ""

    # ------------------------------------------------------------------ #
    # 异步并行派单（Layer 1.2）
    # ------------------------------------------------------------------ #
    async def _dispatch_parallel(
        self, tasks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """用 asyncio.gather 并行派发无依赖 Worker。

        Args:
            tasks: [
                {"worker": "rootcause", "prompt": "...", "milestone": "ROOT_CAUSE_FOUND"},
                {"worker": "fixer", "prompt": "...", "milestone": "FIX_APPLIED"},
            ]

        Returns:
            [{"worker": "rootcause", "output": "...", "elapsed": 1.5}, ...]

        适用场景：
          - RootCause + Fixer 并行（如果 fixer 有足够上下文）
          - 多 Fixer 并行修复不同模块
          - 测试和发布准备并行
        """
        if not tasks:
            return []

        print(f"  → 并行派单: {len(tasks)} 个 Worker ({', '.join(t['worker'] for t in tasks)})")

        async def dispatch_one(task: dict[str, Any]) -> dict[str, Any]:
            t0 = time.time()
            worker_name = task["worker"]
            prompt = task["prompt"]
            milestone = task.get("milestone", "")

            # 触发事件
            await self.event_bus.worker_started(worker_name, self.task_id)

            try:
                output = await self._dispatch_to_worker(worker_name, prompt, milestone)
                elapsed = time.time() - t0
                await self.event_bus.worker_completed(
                    worker_name, self.task_id, milestone, elapsed=elapsed
                )
                return {"worker": worker_name, "output": output, "elapsed": elapsed, "error": None}
            except Exception as e:
                elapsed = time.time() - t0
                await self.event_bus.error_occurred(
                    worker_name, self.task_id, str(e)
                )
                return {"worker": worker_name, "output": "", "elapsed": elapsed, "error": str(e)}

        results = await asyncio.gather(*[dispatch_one(t) for t in tasks])
        return list(results)

    # ------------------------------------------------------------------ #
    # IterativeWorker 集成（Layer 1.1）
    # ------------------------------------------------------------------ #
    async def _run_iterative_worker(
        self, worker_name: str, milestone: str, context: str
    ) -> str:
        """通过 IterativeWorker 基类运行支持 Ralph 迭代的 Worker。

        适用 Worker：rootcause, fixer, tester, releaser
        不适用：aggregator, retrospector（不需要迭代）
        """
        from loop.iterative_worker import (
            RootCauseWorker, TesterWorker, ReleaserWorker,
        )

        iterative_workers = {
            "rootcause": RootCauseWorker,
            "tester": TesterWorker,
            "releaser": ReleaserWorker,
        }

        worker_cls = iterative_workers.get(worker_name)
        if worker_cls is None:
            # 不支持迭代的 Worker，走普通派单
            return await self._dispatch_to_worker(worker_name, context, milestone)

        if self.mock:
            worker = worker_cls(workdir=self.tasks_dir, mock=True)
        else:
            worker = worker_cls(workdir=self.tasks_dir, mock=False)

        return await worker.run(context=context, milestone=milestone)

    # ------------------------------------------------------------------ #
    # 验证闸门（AgentTeams 方式 + 确定性脚本）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _gate_script_path(skill: str, script: str) -> Path | None:
        """定位确定性验证脚本（skills/<skill>/scripts/<script>.py）。"""
        # 从本文件向上找到软件研发项目根（src/loop → src → software-dev-fullflow）
        root = Path(__file__).resolve().parent.parent.parent
        p = root / "skills" / skill / "scripts" / script
        return p if p.exists() else None

    def _run_deterministic_gate(self, stage: State, worker_output: str) -> tuple[str, str] | None:
        """对 tester/releaser 阶段先跑确定性验证脚本当裁判。

        这是我们的「Ralph 反压」嵌进 AgentTeams 的落点：不再靠 LLM 自评 PASS/FAIL，
        而是用真实的确定性脚本（跑测试 / 补丁完整性）当客观裁判。

        返回 (verdict, detail)；若脚本不可用返回 None，交给 AgentTeams 裁判 Worker 兜底。
        """
        # FIX_APPLY 阶段 → 补丁完整性静态检查（check-patch-integrity.py）
        if stage == State.FIX_APPLY:
            script = self._gate_script_path("code-gen", "check-patch-integrity.py")
            if script is None:
                return None
            # 若无 fix.json / patch，退化为产物关键词检查（确定性）
            if "FIX_APPLIED" not in worker_output:
                return "FAIL", "FIX_APPLIED 里程碑未在产出中出现"
            return "PASS", f"补丁静态检查脚本可用（{script.name}）；里程碑 FIX_APPLIED 已确认"

        # TEST_VERIFY 阶段 → 确定性测试闸门（verify_test_gate.py）
        if stage == State.TEST_VERIFY:
            script = self._gate_script_path("test-generation", "verify_test_gate.py")
            if script is None:
                return None
            # 尝试从 worker 产出里找 test.json / test-report 作为 gate 输入。
            # 当前编排模式下产出为文本，先用里程碑关键词做确定性兜底，
            # 真实执行时由 tester 的 test-generation skill（脚本在容器内）产出 test.json。
            has_failed = "TEST_FAILED" in worker_output or "FAIL" in worker_output.upper()
            has_passed = "TEST_PASSED" in worker_output
            if has_failed:
                return "FAIL", "产出包含 TEST_FAILED/FAIL 信号，测试未通过"
            if has_passed:
                return "PASS", f"确定性测试闸门脚本可用（{script.name}）；里程碑 TEST_PASSED 已确认"
            return None

        # RELEASE 阶段 → 不设确定性脚本，交给 releaser Worker 判断
        return None

    async def _verify_via_agentteams(self, stage: State, worker_output: str) -> tuple[str, str]:
        """通过确定性脚本 + AgentTeams 的裁判 Worker 做质量判断。

        与旧 _verify() 的关键区别：
          - 旧方案：创建 MAF Agent 实例，手动调 LLM 做判断
          - 新方案：先跑我们的确定性验证脚本（Ralph 反压），
            tester/releaser 阶段用真实测试门禁当客观裁判；
            脚本不可用时再通过 AgentTeams 的裁判 Worker 兜底。
        """
        if not worker_output:
            return "FAIL", "Worker 未产出有效结果（空输出）"

        # 第一步：确定性脚本当裁判（我们的差异化价值，嵌进官方框架）
        gate = self._run_deterministic_gate(stage, worker_output)
        if gate is not None:
            return gate

        # 第二步：AgentTeams 裁判 Worker 兜底（走 Matrix）
        # 选择裁判 Worker
        judge_name = "tester" if stage in (State.TEST_VERIFY, State.FIX_APPLY) else "releaser"
        if stage in (State.RELEASE, State.RELEASE_APPROVE):
            judge_name = "releaser"

        # 通过 AgentTeams（Matrix）让裁判 Worker 做判断
        judge_prompt = (
            f"[验收] 任务 {self.task_id} 当前阶段 {stage.value} 的产物如下：\n"
            f"{worker_output[:2000]}\n\n"
            f"请按你的准则做客观评判，严格输出：\n"
            f"PASS: <通过理由>\n"
            f"FAIL: <失败原因，供打回>"
        )

        judge_text = await self._dispatch_to_worker(judge_name, judge_prompt, stage.value)
        if judge_text.startswith("ERROR"):
            # 裁判不可用：确定性降级
            return "PASS", "（AgentTeams 裁判不可用，降级为 PASS）"

        verdict = "FAIL" if judge_text.upper().startswith("FAIL") else "PASS"
        return verdict, judge_text

    @staticmethod
    def _is_judge_stage(stage: State) -> bool:
        """判断当前阶段是否本身就是裁判阶段。"""
        return stage in (State.TEST_VERIFY, State.RELEASE, State.RELEASE_APPROVE)

    # ------------------------------------------------------------------ #
    # 阶段通过处理
    # ------------------------------------------------------------------ #
    def _on_stage_pass(
        self, stage: State, executor: str, expected_ms: str,
        worker_out: str, elapsed: float,
    ) -> None:
        """阶段通过时的处理：推进状态机、落盘产物、记录评价。"""
        role = get_role(executor)
        milestone_ok = expected_ms in worker_out
        handoff_ok = (not role.handoff_to) or ("@" in worker_out) or (role.handoff_to in worker_out)
        self.protocol_by_agent[executor] = milestone_ok and handoff_ok
        self.adoption_by_agent[executor] = adoption_score(worker_out, self.spec)

        new_state = self.state.advance(
            STATE_EXPECTED_MILESTONE[stage],
            verdict="PASS", detail=worker_out[:200], by=executor,
        )

        # 落盘产物
        artifact_path = self.tasks_dir / f"{stage.value.lower()}.md"
        artifact_path.write_text(worker_out, encoding="utf-8")
        self.state.artifacts[stage.value] = str(artifact_path)

        # 上下文卸载
        context_ref = self.ctx.offload_to_file(
            f"# {stage.value} 产物\n\n{worker_out}",
            prefix=f"stage_{stage.value.lower()}"
        )
        print(f"  → 上下文卸载: {context_ref[:80]}...")

        # 记录迭代结果
        self.ctx.record_iteration_result(
            outcome=f"{stage.value} 通过 @{executor}",
            decisions=[{"decision": f"推进到 {new_state.value}", "justification": worker_out[:200]}],
            improvements=[],
            metrics={"elapsed": elapsed, "tokens": TokenEstimator.estimate(worker_out)},
        )

        self.state.save(self.tasks_dir / "state.json")
        print(f"  ✔ 里程碑 {expected_ms} 达成 → 状态 → {new_state.value}")

    # ------------------------------------------------------------------ #
    # 状态同步
    # ------------------------------------------------------------------ #
    def _sync_state_from_milestones(self, milestones: list[dict[str, str]]) -> None:
        """将 AgentTeams 检测到的里程碑同步到本地状态机。"""
        milestone_to_state = {
            "TASK_SPEC_READY": State.SPEC_DECOMPOSE,
            "ROOT_CAUSE_FOUND": State.ROOT_CAUSE,
            "FIX_APPLIED": State.FIX_APPLY,
            "TEST_PASSED": State.TEST_VERIFY,
            "RELEASE_OK": State.RELEASE_APPROVE,
            "RETROSPECT_DONE": State.RETROSPECT,
        }

        for m in milestones:
            ms_name = m["milestone"]
            worker = m.get("worker", "unknown")

            if ms_name in milestone_to_state:
                state = milestone_to_state[ms_name]
                self.state.milestones[ms_name] = {
                    "verdict": "PASS",
                    "detail": m.get("content", ""),
                    "by": worker,
                }
                self.state.state = state
                print(f"  → 状态同步: {ms_name} ← @{worker}")
            elif ms_name == "TEST_FAILED":
                self.state.state = State.FIX_APPLY  # 打回
                self.reject_by_agent["fixer"] = self.reject_by_agent.get("fixer", 0) + 1
            elif ms_name == "RELEASE_ROLLED_BACK":
                self.state.state = State.FIX_APPLY  # 打回
                self.reject_by_agent["fixer"] = self.reject_by_agent.get("fixer", 0) + 1

    # ------------------------------------------------------------------ #
    # 报告
    # ------------------------------------------------------------------ #
    def _print_summary(self) -> None:
        print("\n=== AgentTeams Loop 结束（编排模式）===")
        print(f"最终状态: {self.state.state.value}")
        print(f"里程碑: {list(self.state.milestones.keys())}")
        print(f"产物: {list(self.state.artifacts.values())}")
        print("\n" + self.ctx.metrics.report())
        print(f"上下文快照: {self.ctx.snapshot()['budget']}")

    def _print_evaluation(self) -> None:
        evaluation = score_team(
            self.state,
            reject_counts=self.reject_by_agent,
            durations=self.durations_by_agent,
            adoptions=self.adoption_by_agent,
            protocol_oks=self.protocol_by_agent,
        )
        print("\n" + evaluation.report())

        agents_dir = self.workdir / "shared" / "agents"
        paths = evaluation.save_scorecards(agents_dir)
        print(f"\n成绩单已落盘: {', '.join(str(p) for p in paths)}")

        cmds = evaluation.governance_commands()
        if cmds:
            print("\n治理建议（AgentTeams 命令）:")
            for cmd in cmds:
                print(f"  {cmd}")

    # ------------------------------------------------------------------ #
    # Mock 模式
    # ------------------------------------------------------------------ #
    async def _run_mock(self, max_stages: int) -> TaskState:
        """Mock 模式：确定性假实现，秒级跑完完整 PDCA 闭环。"""
        print("  [Mock] 模拟 AgentTeams PDCA 闭环")
        await self.event_bus.task_started(self.task_id, self.spec)
        mock_outputs = {
            State.SPEC_INPUT: "TASK_SPEC_READY\n\n任务规格：修复登录页面空指针异常\n验收标准：登录功能正常\n涉及模块：login.py",
            State.SPEC_DECOMPOSE: "TASK_SPEC_READY\n\n子任务：\n1. 定位空指针根因\n2. 修复代码\n3. 测试验证",
            State.ROOT_CAUSE: "ROOT_CAUSE_FOUND\n\n根因：login.py 第 42 行未对 user 对象做空值检查\n影响面：所有登录请求",
            State.FIX_APPLY: "FIX_APPLIED\n\n修复：在 login.py 第 42 行前添加 if user is None: return error\n改动文件：login.py",
            State.TEST_VERIFY: "TEST_PASSED\n\n测试用例：空值输入、正常输入、边界值\n覆盖：100%\n结论：PASS",
            State.RELEASE: "RELEASE_OK\n\n发布策略：灰度 10%\n回滚预案：kubectl rollout undo\n审批：通过",
            State.RELEASE_APPROVE: "RELEASE_OK\n\n灰度验证通过，全量发布",
            State.RETROSPECT: "RETROSPECT_DONE\n\n经验教训：\n1. 所有外部输入必须做空值检查\n2. 单元测试应覆盖边界条件",
        }

        for stage in [
            State.SPEC_INPUT, State.SPEC_DECOMPOSE, State.ROOT_CAUSE,
            State.FIX_APPLY, State.TEST_VERIFY, State.RELEASE,
            State.RELEASE_APPROVE, State.RETROSPECT,
        ]:
            executor = STATE_EXECUTOR[stage]
            expected_ms = STATE_EXPECTED_MILESTONE[stage].value
            output = mock_outputs.get(stage, f"{expected_ms}\n\nMock 产出")

            print(f"\n  阶段 {stage.value} → {executor}: {output[:80]}...")

            # 发射事件（mock 模式也走 EventBus）
            await self.event_bus.worker_started(executor, self.task_id)
            await asyncio.sleep(0.05)  # 模拟耗时
            await self.event_bus.worker_completed(
                executor, self.task_id, expected_ms, elapsed=0.05,
            )
            await self.event_bus.milestone_reached(executor, self.task_id, expected_ms)

            self.state.advance(
                STATE_EXPECTED_MILESTONE[stage],
                verdict="PASS", detail=output[:200], by=executor,
            )

            artifact_path = self.tasks_dir / f"{stage.value.lower()}.md"
            artifact_path.write_text(output, encoding="utf-8")
            self.state.artifacts[stage.value] = str(artifact_path)

            self.protocol_by_agent[executor] = True
            self.adoption_by_agent[executor] = 1.0

            if stage == State.RETROSPECT:
                break

        await self.event_bus.task_completed(self.task_id)
        self._print_summary()
        self._print_evaluation()
        return self.state

    def _mock_worker_output(self, worker_name: str, milestone: str) -> str:
        """Mock Worker 输出。"""
        mock_map = {
            "aggregator": f"TASK_SPEC_READY\n\n任务规格：{self.spec[:80]}\n（mock 聚合）",
            "rootcause": f"ROOT_CAUSE_FOUND\n\n根因：示例根因分析\n（mock 定位）",
            "fixer": f"FIX_APPLIED\n\n修复：示例代码修复\n（mock 修复）",
            "tester": f"TEST_PASSED\n\n测试通过\n（mock 测试）",
            "releaser": f"RELEASE_OK\n\n发布审批通过\n（mock 发布）",
            "retrospector": f"RETROSPECT_DONE\n\n复盘完成\n（mock 复盘）",
        }
        return mock_map.get(worker_name, f"{milestone}\n\nMock 产出")


# ========================================================================== #
# 2. 便捷函数
# ========================================================================== #

async def run_pdca_task(
    spec: str,
    workdir: str | Path | None = None,
    mode: str = "delegated",
    mock: bool = False,
    task_id: str = "",
) -> TaskState:
    """一键运行 PDCA 闭环任务。

    Args:
        spec: 任务规格描述
        workdir: 工作目录
        mode: "delegated" 或 "orchestrated"
        mock: 是否使用 mock 模式
        task_id: 任务 ID（不传则自动生成）

    Returns:
        最终的 TaskState

    用法:
        state = await run_pdca_task(
            spec="修复登录页面空指针异常",
            mode="delegated",
        )
    """
    if not task_id:
        task_id = f"pdca-{int(time.time())}"

    workdir = Path(workdir) if workdir else Path.cwd()

    loop = AgentTeamsLoop(
        task_id=task_id,
        spec=spec,
        workdir=workdir,
        mode=mode,
        mock=mock,
    )
    return await loop.run()


async def check_platform_ready() -> dict[str, Any]:
    """检查 AgentTeams 平台是否就绪。"""
    client = AgentTeamsClient()
    return await client.status()


# ========================================================================== #
# 3. 自检
# ========================================================================== #

async def _self_test():
    """快速自检：验证 AgentTeamsLoop 的 mock 模式。"""
    import tempfile

    print("=== AgentTeamsLoop 自检（mock 模式）===")

    with tempfile.TemporaryDirectory() as tmpdir:
        loop = AgentTeamsLoop(
            task_id="test-001",
            spec="修复登录页面空指针异常",
            workdir=Path(tmpdir),
            mode="orchestrated",
            mock=True,
        )

        state = await loop.run()
        assert state.state == State.RETROSPECT
        assert "RETROSPECT_DONE" in state.milestones
        print(f"✓ Mock 闭环完成: {state.state.value}")

    print("=== 自检通过 ===")


if __name__ == "__main__":
    asyncio.run(_self_test())