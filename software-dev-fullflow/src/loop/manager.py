"""Manager 调度 Loop —— 可运行的研发团队调度引擎。

对应 design/MANAGER-LOOP-DESIGN.md：把"单 Agent ReAct"升级为"调度 ReAct"。
Manager 不做具体编码/测试，只做调度：
    wake → 读任务 → 派单给当前状态对应的 Worker → 收结果 → 验证闸门判断 → 推进/打回里程碑 → 循环

运行底座：MAF（Microsoft Agent Framework）已验证能在 DeepSeek（OpenAI 兼容）上跑通
（见 demo/maf_sequential_deepseek.py）。这里复用 MAF 的 Agent + OpenAIChatCompletionClient，
把我们的调度逻辑（状态机 + 里程碑 + 6 Worker）作为 Manager 的控制循环。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI

# 让 src/loop 作为包可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loop.state import State, Milestone, TaskState, STATE_EXECUTOR, STATE_EXPECTED_MILESTONE  # noqa: E402
from loop.team import get_role, DEFAULT_AGENTS  # noqa: E402
from loop.fixer_loop import FixerLoop  # noqa: E402
from loop.evaluation import score_team, adoption_score  # noqa: E402


class TeamManagerLoop:
    """研发团队调度 Manager。

    核心：一个确定性控制循环，驱动 6 个研发 Worker 完成一条 PDCA 闭环。
    不依赖 Agent 自律收敛，靠"验证闸门"（tester/releaser 的确定性判断）做客观裁判。
    """

    def __init__(self, task_id: str, spec: str, workdir: Path, mock: bool = False):
        self.task_id = task_id
        self.spec = spec
        self.workdir = workdir                    # 顶层工作目录
        self.tasks_dir = workdir / "shared" / "tasks" / task_id
        self.knowledge_dir = workdir / "shared" / "knowledge"
        self.state = TaskState(task_id=task_id, spec=spec)
        self.mock = mock                          # mock=True 时用确定性结果，秒级跑完完整闭环
        # 成员评价信号采集：打回次数 / 累计耗时 / 协议合规 / 下游采纳度（喂给 score_team）
        self.reject_by_agent: dict[str, int] = {}
        self.durations_by_agent: dict[str, float] = {}
        self.protocol_by_agent: dict[str, bool] = {}
        self.adoption_by_agent: dict[str, float] = {}
        # 通过 async_client 注入 httpx(trust_env=False)，绕过系统/环境代理（否则 10061 连接被拒）
        self.client = OpenAIChatCompletionClient(
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            async_client=AsyncOpenAI(
                api_key=os.environ["DEEPSEEK_API_KEY"],
                base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                http_client=httpx.AsyncClient(trust_env=False),
            ),
        )

    # ------------------------------------------------------------------ #
    # 工具：调用一个研发 Worker 跑当前阶段，返回该 Worker 的产出文本
    # ------------------------------------------------------------------ #
    async def _run_worker(self, role_name: str, milestone: str, context: str) -> str:
        """实例化并运行一个 Worker Agent，返回其最终回复文本。

        Fixer 特殊处理：走 Ralph 式单 Agent 自我迭代（FixerLoop），
        内部自主完成"写代码→校验→修正→再校验"循环，减少 Manager 层打回。
        """
        role = get_role(role_name)
        # mock 模式：确定性假实现，展示调度流程而不调 API
        if self.mock:
            handoff = f"@{role.handoff_to}" if role.handoff_to else "（终态，闭环结束）"
            return (
                f"[{role.title}] 已完成职责。\n"
                f"任务规格: {self.spec[:80]}\n"
                f"产出里程碑: {milestone}\n"
                f"交接: {handoff}\n"
                f"（mock 输出，用于快速演示调度循环）"
            )

        # ---- Fixer：Ralph 式自我迭代 ----
        if role_name == "fixer":
            fixer = FixerLoop(client=self.client, workdir=self.tasks_dir, mock=False)
            return await fixer.run(context=context, milestone=milestone)

        # ---- 其他 Worker：一次性 Agent 调用 ----
        prompt = (
            f"[任务 {self.task_id}] {role.title}（{role.real_role}）请履行职责。\n\n"
            f"【任务规格】\n{self.spec}\n\n"
            f"【当前阶段产物/上下文】\n{context}\n\n"
            f"【你的工作准则】\n{role.guidelines}\n\n"
            f"【本次要产出的里程碑】{milestone}\n"
            f"完成后 @mention 给 {role.handoff_to or 'manager'}。请直接输出你的工作成果。"
        )
        worker = Agent(
            client=self.client,
            instructions=role.soul + "\n\n" + role.guidelines,
            name=role_name,
        )
        result = await worker.run(prompt)
        # 提取 assistant 最后一条文本
        text = ""
        for msg in result.messages:
            if getattr(msg, "role", None) == "assistant":
                text = getattr(msg, "text", "") or text
        return text.strip()

    # ------------------------------------------------------------------ #
    # 验证闸门：由确定性规则 + 下一位裁判 Agent 判断当前阶段是否通过
    # ------------------------------------------------------------------ #
    async def _verify(self, stage: State, worker_output: str) -> tuple[str, str]:
        """返回 (verdict, detail)。verdict 为 PASS / FAIL。"""
        # mock 模式：一律判 PASS，快速推进完整闭环
        if self.mock:
            return "PASS", "（mock 校验通过）"
        # 确定性兜底：产出为空视为 FAIL（不依赖 Agent 自律）
        if not worker_output:
            return "FAIL", "Worker 未产出有效结果（空输出）"

        # 通过一个独立"裁判" Agent 做质量判断（对应测试/发布门禁）
        judge_name = "tester" if stage in (State.TEST_VERIFY, State.FIX_APPLY) else "releaser"
        if stage in (State.RELEASE, State.RELEASE_APPROVE):
            judge_name = "releaser"
        judge_role = get_role(judge_name)
        judge = Agent(
            client=self.client,
            instructions=judge_role.soul + "\n\n" + judge_role.guidelines,
            name=judge_name,
        )
        judgement = await judge.run(
            f"[验收] 任务 {self.task_id} 当前阶段 {stage.value} 的产物如下：\n"
            f"{worker_output}\n\n"
            f"请按你的准则做客观评判，严格输出：\n"
            f"PASS: <通过理由>\n"
            f"FAIL: <失败原因，供打回>"
        )
        judge_text = ""
        for msg in judgement.messages:
            if getattr(msg, "role", None) == "assistant":
                judge_text = getattr(msg, "text", "") or judge_text
        judge_text = judge_text.strip()
        verdict = "FAIL" if judge_text.upper().startswith("FAIL") else "PASS"
        return verdict, judge_text

    # ------------------------------------------------------------------ #
    # 主调度循环（Manager Loop 的确定性骨架）
    # ------------------------------------------------------------------ #
    async def run(self, max_stages: int = 8, max_iter_per_stage: int = 3) -> TaskState:
        """驱动一条完整 PDCA 闭环。返回最终 TaskState。"""
        self.state.save(self.tasks_dir / "state.json")
        print(f"\n=== Manager Loop 启动 · 任务 {self.task_id} ===")
        print(f"初始状态: {self.state.state.value}")

        # 上下文累积：每阶段把上一阶段产物作为下一阶段的输入（上下文传递）
        context = f"【原始任务】\n{self.spec}\n"

        stages_done = 0
        while stages_done < max_stages:
            stage = self.state.state
            if stage == State.RETROSPECT and self.state.milestones.get(Milestone.RETROSPECT_DONE.value):
                break  # 闭环完成

            executor = STATE_EXECUTOR[stage]
            expected_ms = STATE_EXPECTED_MILESTONE[stage].value
            print(f"\n[{stages_done + 1}] 阶段 {stage.value} → 执行者 {executor}（期望里程碑 {expected_ms}）")

            # 同阶段重试计数
            local_retry = 0
            while True:
                local_retry += 1
                t0 = time.time()
                print(f"  → 派单给 {executor} ...")
                worker_out = await self._run_worker(executor, expected_ms, context)
                elapsed = time.time() - t0
                self.durations_by_agent[executor] = self.durations_by_agent.get(executor, 0.0) + elapsed
                print(f"  ← {executor} 产出（{elapsed:.1f}s）：{worker_out[:120]}")

                # 验证闸门（客观裁判）
                verdict, detail = await self._verify(stage, worker_out)
                print(f"  校验: {verdict}")

                if verdict == "PASS":
                    # 成员评价埋点：协议合规（里程碑词 + 交接 @mention）+ 下游采纳度
                    # 注意在追加 context 前采集，让 adoption 反映"对既有上游的采纳"
                    role = get_role(executor)
                    milestone_ok = expected_ms in worker_out
                    # 交接合规：有下一棒则需 @mention 交接；终态角色（无 handoff）默认合规
                    handoff_ok = (not role.handoff_to) or ("@" in worker_out) or (role.handoff_to in worker_out)
                    self.protocol_by_agent[executor] = milestone_ok and handoff_ok
                    self.adoption_by_agent[executor] = adoption_score(worker_out, context)

                    # 推进里程碑 + 状态机
                    new_state = self.state.advance(
                        STATE_EXPECTED_MILESTONE[stage],
                        verdict="PASS", detail=detail[:200], by=executor,
                    )
                    # 落产物到 shared/tasks/{id}/
                    artifact_path = self.tasks_dir / f"{stage.value.lower()}.md"
                    artifact_path.write_text(worker_out, encoding="utf-8")
                    self.state.artifacts[stage.value] = str(artifact_path)
                    context += f"\n[{stage.value} 产物 @{executor}]\n{worker_out[:2000]}\n"
                    self.state.save(self.tasks_dir / "state.json")
                    print(f"  ✔ 里程碑 {expected_ms} 达成 → 状态 → {new_state.value}")
                    break

                # 埋点：FAIL 归到当前执行者（成员评价信号）
                self.reject_by_agent[executor] = self.reject_by_agent.get(executor, 0) + 1
                # FAIL：打回（有上限，防死循环）
                if local_retry >= max_iter_per_stage:
                    print(f"  ✘ 阶段 {stage.value} 打回 {local_retry} 次仍失败，跳过该阶段继续（避免死循环）")
                    self.state.advance(
                        STATE_EXPECTED_MILESTONE[stage],
                        verdict="FAIL", detail=f"打回上限: {detail[:200]}", by=executor,
                    )
                    break
                # 打回重试：带上裁判反馈让 Worker 修正
                context += f"\n[{stage.value} 校验未过 @{executor}] {detail[:500]}\n"
                print(f"  → 打回 {executor} 重试（第 {local_retry} 次）：{detail[:100]}")

            self.state.save(self.tasks_dir / "state.json")
            stages_done += 1

            # 闭环完成判断
            if self.state.milestones.get(Milestone.RETROSPECT_DONE.value):
                print("\n=== 闭环完成：RETROSPECT_DONE ===")
                break

        print("\n=== Manager Loop 结束 ===")
        print(f"最终状态: {self.state.state.value}")
        print(f"里程碑: {list(self.state.milestones.keys())}")
        print(f"产物: {list(self.state.artifacts.values())}")
        # 成员评价：汇总本次闭环采集的信号，输出团队评价报告
        evaluation = score_team(
            self.state,
            reject_counts=self.reject_by_agent,
            durations=self.durations_by_agent,
            adoptions=self.adoption_by_agent,
            protocol_oks=self.protocol_by_agent,
        )
        print("\n" + evaluation.report())

        # 落盘成绩单（可审计留痕）+ 输出 AgentTeams 治理命令（对接动态团队）
        agents_dir = self.workdir / "shared" / "agents"
        paths = evaluation.save_scorecards(agents_dir)
        print(f"\n成绩单已落盘: {', '.join(str(p) for p in paths)}")
        cmds = evaluation.governance_commands()
        if cmds:
            print("\n治理建议（AgentTeams 命令）:")
            for cmd in cmds:
                print(f"  {cmd}")
        return self.state
