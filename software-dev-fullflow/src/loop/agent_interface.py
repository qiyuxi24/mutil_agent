"""标准化 Agent I/O 契约 —— 框架无关的数据结构层。

AgentTeams 平台的 Worker CRD（src/agentteams/workers.yaml + workers/*/SOUL.md）
已取代 Python 端的 Agent 实现。copaw 运行时负责 Worker 生命周期管理、技能执行
和 Ralph 自我迭代。本文件仅保留框架无关的 I/O 数据结构和抽象契约。

保留内容：
  - WorkerContext: 统一输入上下文（任务规格 + 上游产物 + 里程碑期望）
  - WorkerResult: 统一输出结果（状态码 + 产出文本 + 交接目标）
  - ResultStatus: 结果状态枚举
  - AgentInterface: 抽象基类（作为 I/O 契约参考）"""

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
# 3. 自检
# ========================================================================== #

async def _self_test():
    """快速自检：验证数据类序列化。"""
    print("=== AgentInterface 自检 ===")

    # 数据类
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

    print("=== 自检通过 ===")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_self_test())