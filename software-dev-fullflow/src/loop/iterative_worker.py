"""工作计划数据结构 —— 框架无关的数据结构层。

Ralph 自我迭代能力现由 AgentTeams 平台的 copaw 运行时在 Worker 容器内原生提供。
Worker 的 SOUL.md 中定义的工作准则和校验规则，由 copaw 的 AgentRunner + tool hook
机制执行。本文件仅保留框架无关的数据结构。

保留内容：
  - WorkStep / WorkPlan: 工作计划数据结构
"""

from __future__ import annotations

from dataclasses import dataclass, field


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