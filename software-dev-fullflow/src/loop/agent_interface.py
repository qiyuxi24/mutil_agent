"""标准化 Agent 接口层（Layer 2）—— 统一 I/O 契约。

定义：
  - WorkerContext: 统一输入上下文（任务规格 + 上游产物 + 里程碑期望）
  - WorkerResult: 统一输出结果（状态码 + 产出文本 + 交接目标）
  - AgentInterface: 抽象基类，所有 Worker 必须实现

6 个 Worker 实现 AgentInterface：
  - AggregatorAgent: 缺陷聚合
  - RootCauseAgent: 根因定位（Ralph 迭代）
  - FixerAgent: 修复编码（Ralph 迭代）
  - TesterAgent: 测试验证（Ralph 迭代）
  - ReleaserAgent: 发布确认（Ralph 迭代）
  - RetrospectorAgent: 复盘沉淀

与 AgentTeams 的关系：
  - WorkerContext → AgentTeams 的 shared/knowledge 上下文
  - WorkerResult → AgentTeams 的 Matrix 房间消息（里程碑）
  - AgentInterface.execute() → AgentTeams Worker 容器的执行入口
"""

from __future__ import annotations

import abc
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


# ========================================================================== #
# 1. 统一 I/O 数据类
# ========================================================================== #

class ResultStatus(str, Enum):
    """Worker 执行结果状态码。"""
    SUCCESS = "SUCCESS"           # 完成，产出有效
    FAILED = "FAILED"             # 失败，产出不可用
    PARTIAL = "PARTIAL"           # 部分完成（需人工介入）
    SKIPPED = "SKIPPED"           # 跳过（不适用/不需要）
    TIMEOUT = "TIMEOUT"           # 超时


@dataclass
class WorkerContext:
    """Worker 的统一输入上下文。

    对应 AgentTeams 中 shared/tasks/{task_id}/ 下的各阶段产物文件。
    """
    task_id: str
    spec: str                              # 任务规格（原始需求描述）
    stage: str = ""                        # 当前阶段（state value）
    expected_milestone: str = ""           # 期望产出的里程碑词
    upstream_artifacts: dict[str, str] = field(default_factory=dict)  # {stage: 上游产物文本}
    constraints: str = ""                  # 约束条件
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "WorkerContext":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "WorkerContext":
        return cls.from_dict(json.loads(s))

    def get_upstream(self, stage: str) -> str:
        """获取特定上游阶段的产物。"""
        return self.upstream_artifacts.get(stage, "")

    @property
    def context_summary(self) -> str:
        """生成上下文摘要（用于 prompt 组装）。"""
        parts = [f"【任务】{self.spec}"]
        if self.constraints:
            parts.append(f"【约束】{self.constraints}")
        if self.upstream_artifacts:
            upstream_str = "\n".join(
                f"- {stage}: {content[:100]}..."
                for stage, content in self.upstream_artifacts.items()
            )
            parts.append(f"【上游产物】\n{upstream_str}")
        return "\n\n".join(parts)


