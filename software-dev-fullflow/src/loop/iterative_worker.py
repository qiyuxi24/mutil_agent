"""通用 IterativeWorker 基类 —— Ralph 自我迭代机制抽象。

从 fixer_loop.py 的 FixerLoop 提取通用 Ralph 迭代模式，让所有 Worker 都支持：
  - 生成计划 → 执行步骤 → 自我校验 → 修正 → 最终审查

每个 Worker 覆写 `_validate_step()` 实现角色特定校验：
  - RootCause: 校验根因是否有证据支撑、是否标注不确定性
  - Tester: 校验测试是否覆盖边界/异常/回归
  - Releaser: 校验回滚预案是否完整

Ralph 五大原则落地：
  1. 一次循环只做一件事   → 按 plan 拆成原子步骤
  2. 规格驱动（Spec）     → 读上游产物当蓝图
  3. 子代理并行           → 校验用独立 Agent 调用
  4. 反压机制（Backpressure）→ 校验 Agent 当客观裁判
  5. 持续调优             → 错误反馈写回上下文

硬约束：
  - 单步最多重试 3 次
  - 总迭代上限 20 次
  - 上下文 70/30 分配
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loop.context import ContextBudget, TokenEstimator, offload_to_file as ctx_offload


# ------------------------------------------------------------------ #
# 数据结构
# ------------------------------------------------------------------ #

@dataclass
class WorkStep:
    """一个原子工作步骤。"""
    index: int
    description: str            # 这一步要做什么
    target_file: str = ""
    status: str = "pending"     # pending | in_progress | done | failed
    retries: int = 0
    error_feedback: str = ""


@dataclass
class WorkPlan:
    """通用工作计划。"""
    summary: str
    steps: list[WorkStep] = field(default_factory=list)
    constraints: str = ""
    rollback: str = ""


# ------------------------------------------------------------------ #
# IterativeWorker —— 通用 Ralph 迭代基类
# ------------------------------------------------------------------ #

class IterativeWorker(abc.ABC):
    """通用 Ralph 式自我迭代引擎。

    子类需覆写：
      - _validate_step(): 角色特定的校验逻辑
      - worker_name(): 返回 Worker 标识
      - _plan_prompt(): 生成计划的 prompt 模板
      - _execute_prompt(): 执行步骤的 prompt 模板
      - _review_prompt(): 最终审查的 prompt 模板

    用法：
        class MyWorker(IterativeWorker):
            def worker_name(self) -> str:
                return "my_worker"

            async def _validate_step(self, step, plan, output, context):
                # 角色特定校验逻辑
                ...
    """

    MAX_STEPS = 8
    MAX_RETRIES_PER_STEP = 3
    MAX_TOTAL_ITERATIONS = 20
    STEP_BUDGET = 8000

    def __init__(self, workdir: Path, mock: bool = False):
        self.workdir = workdir
        self.mock = mock
        self._total_iterations = 0
        self._error_log: list[str] = []

    # ------------------------------------------------------------------ #
    # 公开入口
    # ------------------------------------------------------------------ #

    async def run(self, context: str, milestone: str = "") -> str:
        """运行 Ralph 式自我迭代，返回最终产物。

        子类可覆写此方法以自定义迭代流程。
        """
        if self.mock:
            return self._mock_run(context, milestone)

        t0 = time.time()
        name = self.worker_name()
        print(f"  [{name}] Ralph 自我迭代启动（上下文 {len(context)} 字符）")

        plan = await self._generate_plan(context)
        if not plan.steps:
            return self._fail("无法生成工作计划（plan 为空）")

        print(f"  [{name}] 计划: {len(plan.steps)} 步，概要: {plan.summary[:80]}")

        all_outputs: list[str] = []
        for step in plan.steps:
            self._check_total_limit()
            step.status = "in_progress"

            result = await self._execute_step(step, plan, context, all_outputs)
            if result.startswith(f"{name.upper()}_FAILED"):
                return self._fail(f"步骤 {step.index + 1}/{len(plan.steps)} 失败: {result}")

            all_outputs.append(result)
            step.status = "done"

        final_output = await self._final_review(plan, all_outputs, context)
        if final_output.startswith(f"{name.upper()}_FAILED"):
            return final_output

        elapsed = time.time() - t0
        print(f"  [{name}] Ralph 自我迭代完成（{elapsed:.1f}s，{self._total_iterations} 次调用，{len(plan.steps)} 步）")
        if self._error_log:
            print(f"  [{name}] 持续调优记录: {len(self._error_log)} 条经验")

        return f"{milestone}\n\n{final_output}" if milestone else final_output

    # ------------------------------------------------------------------ #
    # 子类需覆写的方法
    # ------------------------------------------------------------------ #

    @abc.abstractmethod
    def worker_name(self) -> str:
        """Worker 标识名。"""
        ...

    @abc.abstractmethod
    async def _validate_step(
        self, step: WorkStep, plan: WorkPlan, output: str, context: str
    ) -> tuple[str, str]:
        """角色特定的校验逻辑。

        Returns:
            (verdict, feedback): verdict 为 PASS / FAIL
        """
        ...

    @abc.abstractmethod
    def _plan_prompt(self, context: str) -> str:
        """生成计划的 prompt。"""
        ...

    @abc.abstractmethod
    def _execute_prompt(self) -> str:
        """执行步骤的 prompt 模板。"""
        ...

    @abc.abstractmethod
    def _review_prompt(self) -> str:
        """最终审查的 prompt 模板。"""
        ...

    @abc.abstractmethod
    async def _call_model(self, system_prompt: str, user_prompt: str) -> str:
        """调用 LLM 模型。子类实现具体的 API 调用。"""
        ...

    # ------------------------------------------------------------------ #
    # 通用实现：生成计划
    # ------------------------------------------------------------------ #

    async def _generate_plan(self, context: str) -> WorkPlan:
        """基于上下文生成工作计划（原子步骤拆分）。"""
        prompt = self._plan_prompt(context)
        result = await self._call_model(
            system_prompt=f"你是 {self.worker_name()}，负责制定工作计划，只做规划不做执行。",
            user_prompt=prompt,
        )
        return self._parse_plan(result)

    def _parse_plan(self, text: str) -> WorkPlan:
        """从 LLM 输出中解析工作计划。"""
        plan = WorkPlan(summary="")
        lines = text.split("\n")
        section = ""
        step_idx = 0

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## 概要") or stripped.startswith("## 计划概要"):
                section = "summary"
                continue
            if stripped.startswith("## 约束"):
                section = "constraints"
                continue
            if stripped.startswith("## 回滚"):
                section = "rollback"
                continue
            if stripped.startswith("## 步骤") or stripped.startswith("## 原子步骤"):
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
                if stripped[0].isdigit():
                    desc = stripped.split(".", 1)[-1].strip()
                    target_file = ""
                    if "目标文件:" in desc or "目标文件：" in desc:
                        parts = desc.split("目标文件:") if "目标文件:" in desc else desc.split("目标文件：")
                        desc = parts[0].strip().rstrip("—").strip().rstrip("-").strip()
                        target_file = parts[1].strip() if len(parts) > 1 else ""
                    plan.steps.append(WorkStep(index=step_idx, description=desc, target_file=target_file))
                    step_idx += 1

        plan.summary = plan.summary.strip()
        plan.constraints = plan.constraints.strip()
        plan.rollback = plan.rollback.strip()

        if not plan.steps:
            plan.steps = [WorkStep(index=0, description="执行完整工作（按上下文和规格）")]
        if not plan.summary:
            plan.summary = "按上下文执行工作"

        return plan

    # ------------------------------------------------------------------ #
    # 通用实现：执行单个步骤
    # ------------------------------------------------------------------ #

    async def _execute_step(
        self, step: WorkStep, plan: WorkPlan, context: str, previous_outputs: list[str]
    ) -> str:
        """执行一个原子步骤，内带 Ralph 反压循环。"""
        prev_context = "\n\n".join(previous_outputs) if previous_outputs else "（无前置步骤）"

        tuning_rules = ""
        if self._error_log:
            tuning_rules = "【已踩过的坑（禁止再犯）】\n" + "\n".join(
                f"- {e}" for e in self._error_log[-5:]
            ) + "\n\n"

        while step.retries < self.MAX_RETRIES_PER_STEP:
            self._check_total_limit()

            budget = ContextBudget(total_budget=self.STEP_BUDGET)

            task_header = (
                f"你是 {self.worker_name()}，正在执行工作计划的第 {step.index + 1}/{len(plan.steps)} 步。\n\n"
                f"【计划概要】{plan.summary}\n"
                f"【约束条件】{plan.constraints or '无特殊约束'}\n"
                f"【当前步骤】{step.description}\n"
                f"{'【目标文件】' + step.target_file if step.target_file else ''}\n\n"
            )
            budget.allocate_critical(task_header)
            budget.allocate_critical(f"【原始上下文】\n{context[:2000]}\n\n")
            budget.allocate_support(f"【前置步骤产出】\n{prev_context[:1500]}\n\n")

            if tuning_rules:
                budget.allocate_support(tuning_rules)

            error_context = ""
            if step.error_feedback:
                error_context = (
                    f"\n【上轮校验失败——请修正以下问题】\n{step.error_feedback}\n"
                    f"请针对以上问题修改，不要引入无关改动。\n"
                )
                budget.allocate_support(error_context)

            task_instruction = self._execute_prompt().format(
                step_index=step.index + 1,
                total_steps=len(plan.steps),
            )
            budget.allocate_critical(task_instruction)

            prompt = f"{budget.critical.content}\n\n---\n\n{budget.support.content}"

            output = await self._call_model(
                system_prompt=f"你是 {self.worker_name()}，负责执行具体工作。",
                user_prompt=prompt,
            )
            self._total_iterations += 1

            prompt_tokens = TokenEstimator.estimate(prompt)
            output_tokens = TokenEstimator.estimate(output)
            print(f"  [{self.worker_name()}] 步骤 {step.index + 1} prompt: {prompt_tokens}t, "
                  f"budget util: {budget.utilization:.0%}")

            verdict, feedback = await self._validate_step(step, plan, output, context)

            if verdict == "PASS":
                return output

            step.retries += 1
            step.error_feedback = feedback
            self._error_log.append(f"[步骤{step.index + 1}] {feedback[:200]}")
            print(f"  [{self.worker_name()}] 步骤 {step.index + 1} 校验失败（第 {step.retries} 次），反馈: {feedback[:100]}")

        return f"{self.worker_name().upper()}_FAILED: 步骤 {step.index + 1} 重试 {self.MAX_RETRIES_PER_STEP} 次仍失败。最后反馈: {step.error_feedback[:200]}"

    # ------------------------------------------------------------------ #
    # 通用实现：最终审查
    # ------------------------------------------------------------------ #

    async def _final_review(
        self, plan: WorkPlan, step_outputs: list[str], context: str
    ) -> str:
        """所有步骤完成后，进行一次整体审查。"""
        combined = "\n\n---\n\n".join(
            f"步骤 {i + 1}:\n{out[:1500]}" for i, out in enumerate(step_outputs)
        )

        prompt = self._review_prompt().format(
            summary=plan.summary,
            constraints=plan.constraints or "无",
            rollback=plan.rollback or "无",
            combined=combined,
        )

        result = await self._call_model(
            system_prompt=f"你是 {self.worker_name()}，已完成所有步骤，请做最终整合审查。",
            user_prompt=prompt,
        )
        self._total_iterations += 1

        if f"{self.worker_name().upper()}_FAILED" in result.upper():
            return f"{self.worker_name().upper()}_FAILED: 最终审查未通过: {result[:200]}"
        return result

    # ------------------------------------------------------------------ #
    # 辅助方法
    # ------------------------------------------------------------------ #

    def _check_total_limit(self) -> None:
        if self._total_iterations >= self.MAX_TOTAL_ITERATIONS:
            raise RuntimeError(
                f"{self.worker_name()} 超过总迭代上限 {self.MAX_TOTAL_ITERATIONS}，"
                f"最后 {len(self._error_log)} 条错误: {self._error_log[-3:]}"
            )

    def _fail(self, reason: str) -> str:
        return f"{self.worker_name().upper()}_FAILED: {reason}"

    def _mock_run(self, context: str, milestone: str) -> str:
        """Mock 模式：确定性假实现。"""
        print(f"  [{self.worker_name()}] mock 模式：模拟 Ralph 3 步迭代")
        name = self.worker_name()
        steps = [
            f"STEP_1_DONE: {name} 核心工作（mock）",
            f"STEP_2_DONE: {name} 验证工作（mock）",
            f"STEP_3_DONE: {name} 边界处理（mock）",
        ]
        return (
            f"{milestone}\n\n"
            f"## {name} 工作报告（Ralph 自我迭代 · mock）\n\n"
            f"概要: 基于上下文执行工作\n"
            f"迭代步骤: {len(steps)} 步\n"
            f"校验轮次: 每步 1 轮（mock 全部通过）\n\n"
            + "\n".join(steps) +
            f"\n\n经验沉淀: 本次工作中踩过的坑已记录到持续调优日志"
        )


# ------------------------------------------------------------------ #
# 预置子类：RootCause 校验
# ------------------------------------------------------------------ #

class RootCauseWorker(IterativeWorker):
    """根因定位 Worker —— 校验根因是否有证据支撑、是否标注不确定性。"""

    def worker_name(self) -> str:
        return "rootcause"

    def _plan_prompt(self, context: str) -> str:
        return (
            "你是根因定位员，需要为缺陷分析制定分析计划。\n\n"
            f"【上下文】\n{context}\n\n"
            "请按以下格式输出分析计划：\n\n"
            "## 概要\n（一句话描述分析思路）\n\n"
            "## 约束\n（分析中不能忽略的边界条件）\n\n"
            "## 步骤\n"
            "1. [步骤描述] — 目标文件: xxx\n"
            "2. [步骤描述] — 目标文件: xxx\n\n"
            "规则：每个步骤必须是原子化的，最多 {MAX} 步。\n"
        ).replace("{MAX}", str(self.MAX_STEPS))

    def _execute_prompt(self) -> str:
        return (
            "请输出这一步的分析结果，只做这一步的事。\n"
            "完成后请标注: STEP_{step_index}_DONE"
        )

    def _review_prompt(self) -> str:
        return (
            "你已完成所有分析步骤。请做最终整合审查。\n\n"
            "【计划概要】{summary}\n"
            "【约束条件】{constraints}\n\n"
            "【所有步骤产出】\n{combined}\n\n"
            "请整合所有步骤的产出，输出一份完整的根因分析报告：\n"
            "1. 根因是什么（一句话）\n"
            "2. 证据链（逐条列出）\n"
            "3. 影响面分析\n"
            "4. 不确定性标注（如有）\n"
            "5. 修复建议\n\n"
            "确保报告完整、有证据支撑、不确定性明确标注。"
        )

    async def _validate_step(
        self, step: WorkStep, plan: WorkPlan, output: str, context: str
    ) -> tuple[str, str]:
        """校验根因分析步骤：检查是否有证据支撑、是否标注不确定性。"""
        code_snippet = output
        if TokenEstimator.estimate(output) > 2000:
            offload_path = self.workdir / f"rootcause_step_{step.index + 1}_output.md"
            ctx_offload(output, offload_path)
            code_snippet = f"[完整内容已卸载至: {offload_path.name}]\n{output[:500]}..."

        validate_prompt = (
            "你是根因分析审查员，只做客观评判。\n\n"
            "请对以下根因分析步骤做严格审查：\n\n"
            f"【分析概要】{plan.summary}\n"
            f"【当前步骤】{step.description}\n\n"
            f"【分析产出】\n{code_snippet}\n\n"
            "审查标准：\n"
            "1. 是否有证据支撑？（无证据的猜测 = FAIL）\n"
            "2. 是否标注了不确定性？（不确定但未标注 = FAIL）\n"
            "3. 逻辑是否自洽？\n"
            "4. 是否引入了无关分析？\n\n"
            "输出格式：\n"
            "PASS: <通过理由>\n"
            "FAIL: <失败原因，指出哪条标准未通过>"
        )

        result = await self._call_model(
            system_prompt="你是严格的根因分析审查员，只输出 PASS 或 FAIL。",
            user_prompt=validate_prompt,
        )
        self._total_iterations += 1

        if result.strip().upper().startswith("PASS"):
            return "PASS", result.strip()
        return "FAIL", result.strip()


# ------------------------------------------------------------------ #
# 预置子类：Tester 校验
# ------------------------------------------------------------------ #

class TesterWorker(IterativeWorker):
    """测试验证 Worker —— 校验测试是否覆盖边界/异常/回归。"""

    def worker_name(self) -> str:
        return "tester"

    def _plan_prompt(self, context: str) -> str:
        return (
            "你是测试验证员，需要为代码修复制定测试计划。\n\n"
            f"【上下文】\n{context}\n\n"
            "请按以下格式输出测试计划：\n\n"
            "## 概要\n（一句话描述测试策略）\n\n"
            "## 约束\n（测试环境限制、不能测的模块）\n\n"
            "## 步骤\n"
            "1. [步骤描述] — 目标文件: xxx\n"
            "2. [步骤描述] — 目标文件: xxx\n\n"
            "规则：覆盖边界、异常、回归三个维度，每步原子化。最多 {MAX} 步。\n"
        ).replace("{MAX}", str(self.MAX_STEPS))

    def _execute_prompt(self) -> str:
        return (
            "请输出这一步的测试用例/测试结果，只做这一步的事。\n"
            "完成后请标注: STEP_{step_index}_DONE"
        )

    def _review_prompt(self) -> str:
        return (
            "你已完成所有测试步骤。请做最终整合审查。\n\n"
            "【计划概要】{summary}\n"
            "【约束条件】{constraints}\n\n"
            "【所有步骤产出】\n{combined}\n\n"
            "请整合所有步骤的产出，输出一份完整的测试报告：\n"
            "1. 测试覆盖总结\n"
            "2. 边界测试结果\n"
            "3. 异常测试结果\n"
            "4. 回归测试结果\n"
            "5. 结论 PASS / FAIL\n\n"
            "确保报告完整、可复现。"
        )

    async def _validate_step(
        self, step: WorkStep, plan: WorkPlan, output: str, context: str
    ) -> tuple[str, str]:
        """校验测试步骤：检查是否覆盖边界/异常/回归。"""
        code_snippet = output
        if TokenEstimator.estimate(output) > 2000:
            offload_path = self.workdir / f"tester_step_{step.index + 1}_output.md"
            ctx_offload(output, offload_path)
            code_snippet = f"[完整内容已卸载至: {offload_path.name}]\n{output[:500]}..."

        validate_prompt = (
            "你是测试审查员，只做客观评判。\n\n"
            "请对以下测试步骤做严格审查：\n\n"
            f"【测试概要】{plan.summary}\n"
            f"【当前步骤】{step.description}\n\n"
            f"【测试产出】\n{code_snippet}\n\n"
            "审查标准：\n"
            "1. 是否覆盖了边界条件？（未覆盖 = FAIL）\n"
            "2. 是否覆盖了异常路径？（未覆盖 = FAIL）\n"
            "3. 是否覆盖了回归场景？（未覆盖 = FAIL）\n"
            "4. 测试用例是否可复现？\n\n"
            "输出格式：\n"
            "PASS: <通过理由>\n"
            "FAIL: <失败原因，指出哪条标准未通过>"
        )

        result = await self._call_model(
            system_prompt="你是严格的测试审查员，只输出 PASS 或 FAIL。",
            user_prompt=validate_prompt,
        )
        self._total_iterations += 1

        if result.strip().upper().startswith("PASS"):
            return "PASS", result.strip()
        return "FAIL", result.strip()


# ------------------------------------------------------------------ #
# 预置子类：Releaser 校验
# ------------------------------------------------------------------ #

class ReleaserWorker(IterativeWorker):
    """发布确认 Worker —— 校验回滚预案是否完整。"""

    def worker_name(self) -> str:
        return "releaser"

    def _plan_prompt(self, context: str) -> str:
        return (
            "你是发布确认员，需要为修复发布制定发布计划。\n\n"
            f"【上下文】\n{context}\n\n"
            "请按以下格式输出发布计划：\n\n"
            "## 概要\n（一句话描述发布策略）\n\n"
            "## 约束\n（发布限制、不能动的配置）\n\n"
            "## 回滚预案\n（如果发布失败，如何回滚）\n\n"
            "## 步骤\n"
            "1. [步骤描述]\n"
            "2. [步骤描述]\n\n"
            "规则：每步原子化，最多 {MAX} 步。\n"
        ).replace("{MAX}", str(self.MAX_STEPS))

    def _execute_prompt(self) -> str:
        return (
            "请输出这一步的发布操作，只做这一步的事。\n"
            "完成后请标注: STEP_{step_index}_DONE"
        )

    def _review_prompt(self) -> str:
        return (
            "你已完成所有发布步骤。请做最终整合审查。\n\n"
            "【计划概要】{summary}\n"
            "【约束条件】{constraints}\n"
            "【回滚预案】{rollback}\n\n"
            "【所有步骤产出】\n{combined}\n\n"
            "请整合所有步骤的产出，输出一份完整的发布报告：\n"
            "1. 发布策略（灰度/金丝雀/全量）\n"
            "2. 发布步骤记录\n"
            "3. 回滚预案（完整可执行）\n"
            "4. 审批记录\n"
            "5. 结论 RELEASE_OK / RELEASE_ROLLED_BACK\n\n"
            "确保报告完整、回滚预案可执行。"
        )

    async def _validate_step(
        self, step: WorkStep, plan: WorkPlan, output: str, context: str
    ) -> tuple[str, str]:
        """校验发布步骤：检查回滚预案是否完整。"""
        code_snippet = output
        if TokenEstimator.estimate(output) > 2000:
            offload_path = self.workdir / f"releaser_step_{step.index + 1}_output.md"
            ctx_offload(output, offload_path)
            code_snippet = f"[完整内容已卸载至: {offload_path.name}]\n{output[:500]}..."

        validate_prompt = (
            "你是发布审查员，只做客观评判。\n\n"
            "请对以下发布步骤做严格审查：\n\n"
            f"【发布概要】{plan.summary}\n"
            f"【回滚预案】{plan.rollback or '未提供'}\n"
            f"【当前步骤】{step.description}\n\n"
            f"【发布产出】\n{code_snippet}\n\n"
            "审查标准：\n"
            "1. 回滚预案是否完整可执行？（不完整 = FAIL）\n"
            "2. 发布步骤是否留痕可审计？\n"
            "3. 是否有审批记录？\n"
            "4. 是否考虑了最小影响范围？\n\n"
            "输出格式：\n"
            "PASS: <通过理由>\n"
            "FAIL: <失败原因，指出哪条标准未通过>"
        )

        result = await self._call_model(
            system_prompt="你是严格的发布审查员，只输出 PASS 或 FAIL。",
            user_prompt=validate_prompt,
        )
        self._total_iterations += 1

        if result.strip().upper().startswith("PASS"):
            return "PASS", result.strip()
        return "FAIL", result.strip()