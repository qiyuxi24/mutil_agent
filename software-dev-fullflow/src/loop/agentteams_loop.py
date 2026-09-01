"""AgentTeams 客户端 —— 任务提交 + 进度监控 + 结果展示。

本模块是 AgentTeams 平台的 **Python 客户端**，不再实现调度逻辑。
AgentTeams 平台（K8s 原生多 Agent 协作平台）已经提供了完整的：
  - Manager 智能派单（LLM 驱动）
  - Worker 生命周期管理（YAML CRD → 容器运行）
  - Matrix 房间协作（@mention 接力，天然留痕）
  - Skill 体系 + MCP 网关（Higress 接入真实工具链）
  - MinIO 共享存储（持久化记忆，独立于上下文窗口）

本模块的职责：
  1. 接收用户任务输入
  2. 提交任务给 AgentTeams Manager
  3. 监控 Matrix 房间中的里程碑进展
  4. 同步本地状态机（观测层，非控制层）
  5. 展示结果 + 生成评价报告

架构原则：
  - Python 代码是"客户端"，不是"调度引擎"
  - 调度逻辑由 AgentTeams 平台原生提供
  - 本地状态机仅用于观测和展示，不干预 AgentTeams 的调度决策

用法：
    loop = AgentTeamsLoop(task_id="task-001", spec="修复登录页面空指针异常")
    result = await loop.run()
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 允许直接运行本文件做自检（python src/loop/agentteams_loop.py）：把 src/ 加入 sys.path，
# 使 `from loop.xxx import` 绝对导入（项目统一约定）在独立运行时也能解析。
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loop.state import State, Milestone, TaskState, STATE_EXECUTOR, STATE_EXPECTED_MILESTONE
from loop.context import ContextManager, SemanticMemorySearch, AgentMemoryRegistry, AgentMemoryEntry
from loop.evaluation import score_team
from loop.knowledge_tracker import UsageTracker
from loop.agentteams_client import AgentTeamsClient
from loop.agent_bus import AgentBus, EventBus
from loop.audit_logger import AuditLogger
from loop.approval import ApprovalManager
from loop.config import load_dotenv  # noqa: F401

# 统一配置：注入根目录 .env（幂等），使 MAX_DELEGATE_ROUNDS / APPROVAL_* 等可被覆盖。
load_dotenv()


# ========================================================================== #
# AgentTeams 客户端
# ========================================================================== #

class AgentTeamsLoop:
    """AgentTeams 平台的 Python 客户端。

    职责边界：
      - ✅ 提交任务给 AgentTeams Manager
      - ✅ 监控 Matrix 房间中的里程碑进展
      - ✅ 同步本地状态机（观测层）
      - ✅ 生成评价报告
      - ❌ 不实现 Worker 调度（由 AgentTeams Manager 负责）
      - ❌ 不实现验证闸门（由 AgentTeams Worker skill 负责）
      - ❌ 不实现上下文管理（由 AgentTeams MinIO 负责）
    """

    TASK_TIMEOUT = 3600  # 每轮增量等待上限（1 小时），超时视为 checkpoint 边界而非失败
    MAX_DELEGATE_ROUNDS = 6  # GAP-25: 最大续跑轮次（总预算 6h，防无限循环），可用环境变量覆盖
    MAX_DELEGATE_ROUNDS_ENV = "MAX_DELEGATE_ROUNDS"

    def __init__(
        self,
        task_id: str,
        spec: str,
        workdir: Path | None = None,
        mock: bool = False,
    ):
        """
        Args:
            task_id: 任务唯一标识
            spec: 任务规格（自然语言描述）
            workdir: 工作目录（用于产物落盘）
            mock: True 时跳过 AgentTeams 调用，用确定性结果演示流程
        """
        self.task_id = task_id
        self.spec = spec
        self.workdir = workdir or Path.cwd()
        self.mock = mock

        # 本地状态机（观测层，同步自 AgentTeams 平台的 Matrix 消息）
        self.state = TaskState(task_id=task_id, spec=spec)

        # AgentTeams 平台客户端
        #   GAP-25: checkpoint_dir 显式对齐 workdir（默认是 cwd/shared/checkpoints），
        #   跨进程续跑时只要 workdir 一致，断点 checkpoint 就一定可恢复。
        self.client = AgentTeamsClient(
            checkpoint_dir=self.workdir / "shared" / "checkpoints",
        )

        # ---- GAP-13: 观测组件（Context/记忆/语义搜索）延迟初始化 ----
        #   委托模式（delegated）下：AgentTeams 平台用 MinIO 管理共享状态 + Matrix 留痕，
        #   本地 ContextManager/SemanticMemorySearch/AgentMemories 没有真实数据流，
        #   初始化只会白白创建目录/分配对象。因此：
        #     - mock=True  → 立即初始化（_run_mock 路径真实消费这些组件）
        #     - mock=False → 先置 None，未来接入真实 Matrix→本地数据流时再懒加载
        self.ctx: ContextManager | None = None
        self.semantic_search: SemanticMemorySearch | None = None
        # 统一记忆注册表（AgentMemoryRegistry）—— 通用可复用记忆系统
        self.agent_memories: AgentMemoryRegistry | None = None
        # 知识/Skill 复用追踪器（UsageTracker）—— 统计知识使用频率，供成长分治理
        self.usage_tracker = UsageTracker(self.workdir / "shared" / "stats")
        if mock:
            self._ensure_local_contexts()

        # 评价信号采集（委托模式也需要，从 Matrix 消息里提取）
        self.reject_by_agent: dict[str, int] = {}
        self.durations_by_agent: dict[str, float] = {}
        self.protocol_by_agent: dict[str, bool] = {}
        self.adoption_by_agent: dict[str, float] = {}

        # 事件总线（观测层）
        self.agent_bus = AgentBus()
        self.event_bus = EventBus()

        # 工作目录
        self.tasks_dir = self.workdir / "shared" / "tasks" / task_id
        self.knowledge_dir = self.workdir / "shared" / "knowledge"

        # GAP-25: 平台任务委托记录（task_id 持久化，跨进程续跑依据）。
        #   记录 本地 task_id ↔ 平台 platform_task_id 映射 + 运行状态（running/completed）。
        #   下次以同一 task_id 启动时，若记录为 running，则「resume forward」复用同一平台任务，
        #   而非重新 create_task（参考 ARIS resumable-runs.md 的 run_id 持久化 + 前向恢复）。
        self.delegation_file = self.tasks_dir / "delegation.json"

        # 结构化审计日志（可观测 / 可审计，委托模式也需要）
        self.audit = AuditLogger(self.workdir / "shared" / "audit")

        # 审批管理器（人工审批留痕闭环 + TTL 超时兜底）
        #   TTL 默认 60s，可用环境变量 APPROVAL_TTL_SECS 覆盖（<=0 表示不超时仅人工审批）
        approval_ttl = int(os.environ.get("APPROVAL_TTL_SECS", ApprovalManager.DEFAULT_TTL_SECS))
        self.approval = ApprovalManager(
            event_bus=self.event_bus,
            audit=self.audit,
            ttl_secs=approval_ttl,
        )

    def _ensure_local_contexts(self) -> None:
        """GAP-13: 懒加载本地上下文工程组件（只在 mock 模式下调用）。"""
        if self.ctx is not None:
            return
        self.ctx = ContextManager(
            task_id=self.task_id,
            workdir=self.workdir,
            total_budget=32000,
        )
        self.ctx.set_system_prompt(
            "你是软件研发团队的 Leader（固定编排者），"
            "负责从一套完整班子中按阶段挑选员工参与，"
            "驱动 leader/aggregator/rootcause/frontend/backend/fixer/tester/releaser/retrospector 接力完成研发闭环。"
        )
        self.ctx.set_task_spec(self.spec)
        # 通过 ContextManager 门面创建语义搜索器（不再直接访问 ctx.long_mem）
        self.semantic_search = self.ctx.create_semantic_searcher()
        # 按 Agent 维度的独立记忆
        self._init_agent_memories()

    # ------------------------------------------------------------------ #
    # 公开入口
    # ------------------------------------------------------------------ #

    async def run(self) -> TaskState:
        """提交任务给 AgentTeams Manager，监控进度，返回最终状态。"""
        self.state.save(self.tasks_dir / "state.json")
        print(f"\n=== AgentTeams 客户端启动 · 任务 {self.task_id} ===")
        print(f"初始状态: {self.state.state.value}")

        # 启动审批管理器的后台超时扫描（TTL 超时自动驳回，避免演示卡死在审批）
        await self.approval.start()
        try:
            if self.mock:
                result = await self._run_mock()
            else:
                result = await self._run_delegated()
            # 无论 mock / delegated，结束都把最终状态机落盘（观测层证据持久化，
            # 此前 state.json 只保存了初始状态，导致闭环结束后 state.json 仍停在 SPEC_INPUT）
            self.state.save(self.tasks_dir / "state.json")
            return result
        finally:
            # 停止审批后台扫描
            await self.approval.stop()
            # 关闭审计日志文件句柄（避免 Windows 下临时目录清理失败）
            self.audit.close()
            # 落盘并关闭知识/Skill 复用追踪器（确保使用频率统计不丢）
            self.usage_tracker.shutdown()

    # ------------------------------------------------------------------ #
    # GAP-25: 平台任务委托记录持久化（跨进程断点续跑）
    # ------------------------------------------------------------------ #
    def _load_delegation(self) -> dict[str, Any] | None:
        """读取持久化的平台任务委托记录。

        对应 resumable-runs.md 的 run_id 持久化：记录 本地 task_id ↔ 平台 platform_task_id，
        使「同一任务跨进程续跑」成为可能（进程 B 读到进程 A 留下的委托，复用同一平台任务）。
        读取失败（半写/损坏）时返回 None，走新建任务路径，不阻塞。
        """
        if not self.delegation_file.exists():
            return None
        try:
            return json.loads(self.delegation_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return None

    def _save_delegation(self, platform_task_id: str, status: str = "running") -> None:
        """持久化平台任务委托记录。

        采用「临时文件 + os.replace」原子替换，符合 resumable-runs.md 的单 writer 契约
        （load-modify-save + 原子替换，防止并发 resumer 读到半写 JSON 而误判）。
        """
        self.delegation_file.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        prev = self._load_delegation()
        data = {
            "task_id": self.task_id,
            "platform_task_id": platform_task_id,
            "spec": self.spec,
            "created_at": (prev or {}).get("created_at", now),  # 保留首次创建时间
            "updated_at": now,
            "status": status,  # running | completed
        }
        tmp = self.delegation_file.with_name(self.delegation_file.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.delegation_file)

    def _delegation_resume_task_id(self) -> str | None:
        """若存在「进行中」的委托记录，返回可续跑的平台任务 ID；否则 None。

        Resume 语义（resumable-runs.md：resume 不是重新打开 id，而是向前解析到可信进度落点）：
          - status == "running"  → 复用同一平台任务，从断点继续轮询
          - status == "completed" 或记录不存在 → 终态，重新 create_task
        """
        delegation = self._load_delegation()
        if not delegation:
            return None
        if delegation.get("status") == "running":
            return delegation.get("platform_task_id")
        return None

    # ------------------------------------------------------------------ #
    # 委托模式：任务完全交给 AgentTeams Manager
    # ------------------------------------------------------------------ #
    async def _run_delegated(self) -> TaskState:
        """将任务提交给 AgentTeams Manager，轮询等待完成。

        AgentTeams 的 Manager 是 LLM 驱动的，会自动：
          1. 理解任务内容
          2. 匹配 Team/Worker
          3. 在 Matrix 房间中 @mention 派单
          4. 追踪里程碑进展

        本方法（Python 客户端）只负责：
          1. 提交任务给 Manager
          2. 轮询 Matrix 房间消息，检测里程碑
          3. 同步本地状态机（观测层）
          4. 超时/失败处理（GAP-25: 超时后接续轮询，不放弃）
          5. 生成评价报告

        GAP-04 降级策略：
          委托模式遇到平台不可用时，自动 fallback 到 mock 模式，
          保证演示（"闭环真能跑"卖点）在任何环境下都不翻车。

        GAP-25 断点续跑：
          - wait_for_task 超时返回 timeout 时，循环接续下一轮（client 已落 checkpoint，
            下一轮自动从断点恢复里程碑与累计耗时），而不是一次性放弃
          - platform_task_id 持久化到 delegation.json，跨进程以同一 task_id 重启时
            「resume forward」复用同一平台任务，不重复创建
        """
        print("  → 提交任务给 AgentTeams Manager...")

        # GAP-04: 委托模式降级策略 —— 先探活，平台不可用直接降级到 mock
        try:
            platform_ok = await self.client.ping()
        except Exception as e:  # noqa: BLE001 - 探活失败（docker 子进程/超时等）不应中断演示
            print(f"  ⚠ 平台探活异常: {e}")
            platform_ok = False

        if not platform_ok:
            print("\n  ⚠ AgentTeams 平台不可用，自动切换 Mock 模式演示完整闭环。")
            print("    （委托模式 → mock 降级：确保演示不翻车）")
            self.audit.log(self.task_id, "manager", "state", "degrade_to_mock",
                           result="OK", detail={"reason": "platform_unavailable"})
            return await self._run_mock()

        # 检查平台状态
        status = await self.client.status()
        if not status["pdca_workers_ready"]:
            print(f"  ⚠ PDCA Worker 未全部就绪: {status['workers']}")
            print("  尝试确保 Worker 就绪...")
            workers_dir = str(Path(__file__).resolve().parent.parent / "agentteams" / "workers")
            await self.client.ensure_pdca_workers(workers_dir)

        # GAP-25: 跨进程断点续跑 —— 已有「进行中」的委托记录时，直接复用平台任务（resume forward）
        platform_task_id = self._delegation_resume_task_id()
        if platform_task_id:
            print(f"  ♻ 检测到持久化的平台任务 {platform_task_id}，从断点续跑（resume forward）")

        # 创建任务并发送给 Manager（仅在无续跑任务时）
        if platform_task_id is None:
            try:
                task_info = await self.client.create_task(
                    spec=self.spec,
                    manager=os.environ.get("AGENTTEAMS_MANAGER_USER", "manager"),
                )
                platform_task_id = task_info.task_id
                # 立刻落盘委托记录：此后即使本轮超时/进程崩溃退出，跨进程也能接续同一平台任务
                self._save_delegation(platform_task_id, status="running")
                print(f"  → 任务已创建: {platform_task_id}")
                self.audit.log(self.task_id, "manager", "state", "create_task",
                               result="OK", detail={"task_id": platform_task_id})
            except RuntimeError as e:
                # GAP-04: 任务创建失败（Matrix 登录/房间不可达等）同样降级到 mock
                print(f"  ✘ 任务提交失败: {e}")
                print("  ⚠ AgentTeams 平台不可用，自动切换 Mock 模式演示完整闭环。")
                self.audit.log_error(self.task_id, "manager", "create_task", str(e))
                self.audit.log(self.task_id, "manager", "state", "degrade_to_mock",
                               result="OK", detail={"reason": "create_task_failed"})
                return await self._run_mock()

        # GAP-25: 循环接续轮询 —— 超时不是失败，是 checkpoint 边界。
        #   client 每轮 wait_for_task 都落盘 checkpoint（status=timeout），下一轮自动恢复里程碑与累计耗时。
        #   对应长时程多智能体教程的 outer-loop time budget：单步超时由编排器强制接续，直到完成或预算耗尽。
        max_rounds = int(os.environ.get(self.MAX_DELEGATE_ROUNDS_ENV, self.MAX_DELEGATE_ROUNDS))
        result: dict[str, Any] = {"status": "timeout", "milestones": [], "elapsed": 0.0}
        for round_no in range(1, max_rounds + 1):
            result = await self.client.wait_for_task(
                task_id=platform_task_id,
                timeout=self.TASK_TIMEOUT,
                poll_interval=10,
            )
            self.audit.log(self.task_id, "manager", "state", f"wait_task#{round_no}",
                           result=result.get("status", "done"),
                           detail={"elapsed_s": round(result.get("elapsed", 0), 1),
                                   "milestones": [m["milestone"] for m in result.get("milestones", [])]})

            # 同步本地状态机（观测层）
            self._sync_state_from_milestones(result.get("milestones", []))

            if result.get("status") == "completed":
                # 任务完成 → 委托记录标记终态（保留供审计；后续以同一 task_id 启动会重新建任务）
                self._save_delegation(platform_task_id, status="completed")
                break

            # timeout → 接续下一轮
            done_ms = [m["milestone"] for m in result.get("milestones", [])]
            print(f"  ⏳ 第 {round_no}/{max_rounds} 轮等待超时（已累计 {result.get('elapsed', 0):.0f}s），"
                  f"已达成 {len(done_ms)} 个里程碑: {', '.join(sorted(set(done_ms))) or '—'}")
            if round_no < max_rounds:
                print(f"     → 从断点继续接续轮询（第 {round_no + 1} 轮）...")
        else:
            # for-else：达到最大轮次仍未完成（从未 break），按当前进度收尾，不无限循环
            print(f"  ⚠ 达到最大续跑轮次（{max_rounds} × {self.TASK_TIMEOUT}s），任务仍未完成，按当前进度收尾。")
            self.audit.log(self.task_id, "manager", "state", "max_rounds_reached",
                           result="timeout", detail={"rounds": max_rounds})

        # 生成评价报告
        self._print_evaluation()

        print(f"\n=== AgentTeams 客户端结束 ===")
        print(f"最终状态: {self.state.state.value}")
        print(f"耗时: {result.get('elapsed', 0):.1f}s")
        return self.state

    # ------------------------------------------------------------------ #
    # 状态同步：从 Matrix 消息中提取里程碑，同步到本地状态机
    # ------------------------------------------------------------------ #
    def _sync_state_from_milestones(self, milestones: list[dict[str, str]]) -> None:
        """将 AgentTeams Matrix 房间中检测到的里程碑同步到本地状态机。

        这是观测层：本地状态机镜像 AgentTeams 平台的实际进度，
        不做调度决策，只用于展示和评价。
        """
        milestone_to_state = {
            "TASK_SPEC_READY": State.SPEC_DECOMPOSE,
            "ROOT_CAUSE_FOUND": State.ROOT_CAUSE,
            "FIX_APPLIED": State.FIX_APPLY,
            "SITE_READY": State.FIX_APPLY,       # 前端完成 → 进入编码/验证
            "BACKEND_READY": State.FIX_APPLY,    # 后端完成 → 进入编码/验证
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
                self.audit.log_milestone(self.task_id, worker, ms_name,
                                         state=state.value, result="PASS")
            elif ms_name == "TEST_FAILED":
                self.state.state = State.FIX_APPLY
                # 打回对应编码员工（fixer/frontend/backend 都可能被测试打回）
                self.reject_by_agent[worker] = self.reject_by_agent.get(worker, 0) + 1
                self.audit.log_milestone(self.task_id, worker, ms_name,
                                         state="FIX_APPLY", result="FAIL")
            elif ms_name == "RELEASE_ROLLED_BACK":
                self.state.state = State.FIX_APPLY
                self.reject_by_agent[worker] = self.reject_by_agent.get(worker, 0) + 1
                self.audit.log_milestone(self.task_id, worker, ms_name,
                                         state="FIX_APPLY", result="FAIL")

    # ------------------------------------------------------------------ #
    # 报告
    # ------------------------------------------------------------------ #
    def _print_summary(self) -> None:
        print("\n=== AgentTeams 任务完成 ===")
        print(f"最终状态: {self.state.state.value}")
        print(f"里程碑: {list(self.state.milestones.keys())}")
        print(f"产物: {list(self.state.artifacts.values())}")
        # GAP-13: 委托模式下 ctx 为 None，跳过本地上下文指标（真实指标在 AgentTeams 平台侧）
        if self.ctx is not None:
            print("\n" + self.ctx.metrics_report())
            print(f"上下文快照: {self.ctx.budget_snapshot()}")
        else:
            print("（委托模式：上下文预算/性能指标由 AgentTeams 平台维护）")

    def _print_evaluation(self) -> None:
        # 成长分 = 各 Agent 沉淀的知识被跨任务 RAG 检索命中的总次数（UsageTracker 采集）
        # 由 knowledge_tracker 提供，对齐 KPI-BENCHMARK §3.4 成长分公式。
        # 从已记录的里程碑中提取参与 Agent，逐个查成长分。
        self.usage_tracker.flush()
        growth_scores: dict[str, float] = {}
        for ms in (self.state.milestones or {}).values():
            by = ms.get("by")
            if by and by not in growth_scores:
                growth_scores[by] = self.usage_tracker.get_agent_growth_score(by)

        evaluation = score_team(
            self.state,
            reject_counts=self.reject_by_agent,
            durations=self.durations_by_agent,
            adoptions=self.adoption_by_agent,
            protocol_oks=self.protocol_by_agent,
            growth_scores=growth_scores,
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
    # Agent 独立记忆
    # ------------------------------------------------------------------ #

    def _init_agent_memories(self) -> None:
        """初始化所有 Agent 的统一记忆注册表（一套完整班子）。"""
        agent_names = [
            "leader", "aggregator", "rootcause",
            "frontend", "backend", "fixer",
            "tester", "releaser", "retrospector",
            "doc-manager", "coordinator",
        ]
        self.agent_memories = AgentMemoryRegistry(
            storage_dir=self.workdir / "shared",
            agent_names=agent_names,
        )

    def record_agent_iteration(self, agent_name: str, phase: str, outcome: str,
                               mistakes: list[str] | None = None,
                               fixes: list[str] | None = None,
                               patterns: list[str] | None = None,
                               retry_count: int = 0) -> None:
        """记录一次 Agent 迭代结果到该 Agent 的统一记忆注册表。"""
        # GAP-13: 委托模式下 agent_memories / ctx 未初始化，直接跳过（记忆由 AgentTeams 平台维护）
        if self.ctx is None or not self.agent_memories:
            return
        if not self.agent_memories.has(agent_name):
            return
        mem = self.agent_memories.get(agent_name)
        entry = AgentMemoryEntry(
            task_id=self.task_id,
            iteration=self.ctx.current_iteration(),
            phase=phase,
            outcome=outcome,
            mistakes=mistakes or [],
            fixes=fixes or [],
            patterns=patterns or [],
            retry_count=retry_count,
        )
        mem.record_iteration(entry)

    def consolidate_all_agent_memories(self) -> dict[str, int]:
        """将所有 Agent 的近期迭代记录沉淀为长期记忆。"""
        # GAP-13: 委托模式下 agent_memories 为空，直接跳过
        if not self.agent_memories:
            return {}
        return self.agent_memories.consolidate_all()

    # ------------------------------------------------------------------ #
    # Mock 模式：演示完整 PDCA 闭环（不依赖 AgentTeams 平台）
    # ------------------------------------------------------------------ #
    async def _run_mock(self) -> TaskState:
        """Mock 模式：确定性假实现，秒级跑完完整 PDCA 闭环。

        仅在本地演示时使用，不依赖 AgentTeams 平台。
        """
        # GAP-13: mock 模式下确保本地上下文工程组件已初始化（双保险）
        self._ensure_local_contexts()
        print("  [Mock] 模拟 AgentTeams PDCA 闭环（不连平台）")
        await self.event_bus.task_started(self.task_id, self.spec)

        # ARIS 移植模块（2026-08-31，批次 7 集成）：三处「增量观测/演示」接入。
        #   全部 try/except 包裹：任何异常/缺依赖都静默跳过，绝不阻断既有闭环，
        #   保持 mock 的 6 里程碑 / 8 状态流转 / 每状态一个产物 md 的测试契约不变。
        try:
            from loop.iteration_log import note as iter_note
            from loop.evidence_check import check_batch
            from loop.review_gate import evaluate_transition
            from loop.acceptance_gate import accept as gate_accept
        except Exception:
            iter_note = check_batch = evaluate_transition = gate_accept = None

        # Mock 闭环产出：让 SPEC_INPUT / FIX_APPLY 阶段贴合本次 spec，
        # 使演示叙事一致（默认缺陷修复语义；建站类任务会显示对应产出）。
        # 保持既有测试契约不变：每状态一个产物 md、6 里程碑、8 个状态流转。
        spec_head = (self.spec or "").splitlines()[0][:60]
        mock_outputs = {
            State.SPEC_INPUT: f"TASK_SPEC_READY\n\n任务规格：{spec_head}\n验收标准：按 spec 完成并验证\n产出：确定性实现",
            State.SPEC_DECOMPOSE: "TASK_SPEC_READY\n\n子任务：\n1. 解析需求\n2. 产出实现\n3. 测试验证",
            State.ROOT_CAUSE: "ROOT_CAUSE_FOUND\n\n根因：任务可确定性实现\n影响面：目标产物",
            State.FIX_APPLY: f"FIX_APPLIED\n\n产出：{spec_head}\n改动文件：index.html / style.css / app.js（按需）",
            State.TEST_VERIFY: "TEST_PASSED\n\n测试用例：结构完整性、关键逻辑、边界值\n覆盖：100%\n结论：PASS",
            State.RELEASE: "RELEASE_OK\n\n发布策略：静态站点\n回滚预案：保留上一版本\n审批：通过",
            State.RELEASE_APPROVE: "RELEASE_OK\n\n验证通过，发布",
            State.RETROSPECT: "RETROSPECT_DONE\n\n经验教训：\n1. 确定性建站应拆分为结构/样式/逻辑三部分\n2. 静态站点无后端依赖，易于验证",
        }

        stages = [
            State.SPEC_INPUT, State.SPEC_DECOMPOSE, State.ROOT_CAUSE,
            State.FIX_APPLY, State.TEST_VERIFY, State.RELEASE,
            State.RELEASE_APPROVE, State.RETROSPECT,
        ]

        for stage in stages:
            executor = STATE_EXECUTOR[stage]
            expected_ms = STATE_EXPECTED_MILESTONE[stage].value
            output = mock_outputs.get(stage, f"{expected_ms}\n\nMock 产出")

            print(f"\n  阶段 {stage.value} → {executor}: {output[:80]}...")

            # ARIS 停滞检测（增量观测）：每轮记录「新发现数」。
            #   mock 每阶段都有产出 → new_findings=1，stale 归零、pivot=none，不会误触发转向。
            #   真实委托模式下可改为从 milestone 增量推导，同一台账文件、同一裁决语义。
            if iter_note is not None:
                try:
                    iter_note(
                        root=str(self.workdir / "shared" / "runs"),
                        run_id=self.task_id,
                        phase=stage.value,
                        new_findings=1,
                    )
                except Exception:
                    pass

            await self.event_bus.worker_started(executor, self.task_id)
            await asyncio.sleep(0.05)
            await self.event_bus.worker_completed(
                executor, self.task_id, expected_ms, elapsed=0.05,
            )
            await self.event_bus.milestone_reached(executor, self.task_id, expected_ms)

            self.state.advance(
                STATE_EXPECTED_MILESTONE[stage],
                verdict="PASS", detail=output[:200], by=executor,
            )

            # 记录到该 Agent 的独立记忆（跨任务持久化）
            self.record_agent_iteration(
                agent_name=executor,
                phase=stage.value.lower(),
                outcome="success",
                patterns=[f"完成 {stage.value} 阶段"],
            )

            artifact_path = self.tasks_dir / f"{stage.value.lower()}.md"
            artifact_path.write_text(output, encoding="utf-8")
            self.state.artifacts[stage.value] = str(artifact_path)

            self.protocol_by_agent[executor] = True
            self.adoption_by_agent[executor] = 1.0

            # 知识/Skill 复用追踪：每个阶段完成视为一次"复用沉淀经验"，
            # 知识归属 retrospector（沉淀者），供成长分治理统计跨任务复用率。
            self.usage_tracker.record_knowledge_hit(
                knowledge_id=f"{self.task_id}:{expected_ms}",
                task_id=self.task_id,
                source_agent="retrospector",
                category=stage.value,
            )
            self.usage_tracker.record_skill_invoke(
                skill_name=f"milestone-{stage.value.lower()}",
                agent_name=executor,
            )

            self.audit.log_milestone(self.task_id, executor, expected_ms,
                                     state=stage.value, result="PASS")

            # ARIS 证据预检（增量观测）：TEST_VERIFY 阶段产出后，对被引用的证据做确定性预检。
            #   mock 产物是确定性写盘的 test_verify.md，预检应全部 verified；
            #   若预检命中 path_missing/value_not_found，说明引用的是幻觉证据 → 打回重测
            #   （真实委托模式：Tester 把证据清单写为 claims.json，交 evidence_check 机械校验）。
            if stage == State.TEST_VERIFY and check_batch is not None:
                try:
                    claims = [
                        {"value": "TEST_PASSED", "source": "test_verify.md"},
                        {"value": "100", "source": "test_verify.md"},  # 覆盖：100%
                        {"value": "PASS", "source": "test_verify.md"},
                    ]
                    pre = check_batch(claims, root=str(self.tasks_dir))
                    summary = pre.get("summary", {})
                    ok = summary.get("verified", 0) == len(claims)
                    print(f"  [证据预检] test_verify.md → verified={summary.get('verified', 0)}"
                          f"/{len(claims)} (path_missing={summary.get('path_missing', 0)}, "
                          f"value_not_found={summary.get('value_not_found', 0)})"
                          f" {'PASS' if ok else 'FAIL'}")
                except Exception:
                    pass

            # 发布审批：登记一条人工审批请求，演示审批留痕闭环 + TTL 超时兜底。
            #   默认 auto-approve（mock 秒级闭环不卡在审批）；设 APPROVAL_WAIT=1 则等人工/TTL。
            if stage == State.RELEASE_APPROVE:
                req = await self.approval.request(
                    self.task_id,
                    reason="发布门禁：灰度放量需人工确认",
                    requester="releaser",
                    kind="release",
                )
                if os.environ.get("APPROVAL_WAIT") == "1":
                    # 等待人工审批或超时（后台 check_timeouts 会兜底）
                    deadline = time.time() + (self.approval.ttl_secs or 5)
                    while time.time() < deadline:
                        if req.status.name != "PENDING":
                            break
                        await asyncio.sleep(0.2)
                    if req.status.name == "PENDING":
                        await self.approval.check_timeouts()
                else:
                    # 默认自动批准（演示审批闭环，不阻塞闭环）
                    await self.approval.decide(
                        req.approval_id, approved=True, reviewer="manager-auto",
                    )

            # ARIS 评审路由 + 验收门（增量观测）：展示「执行 ≠ 验收」的硬纪律。
            #   ① review_gate.evaluate_transition：裁决表判定跨族评审才可终结；
            #   ② acceptance_gate.accept：验证验收单号格式 + 执行者不能自评 + 跨族评审。
            #   mock 下只打印演示结论，不改变真实裁决（发布仍由上面的审批闭环决定）。
            if stage == State.RELEASE_APPROVE and (evaluate_transition is not None
                                                   or gate_accept is not None):
                try:
                    if evaluate_transition is not None:
                        t = evaluate_transition(
                            round_backend="llm-chat",
                            score=8.0,
                            verdict="ready",
                            requires_external_acquittal=False,
                            executor_model="deepseek-v4-flash",   # 执行者：deepseek 家族
                            reviewer_model="qwen-plus",           # 评审者：qwen 家族（跨族）
                        )
                        print(f"  [评审路由] llm-chat 跨族评审 → {t.decision}"
                              f" (reason={t.reason})")
                    if gate_accept is not None:
                        v = gate_accept(
                            claim="RELEASE_OK 验收通过",
                            executor="releaser",          # 执行者
                            reviewer="qwen-plus",         # 跨族评审者（非 releaser 自评）
                            verdict_id="review-0001",
                        )
                        print(f"  [验收门] {v.to_dict()}")
                except Exception:
                    pass

            if stage == State.RETROSPECT:
                break

        # 沉淀所有 Agent 的记忆到长期记忆
        consolidated = self.consolidate_all_agent_memories()
        if consolidated:
            print(f"\n  [记忆沉淀] {len(consolidated)} 个 Agent 的记忆已更新长期记忆")

        await self.event_bus.task_completed(self.task_id)
        self._print_summary()
        self._print_evaluation()
        return self.state


# ========================================================================== #
# 便捷函数
# ========================================================================== #

async def run_pdca_task(
    spec: str,
    workdir: str | Path | None = None,
    mock: bool = False,
    task_id: str = "",
) -> TaskState:
    """一键运行 PDCA 闭环任务（提交给 AgentTeams Manager）。

    Args:
        spec: 任务规格描述
        workdir: 工作目录
        mock: 是否使用 mock 模式（不连 AgentTeams 平台）
        task_id: 任务 ID（不传则自动生成）

    Returns:
        最终的 TaskState

    用法:
        state = await run_pdca_task(spec="修复登录页面空指针异常")
    """
    if not task_id:
        task_id = f"pdca-{int(time.time())}"

    workdir = Path(workdir) if workdir else Path.cwd()

    loop = AgentTeamsLoop(
        task_id=task_id,
        spec=spec,
        workdir=workdir,
        mock=mock,
    )
    return await loop.run()


async def check_platform_ready() -> dict[str, Any]:
    """检查 AgentTeams 平台是否就绪。"""
    client = AgentTeamsClient()
    return await client.status()


# ========================================================================== #
# 自检
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
            mock=True,
        )

        state = await loop.run()
        assert state.state == State.RETROSPECT
        assert "RETROSPECT_DONE" in state.milestones
        print(f"✓ Mock 闭环完成: {state.state.value}")

    print("=== 自检通过 ===")


if __name__ == "__main__":
    asyncio.run(_self_test())