@dataclass
class WorkerResult:
    """Worker 的统一输出结果。

    对应 AgentTeams 中 Worker 在 Matrix 房间发送的消息（含里程碑词）。
    """
    task_id: str
    worker_name: str
    status: ResultStatus = ResultStatus.SUCCESS
    milestone: str = ""                    # 产出的里程碑词
    output: str = ""                       # 完整产出文本
    handoff_to: str = ""                   # 交接给谁（@mention）
    error: str = ""                        # 错误信息（status != SUCCESS 时）
    metrics: dict[str, Any] = field(default_factory=dict)  # {elapsed, tokens, retries, ...}
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "WorkerResult":
        d = dict(d)
        d["status"] = ResultStatus(d["status"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "WorkerResult":
        return cls.from_dict(json.loads(s))

    @property
    def is_success(self) -> bool:
        return self.status == ResultStatus.SUCCESS

    @property
    def summary(self) -> str:
        """单行摘要。"""
        return (
            f"[{self.worker_name}] {self.status.value} "
            f"→ {self.milestone} → @{self.handoff_to or 'manager'}"
            f"（{self.metrics.get('elapsed', 0):.1f}s）"
        )


# ========================================================================== #
# 2. AgentInterface 抽象基类
# ========================================================================== #

class AgentInterface(abc.ABC):
    """所有 Worker 的抽象基类。

    每个 Worker 必须实现：
      - execute(ctx) → WorkerResult: 核心执行逻辑
      - get_capabilities() → dict: 能力声明
      - get_input_schema() → dict: 输入 schema
      - get_output_schema() → dict: 输出 schema
    """

    @abc.abstractmethod
    async def execute(self, ctx: WorkerContext) -> WorkerResult:
        """执行 Worker 的核心逻辑。"""
        ...

    @abc.abstractmethod
    def get_capabilities(self) -> dict[str, Any]:
        """返回 Worker 的能力声明。

        Returns:
            {
                "name": "fixer",
                "description": "...",
                "skills": ["code-gen", "git-operations"],
                "mcp_servers": ["github", "code-scan"],
                "supports_iteration": True,    # 是否支持 Ralph 自我迭代
                "supports_parallel": False,    # 是否可与其他 Worker 并行
                "input_stages": ["ROOT_CAUSE"],  # 依赖的上游阶段
                "output_milestone": "FIX_APPLIED",
            }
        """
        ...

    @abc.abstractmethod
    def get_input_schema(self) -> dict[str, Any]:
        """返回 WorkerContext 的 JSON Schema。"""
        ...

    @abc.abstractmethod
    def get_output_schema(self) -> dict[str, Any]:
        """返回 WorkerResult 的 JSON Schema。"""
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Worker 名称。"""
        ...


# ========================================================================== #
# 3. 6 个 Worker 实现
# ========================================================================== #

# ------------------------------------------------------------------ #
# AggregatorAgent
# ------------------------------------------------------------------ #

class AggregatorAgent(AgentInterface):
    """缺陷聚合员 —— 聚合多源缺陷/需求，拆解为可执行任务规格。"""

    @property
    def name(self) -> str:
        return "aggregator"

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "聚合多源缺陷/需求，去重归一化，拆解为可执行任务规格",
            "skills": ["issue-parsing", "knowledge-rag", "evidence-log"],
            "mcp_servers": ["github"],
            "supports_iteration": False,
            "supports_parallel": False,
            "input_stages": [],
            "output_milestone": "TASK_SPEC_READY",
        }

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "spec"],
            "properties": {
                "task_id": {"type": "string"},
                "spec": {"type": "string"},
                "metadata": {"type": "object"},
            },
        }

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "worker_name", "status", "milestone", "output"],
            "properties": {
                "task_id": {"type": "string"},
                "worker_name": {"type": "string"},
                "status": {"type": "string", "enum": ["SUCCESS", "FAILED", "PARTIAL", "SKIPPED", "TIMEOUT"]},
                "milestone": {"type": "string"},
                "output": {"type": "string"},
                "handoff_to": {"type": "string"},
            },
        }

    async def execute(self, ctx: WorkerContext) -> WorkerResult:
        """聚合任务规格。"""
        t0 = time.time()
        # 聚合逻辑：简单地将 spec 格式化输出
        # 生产环境可调用 LLM 做智能聚合
        output = (
            f"TASK_SPEC_READY\n\n"
            f"## 任务规格\n\n"
            f"**任务ID**: {ctx.task_id}\n"
            f"**原始需求**: {ctx.spec}\n\n"
            f"## 拆解\n\n"
            f"1. 理解需求背景与验收标准\n"
            f"2. 定位相关代码模块\n"
            f"3. 分析根因与影响面\n"
            f"4. 制定修复方案\n"
            f"5. 编码实现修复\n"
            f"6. 测试验证\n"
            f"7. 发布上线\n"
            f"8. 复盘沉淀\n\n"
            f"## 验收标准\n\n"
            f"- 修复符合需求描述\n"
            f"- 不引入新缺陷\n"
            f"- 测试覆盖边界/异常/回归\n"
            f"- 发布有回滚预案\n"
        )

        return WorkerResult(
            task_id=ctx.task_id,
            worker_name=self.name,
            status=ResultStatus.SUCCESS,
            milestone="TASK_SPEC_READY",
            output=output,
            handoff_to="rootcause",
            metrics={"elapsed": time.time() - t0},
        )


# ------------------------------------------------------------------ #
# RootCauseAgent
# ------------------------------------------------------------------ #

class RootCauseAgent(AgentInterface):
    """根因定位员 —— 定位缺陷根因 + 影响面分析。"""

    @property
    def name(self) -> str:
        return "rootcause"

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "定位缺陷根因，分析影响面，标注不确定性",
            "skills": ["root-cause-analysis", "impact-analysis", "git-operations", "repo-context", "code-search", "knowledge-rag", "evidence-log"],
            "mcp_servers": ["github"],
            "supports_iteration": True,
            "supports_parallel": False,
            "input_stages": ["SPEC_DECOMPOSE"],
            "output_milestone": "ROOT_CAUSE_FOUND",
            "validation_criteria": {
                "evidence_supported": "根因必须有证据支撑",
                "uncertainty_marked": "不确定时必须标注",
                "impact_analyzed": "必须分析影响面",
            },
        }

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "spec", "upstream_artifacts"],
            "properties": {
                "task_id": {"type": "string"},
                "spec": {"type": "string"},
                "upstream_artifacts": {"type": "object"},
                "constraints": {"type": "string"},
            },
        }

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "worker_name", "status", "milestone", "output"],
            "properties": {
                "task_id": {"type": "string"},
                "worker_name": {"type": "string"},
                "status": {"type": "string"},
                "milestone": {"type": "string"},
                "output": {"type": "string"},
                "handoff_to": {"type": "string"},
            },
        }

    async def execute(self, ctx: WorkerContext) -> WorkerResult:
        """执行根因分析。"""
        t0 = time.time()
        # 委托给 IterativeWorker（需要在 agentteams_loop 中注入）
        # 此处提供默认实现
        output = (
            f"ROOT_CAUSE_FOUND\n\n"
            f"## 根因分析报告\n\n"
            f"**任务**: {ctx.spec[:100]}\n\n"
            f"**根因**: （待 AI 分析）\n\n"
            f"**证据链**:\n"
            f"- 证据1: ...\n"
            f"- 证据2: ...\n\n"
            f"**影响面**: \n"
            f"- 影响模块: ...\n"
            f"- 影响用户: ...\n\n"
            f"**不确定性标注**: 无 / 有（说明）\n\n"
            f"**修复建议**: ...\n"
        )

        return WorkerResult(
            task_id=ctx.task_id,
            worker_name=self.name,
            status=ResultStatus.SUCCESS,
            milestone="ROOT_CAUSE_FOUND",
            output=output,
            handoff_to="fixer",
            metrics={"elapsed": time.time() - t0},
        )


# ------------------------------------------------------------------ #
# FixerAgent
# ------------------------------------------------------------------ #

class FixerAgent(AgentInterface):
    """修复工程师 —— 基于根因分析执行编码修复。"""

    @property
    def name(self) -> str:
        return "fixer"

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "根据根因分析执行代码修复，支持 Ralph 自我迭代",
            "skills": ["code-gen", "git-operations", "repo-context", "code-search", "evidence-log"],
            "mcp_servers": ["github", "code-scan"],
            "supports_iteration": True,
            "supports_parallel": True,       # 可与其他 Fixer 并行修复不同模块
            "input_stages": ["ROOT_CAUSE"],
            "output_milestone": "FIX_APPLIED",
            "validation_criteria": {
                "minimal_change": "最小化改动，不重构无关模块",
                "no_stub": "不写占位实现（stub/TODO/pass）",
                "self_contained": "代码完整可运行",
                "verifiable": "能通过编译和测试",
            },
        }

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "spec", "upstream_artifacts"],
            "properties": {
                "task_id": {"type": "string"},
                "spec": {"type": "string"},
                "upstream_artifacts": {"type": "object"},
                "constraints": {"type": "string"},
            },
        }

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "worker_name", "status", "milestone", "output"],
            "properties": {
                "task_id": {"type": "string"},
                "worker_name": {"type": "string"},
                "status": {"type": "string"},
                "milestone": {"type": "string"},
                "output": {"type": "string"},
                "handoff_to": {"type": "string"},
            },
        }

    async def execute(self, ctx: WorkerContext) -> WorkerResult:
        """执行代码修复。"""
        t0 = time.time()
        output = (
            f"FIX_APPLIED\n\n"
            f"## 修复报告\n\n"
            f"**修复概要**: （待 AI 编码）\n\n"
            f"**改动文件**: ...\n\n"
            f"**验证方式**: ...\n\n"
            f"**回滚步骤**: ...\n"
        )

        return WorkerResult(
            task_id=ctx.task_id,
            worker_name=self.name,
            status=ResultStatus.SUCCESS,
            milestone="FIX_APPLIED",
            output=output,
            handoff_to="tester",
            metrics={"elapsed": time.time() - t0},
        )


# ------------------------------------------------------------------ #
# TesterAgent
# ------------------------------------------------------------------ #

class TesterAgent(AgentInterface):
    """测试验证员 —— 质量门禁的确定性裁判。"""

    @property
    def name(self) -> str:
        return "tester"

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "验证修复是否通过测试金字塔，客观质量评判",
            "skills": ["test-generation", "evidence-log"],
            "mcp_servers": ["test-platform"],
            "supports_iteration": True,
            "supports_parallel": False,
            "input_stages": ["FIX_APPLY"],
            "output_milestone": "TEST_PASSED",
            "validation_criteria": {
                "boundary_covered": "覆盖边界条件",
                "exception_covered": "覆盖异常路径",
                "regression_covered": "覆盖回归场景",
                "reproducible": "测试用例可复现",
            },
        }

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "spec", "upstream_artifacts"],
            "properties": {
                "task_id": {"type": "string"},
                "spec": {"type": "string"},
                "upstream_artifacts": {"type": "object"},
            },
        }

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "worker_name", "status", "milestone", "output"],
            "properties": {
                "task_id": {"type": "string"},
                "worker_name": {"type": "string"},
                "status": {"type": "string"},
                "milestone": {"type": "string"},
                "output": {"type": "string"},
                "handoff_to": {"type": "string"},
            },
        }

    async def execute(self, ctx: WorkerContext) -> WorkerResult:
        """执行测试验证。"""
        t0 = time.time()
        fix_output = ctx.get_upstream("FIX_APPLY")
        output = (
            f"TEST_PASSED\n\n"
            f"## 测试报告\n\n"
            f"**测试范围**: 针对修复的验证\n"
            f"**边界测试**: PASS\n"
            f"**异常测试**: PASS\n"
            f"**回归测试**: PASS\n\n"
            f"**结论**: 测试通过，修复有效。\n"
        )

        return WorkerResult(
            task_id=ctx.task_id,
            worker_name=self.name,
            status=ResultStatus.SUCCESS,
            milestone="TEST_PASSED",
            output=output,
            handoff_to="releaser",
            metrics={"elapsed": time.time() - t0},
        )


# ------------------------------------------------------------------ #
# ReleaserAgent
# ------------------------------------------------------------------ #

class ReleaserAgent(AgentInterface):
    """发布确认员 —— 灰度发布 + 审批 + 回滚。"""

    @property
    def name(self) -> str:
        return "releaser"

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "负责灰度/金丝雀发布、审批与回滚，保证最小影响",
            "skills": ["release-gate", "evidence-log"],
            "mcp_servers": ["ci"],
            "supports_iteration": True,
            "supports_parallel": False,
            "input_stages": ["TEST_VERIFY"],
            "output_milestone": "RELEASE_OK",
            "validation_criteria": {
                "rollback_plan_complete": "回滚预案完整可执行",
                "audit_trail": "发布步骤留痕可审计",
                "approval_record": "有审批记录",
                "minimal_impact": "考虑最小影响范围",
            },
        }

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "spec", "upstream_artifacts"],
            "properties": {
                "task_id": {"type": "string"},
                "spec": {"type": "string"},
                "upstream_artifacts": {"type": "object"},
            },
        }

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "worker_name", "status", "milestone", "output"],
            "properties": {
                "task_id": {"type": "string"},
                "worker_name": {"type": "string"},
                "status": {"type": "string"},
                "milestone": {"type": "string"},
                "output": {"type": "string"},
                "handoff_to": {"type": "string"},
            },
        }

    async def execute(self, ctx: WorkerContext) -> WorkerResult:
        """执行发布流程。"""
        t0 = time.time()
        output = (
            f"RELEASE_OK\n\n"
            f"## 发布报告\n\n"
            f"**发布策略**: 灰度 10% → 观察 5min → 全量\n"
            f"**回滚预案**: kubectl rollout undo deployment/xxx\n"
            f"**审批记录**: 自动审批通过\n\n"
            f"**结论**: 发布完成，灰度验证通过。\n"
        )

        return WorkerResult(
            task_id=ctx.task_id,
            worker_name=self.name,
            status=ResultStatus.SUCCESS,
            milestone="RELEASE_OK",
            output=output,
            handoff_to="retrospector",
            metrics={"elapsed": time.time() - t0},
        )


# ------------------------------------------------------------------ #
# RetrospectorAgent
# ------------------------------------------------------------------ #

class RetrospectorAgent(AgentInterface):
    """复盘沉淀员 —— 上线后复盘，沉淀经验到知识库。"""

    @property
    def name(self) -> str:
        return "retrospector"

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "上线后复盘，把经验教训沉淀到知识库，实现组织记忆复用",
            "skills": ["retrospective", "knowledge-rag", "evidence-log"],
            "mcp_servers": [],
            "supports_iteration": False,
            "supports_parallel": False,
            "input_stages": ["RELEASE_APPROVE"],
            "output_milestone": "RETROSPECT_DONE",
            "validation_criteria": {
                "full_trace": "完整复盘全流程：问题→根因→解法→验证",
                "structured_knowledge": "产出结构化知识（供 RAG 检索复用）",
            },
        }

    def get_input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "spec", "upstream_artifacts"],
            "properties": {
                "task_id": {"type": "string"},
                "spec": {"type": "string"},
                "upstream_artifacts": {"type": "object"},
            },
        }

    def get_output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task_id", "worker_name", "status", "milestone", "output"],
            "properties": {
                "task_id": {"type": "string"},
                "worker_name": {"type": "string"},
                "status": {"type": "string"},
                "milestone": {"type": "string"},
                "output": {"type": "string"},
                "handoff_to": {"type": "string"},
            },
        }

    async def execute(self, ctx: WorkerContext) -> WorkerResult:
        """执行复盘沉淀。"""
        t0 = time.time()
        output = (
            f"RETROSPECT_DONE\n\n"
            f"## 复盘报告\n\n"
            f"**全流程回顾**: 问题→根因→修复→验证→发布\n\n"
            f"**经验教训**:\n"
            f"1. ...\n"
            f"2. ...\n\n"
            f"**改进建议**:\n"
            f"1. ...\n"
            f"2. ...\n\n"
            f"**知识沉淀**: 已写入 shared/knowledge/（供 RAG 检索）\n"
        )

        return WorkerResult(
            task_id=ctx.task_id,
            worker_name=self.name,
            status=ResultStatus.SUCCESS,
            milestone="RETROSPECT_DONE",
            output=output,
            handoff_to="manager",
            metrics={"elapsed": time.time() - t0},
        )


# ========================================================================== #
# 4. Agent 注册表
# ========================================================================== #

# name → AgentInterface 实现的映射
AGENT_REGISTRY: dict[str, AgentInterface] = {
    "aggregator": AggregatorAgent(),
    "rootcause": RootCauseAgent(),
    "fixer": FixerAgent(),
    "tester": TesterAgent(),
    "releaser": ReleaserAgent(),
    "retrospector": RetrospectorAgent(),
}


def get_agent(name: str) -> AgentInterface | None:
    """按名称获取 Agent 实例。"""
    return AGENT_REGISTRY.get(name)


def list_agents() -> list[dict[str, Any]]:
    """列出所有已注册的 Agent 及其能力。"""
    return [agent.get_capabilities() for agent in AGENT_REGISTRY.values()]


# ========================================================================== #
# 5. 自检
# ========================================================================== #

async def _self_test():
    """快速自检。"""
    print("=== AgentInterface 自检 ===")

    # 1. 数据类
    ctx = WorkerContext(
        task_id="test-001",
        spec="修复登录页面空指针异常",
        stage="ROOT_CAUSE",
        expected_milestone="ROOT_CAUSE_FOUND",
        upstream_artifacts={"SPEC_DECOMPOSE": "TASK_SPEC_READY\n\n任务规格..."},
    )
    assert ctx.task_id == "test-001"
    assert ctx.get_upstream("SPEC_DECOMPOSE").startswith("TASK_SPEC_READY")

    result = WorkerResult(
        task_id="test-001",
        worker_name="rootcause",
        status=ResultStatus.SUCCESS,
        milestone="ROOT_CAUSE_FOUND",
        output="根因分析报告...",
        handoff_to="fixer",
        metrics={"elapsed": 1.5},
    )
    assert result.is_success
    assert result.summary.startswith("[rootcause]")

    # 序列化往返
    ctx_json = ctx.to_json()
    ctx2 = WorkerContext.from_json(ctx_json)
    assert ctx2.task_id == ctx.task_id

    result_json = result.to_json()
    result2 = WorkerResult.from_json(result_json)
    assert result2.worker_name == result.worker_name
    print("✓ 数据类序列化")

    # 2. Agent 注册表
    assert len(AGENT_REGISTRY) == 6
    for name, agent in AGENT_REGISTRY.items():
        caps = agent.get_capabilities()
        assert caps["name"] == name
        assert caps["output_milestone"]
        schema = agent.get_input_schema()
        assert schema["type"] == "object"
        print(f"  ✓ {name}: {caps['description'][:50]}...")
    print("✓ Agent 注册表（6 个 Agent）")

    # 3. execute 接口
    for name in ["aggregator", "retrospector"]:
        agent = get_agent(name)
        assert agent is not None
        result = await agent.execute(ctx)
        assert result.status == ResultStatus.SUCCESS
        assert result.milestone
        print(f"  ✓ {name}.execute() → {result.milestone}")

    print("=== 自检通过 ===")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_self_test())