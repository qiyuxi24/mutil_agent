"""Fixer 单 Agent 自我迭代引擎 —— Ralph 方法论落地。

来源：references/theory/SINGLE-AGENT-ITERATION.md（Geoffrey Huntley "Ralph"）
核心思想：把 Fixer 从"一次性调 LLM 写代码"升级为"内部循环自我迭代"，
       写完代码 → 自我校验 → 失败则修正 → 再校验 → 直到通过。

Ralph 五大原则在本模块的落地：
  1. 一次循环只做一件事   → 按 fix plan 拆成原子步骤，每步只改一个文件/函数
  2. 规格驱动（Spec）     → 读 root-cause.md + plan.md 当蓝图，不盲目改代码
  3. 子代理并行           → 代码审查/校验用独立 LLM 调用（模拟编译器/静态分析器）
  4. 反压机制（Backpressure）→ 校验 Agent 当客观裁判，不靠 Fixer 自评
  5. 持续调优             → 错误反馈写回上下文，下一轮避免同类错误

与 Manager 的关系：
  - Manager 把 Fixer 当作一个"黑盒 Worker"，不知道内部在迭代
  - FixerLoop 对 Manager 暴露同样的接口：入参 context + milestone，出参文本
  - Fixer 内部迭代全部消化，Manager 只看到最终结果（减少打回次数）
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI


# ------------------------------------------------------------------ #
# 数据结构
# ------------------------------------------------------------------ #

@dataclass
class FixStep:
    """修复计划中的一个原子步骤。"""
    index: int
    description: str            # 这一步要做什么（一句话）
    target_file: str = ""       # 目标文件（可为空，LLM 按描述判断）
    status: str = "pending"     # pending | in_progress | done | failed
    retries: int = 0
    error_feedback: str = ""    # 上一次失败的错误反馈


@dataclass
class FixPlan:
    """修复工程师的完整修复计划。"""
    summary: str                # 总体修复思路
    steps: list[FixStep] = field(default_factory=list)
    constraints: str = ""       # 约束（不改什么、要注意什么）
    rollback: str = ""          # 回滚预案


# ------------------------------------------------------------------ #
# FixerLoop —— Ralph 式单 Agent 自我迭代
# ------------------------------------------------------------------ #

class FixerLoop:
    """修复工程师的 Ralph 式自我迭代引擎。

    用法：
        loop = FixerLoop(client=client, workdir=workdir, mock=False)
        result = await loop.run(context=..., milestone="FIX_APPLIED")

    context 应包含：
        - 原始任务规格
        - root-cause.md（根因分析产物）
        - 任何已有代码/上下文
    """

    # 硬上限（防死循环，Ralph 的"收敛靠反压，不靠无限重试"）
    MAX_STEPS = 8                 # 单次修复最多拆成 8 个原子步骤
    MAX_RETRIES_PER_STEP = 3      # 单步最多重试 3 次
    MAX_TOTAL_ITERATIONS = 20     # 总迭代上限（所有步骤 + 重试）

    def __init__(
        self,
        client: OpenAIChatCompletionClient,
        workdir: Path,
        mock: bool = False,
    ):
        self.client = client
        self.workdir = workdir
        self.mock = mock
        self._total_iterations = 0
        self._error_log: list[str] = []  # 持续调优：记录踩过的坑

    # ------------------------------------------------------------------ #
    # 公开入口
    # ------------------------------------------------------------------ #

    async def run(self, context: str, milestone: str = "FIX_APPLIED") -> str:
        """运行 Ralph 式自我迭代，返回最终修复产物。

        返回文本以 FIX_APPLIED 开头表示成功，以 FIX_FAILED 开头表示失败。
        """
        if self.mock:
            return self._mock_run(context, milestone)

        t0 = time.time()
        print(f"  [FixerLoop] Ralph 自我迭代启动（上下文 {len(context)} 字符）")

        # Step 1: 生成修复计划（plan.md）
        plan = await self._generate_plan(context)
        if not plan.steps:
            return self._fail("无法生成修复计划（plan 为空）")

        print(f"  [FixerLoop] 修复计划: {len(plan.steps)} 步，概要: {plan.summary[:80]}")

        # Step 2: 逐步执行（Ralph 核心循环）
        all_outputs: list[str] = []
        for step in plan.steps:
            self._check_total_limit()
            step.status = "in_progress"

            result = await self._execute_step(step, plan, context, all_outputs)
            if result.startswith("FIX_FAILED"):
                # 单步失败，整体失败
                return self._fail(f"步骤 {step.index + 1}/{len(plan.steps)} 失败: {result}")

            all_outputs.append(result)
            step.status = "done"

        # Step 3: 最终自检（整体校验）
        final_output = await self._final_review(plan, all_outputs, context)
        if final_output.startswith("FIX_FAILED"):
            return final_output

        elapsed = time.time() - t0
        print(f"  [FixerLoop] Ralph 自我迭代完成（{elapsed:.1f}s，{self._total_iterations} 次 LLM 调用，{len(plan.steps)} 步）")
        if self._error_log:
            print(f"  [FixerLoop] 持续调优记录: {len(self._error_log)} 条经验")

        return f"FIX_APPLIED\n\n{final_output}"

    # ------------------------------------------------------------------ #
    # Step 1: 生成修复计划
    # ------------------------------------------------------------------ #

    async def _generate_plan(self, context: str) -> FixPlan:
        """基于 root-cause 和规格生成修复计划（原子步骤拆分）。"""
        prompt = (
            "你是修复工程师，需要为一个缺陷制定修复计划。\n\n"
            f"【上下文】\n{context}\n\n"
            "请按以下格式输出修复计划：\n\n"
            "## 修复概要\n"
            "（一句话描述总体修复思路）\n\n"
            "## 约束\n"
            "（列出修复中不能碰的模块、不能改的接口、要注意的边界条件）\n\n"
            "## 回滚预案\n"
            "（如果修复引入新问题，如何回滚）\n\n"
            "## 原子步骤\n"
            "按执行顺序列出每个步骤，每步只做一件事：\n"
            "1. [步骤描述] — 目标文件: xxx\n"
            "2. [步骤描述] — 目标文件: xxx\n\n"
            "规则：\n"
            "- 每个步骤必须是原子化的（改一个文件/函数/模块）\n"
            "- 步骤之间可以有依赖，按依赖顺序排列\n"
            "- 如果有单元测试需要同步更新，作为独立步骤\n"
            "- 最多 {MAX} 步，超出则合并\n"
        ).replace("{MAX}", str(self.MAX_STEPS))

        agent = self._make_agent("fixer-planner", "你是修复计划制定者，只做规划不做编码。")
        result = await self._call_agent(agent, prompt)
        return self._parse_plan(result)

    def _parse_plan(self, text: str) -> FixPlan:
        """从 LLM 输出中解析修复计划。"""
        plan = FixPlan(summary="")
        lines = text.split("\n")
        section = ""
        step_idx = 0

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## 修复概要") or stripped.startswith("## 概要"):
                section = "summary"
                continue
            if stripped.startswith("## 约束"):
                section = "constraints"
                continue
            if stripped.startswith("## 回滚"):
                section = "rollback"
                continue
            if stripped.startswith("## 原子步骤") or stripped.startswith("## 步骤"):
                section = "steps"
                continue
            if stripped.startswith("##"):
                section = ""
                continue

            if section == "summary" and stripped:
                plan.summary += stripped + " "
            elif section == "constraints" and stripped:
                plan.constraints += stripped + "\n"
            elif section == "rollback" and stripped:
                plan.rollback += stripped + "\n"
            elif section == "steps" and stripped:
                # 匹配 "1. xxx — 目标文件: yyy" 或 "1. xxx"
                if stripped[0].isdigit():
                    desc = stripped.split(".", 1)[-1].strip()
                    target_file = ""
                    if "目标文件:" in desc or "目标文件：" in desc:
                        parts = desc.split("目标文件:") if "目标文件:" in desc else desc.split("目标文件：")
                        desc = parts[0].strip().rstrip("—").strip().rstrip("-").strip()
                        target_file = parts[1].strip() if len(parts) > 1 else ""
                    plan.steps.append(FixStep(index=step_idx, description=desc, target_file=target_file))
                    step_idx += 1

        plan.summary = plan.summary.strip()
        plan.constraints = plan.constraints.strip()
        plan.rollback = plan.rollback.strip()

        # 兜底：如果没解析出步骤，整个修复作为一个步骤
        if not plan.steps:
            plan.steps = [FixStep(index=0, description="执行完整修复（按根因分析和规格）")]
        if not plan.summary:
            plan.summary = "按根因分析执行修复"

        return plan

    # ------------------------------------------------------------------ #
    # Step 2: 执行单个原子步骤（Ralph 核心：写→验→修→再验）
    # ------------------------------------------------------------------ #

    async def _execute_step(
        self, step: FixStep, plan: FixPlan, context: str, previous_outputs: list[str]
    ) -> str:
        """执行一个原子修复步骤，内带 Ralph 反压循环。"""
        prev_context = "\n\n".join(previous_outputs) if previous_outputs else "（无前置步骤）"

        # 构建持续调优的规则
        tuning_rules = ""
        if self._error_log:
            tuning_rules = "【已踩过的坑（禁止再犯）】\n" + "\n".join(
                f"- {e}" for e in self._error_log[-5:]
            ) + "\n\n"

        while step.retries < self.MAX_RETRIES_PER_STEP:
            self._check_total_limit()

            # --- 写代码 ---
            error_context = ""
            if step.error_feedback:
                error_context = (
                    f"\n【上轮校验失败——请修正以下问题】\n{step.error_feedback}\n"
                    f"请针对以上问题修改代码，不要引入无关改动。\n"
                )

            prompt = (
                f"你是修复工程师，正在执行修复计划的第 {step.index + 1}/{len(plan.steps)} 步。\n\n"
                f"【修复概要】{plan.summary}\n"
                f"【约束条件】{plan.constraints or '无特殊约束'}\n"
                f"【当前步骤】{step.description}\n"
                f"{'【目标文件】' + step.target_file if step.target_file else ''}\n\n"
                f"【原始上下文】\n{context[:3000]}\n\n"
                f"【前置步骤产出】\n{prev_context[:2000]}\n\n"
                f"{tuning_rules}"
                f"{error_context}"
                f"请输出这一步的代码改动（用 diff 或代码块描述），只做这一步的事，不要跨步骤。\n"
                f"完成后请标注: STEP_{step.index + 1}_DONE"
            )

            agent = self._make_agent("fixer-coder", self._coder_instructions())
            code_output = await self._call_agent(agent, prompt)
            self._total_iterations += 1

            # --- 反压校验（Ralph 核心：客观裁判） ---
            verdict, feedback = await self._validate_step(step, plan, code_output, context)

            if verdict == "PASS":
                return code_output

            # --- 校验失败：记录错误，准备重试 ---
            step.retries += 1
            step.error_feedback = feedback
            self._error_log.append(f"[步骤{step.index + 1}] {feedback[:200]}")
            print(f"  [FixerLoop] 步骤 {step.index + 1} 校验失败（第 {step.retries} 次），反馈: {feedback[:100]}")

        # 重试上限
        return f"FIX_FAILED: 步骤 {step.index + 1} 重试 {self.MAX_RETRIES_PER_STEP} 次仍失败。最后反馈: {step.error_feedback[:200]}"

    # ------------------------------------------------------------------ #
    # 反压校验（独立校验 Agent，不靠 Fixer 自评）
    # ------------------------------------------------------------------ #

    async def _validate_step(
        self, step: FixStep, plan: FixPlan, code_output: str, context: str
    ) -> tuple[str, str]:
        """用独立校验 Agent 对单步代码做客观评判。

        返回 (verdict, feedback)。verdict 为 PASS / FAIL。
        """
        validate_prompt = (
            "你是代码审查员（Code Reviewer），只做客观评判，不做修改。\n\n"
            "请对以下修复步骤的代码改动做严格审查：\n\n"
            f"【修复概要】{plan.summary}\n"
            f"【当前步骤】{step.description}\n"
            f"【约束条件】{plan.constraints or '无'}\n\n"
            f"【代码改动】\n{code_output[:4000]}\n\n"
            "审查标准（逐项检查）：\n"
            "1. 改动是否只针对当前步骤？（跨步骤改动 = FAIL）\n"
            "2. 是否有占位实现（stub / TODO / pass / 空函数体）？（有 = FAIL）\n"
            "3. 是否违反约束条件？（违反 = FAIL）\n"
            "4. 代码逻辑是否自洽？（不自洽 = FAIL）\n"
            "5. 是否引入了无关改动？（有 = FAIL）\n\n"
            "输出格式（严格）：\n"
            "PASS: <简要通过理由>\n"
            "或\n"
            "FAIL: <具体失败原因，指出哪条标准未通过，建议如何修正>"
        )

        reviewer = self._make_agent("code-reviewer", (
            "你是严格的代码审查员。你的职责是找出代码中的任何问题，"
            "不放过占位实现、逻辑漏洞、无关改动。"
            "你只输出 PASS 或 FAIL 的客观判断，不提供修改建议之外的任何内容。"
        ))
        result = await self._call_agent(reviewer, validate_prompt)
        self._total_iterations += 1

        if result.strip().upper().startswith("PASS"):
            return "PASS", result.strip()
        return "FAIL", result.strip()

    # ------------------------------------------------------------------ #
    # Step 3: 最终整体审查
    # ------------------------------------------------------------------ #

    async def _final_review(
        self, plan: FixPlan, step_outputs: list[str], context: str
    ) -> str:
        """所有步骤完成后，进行一次整体审查，确保各步骤衔接正确。"""
        combined = "\n\n---\n\n".join(
            f"步骤 {i + 1}:\n{out[:1500]}" for i, out in enumerate(step_outputs)
        )

        prompt = (
            "你是修复工程师，已完成所有修复步骤。请做最终整合审查。\n\n"
            f"【修复概要】{plan.summary}\n"
            f"【约束条件】{plan.constraints or '无'}\n"
            f"【回滚预案】{plan.rollback or '无'}\n\n"
            f"【所有步骤产出】\n{combined}\n\n"
            "请整合所有步骤的产出，输出一份完整的修复报告：\n"
            "1. 修复了什么（一句话）\n"
            "2. 改了哪些文件（列表）\n"
            "3. 每个文件的改动说明\n"
            "4. 如何验证修复有效\n"
            "5. 回滚步骤\n\n"
            "确保报告完整、可执行、可验证。不要输出 FIX_FAILED。"
        )

        agent = self._make_agent("fixer-finalizer", self._coder_instructions())
        result = await self._call_agent(agent, prompt)
        self._total_iterations += 1

        if "FIX_FAILED" in result.upper():
            return f"FIX_FAILED: 最终审查未通过: {result[:200]}"
        return result

    # ------------------------------------------------------------------ #
    # 辅助方法
    # ------------------------------------------------------------------ #

    def _make_agent(self, name: str, instructions: str) -> Agent:
        """创建 Agent 实例（复用 client）。"""
        return Agent(client=self.client, instructions=instructions, name=name)

    async def _call_agent(self, agent: Agent, prompt: str) -> str:
        """调用 Agent 并提取 assistant 回复文本。"""
        result = await agent.run(prompt)
        text = ""
        for msg in result.messages:
            role = getattr(msg, "role", None)
            if role == "assistant":
                text = getattr(msg, "text", "") or text
        return text.strip()

    def _coder_instructions(self) -> str:
        """Fixer 编码 Agent 的通用指令。"""
        return (
            "你是软件研发团队的修复工程师，负责编写高质量、可验证的代码修复。\n"
            "原则：\n"
            "1. 最小化改动——只改必要的代码，不重构无关模块\n"
            "2. 不写占位实现——所有代码都是可运行的完整实现\n"
            "3. 边界处理——考虑空值、异常、并发\n"
            "4. 可验证——代码改动能通过编译和测试\n"
            "5. 不自评——你的代码由校验员审查，你只负责写"
        )

    def _check_total_limit(self) -> None:
        """检查总迭代上限，防止死循环。"""
        if self._total_iterations >= self.MAX_TOTAL_ITERATIONS:
            raise RuntimeError(
                f"FixerLoop 超过总迭代上限 {self.MAX_TOTAL_ITERATIONS}，"
                f"最后 {len(self._error_log)} 条错误: {self._error_log[-3:]}"
            )

    def _fail(self, reason: str) -> str:
        """生成失败输出。"""
        return f"FIX_FAILED: {reason}"

    def _mock_run(self, context: str, milestone: str) -> str:
        """Mock 模式：确定性假实现，快速演示 Ralph 迭代流程。"""
        print("  [FixerLoop] mock 模式：模拟 Ralph 3 步迭代")
        steps = [
            "STEP_1_DONE: 修复核心逻辑（mock）",
            "STEP_2_DONE: 更新单元测试（mock）",
            "STEP_3_DONE: 边界条件处理（mock）",
        ]
        return (
            f"{milestone}\n\n"
            f"## 修复报告（Ralph 自我迭代 · mock）\n\n"
            f"修复概要: 基于根因分析执行修复\n"
            f"迭代步骤: {len(steps)} 步\n"
            f"校验轮次: 每步 1 轮（mock 全部通过）\n\n"
            + "\n".join(steps) +
            f"\n\n经验沉淀: 本次修复中踩过的坑已记录到持续调优日志"
        )