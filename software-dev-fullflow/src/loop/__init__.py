"""可运行的研发团队调度 Loop 系统 —— AgentTeams 原生（阿里官方协同基点）。

参赛主路径（AgentTeams 原生 / 框架无关）：
    agentteams_loop.py    — Python 客户端：提交任务 + 监控里程碑 + 展示结果
    agentteams_client.py  — AgentTeams 平台客户端（封装 agt CLI + Matrix 协议）
    agentteams_matrix.py  — Matrix 协议客户端（MatrixClientMixin）
    agentteams_yaml.py    — workers.yaml 解析（单一数据源）
    state.py              — PDCA 闭环确定性状态机（8 状态 + 里程碑 + 打回）
    context/              — 上下文工程包（预算/三层记忆/迭代协议/编排器）
    evaluation.py         — 成员评价器（合格度 + 贡献度 + 治理评级）
    agent_bus.py          — 消息总线（AgentBus pub/sub）
    event_bus.py          — 事件驱动（EventBus，替代同步轮询）
    audit_logger.py       — 结构化审计日志

框架无关数据结构：
    agent_interface.py    — WorkerContext / WorkerResult / ResultStatus / AgentInterface
    iterative_worker.py   — WorkStep / WorkPlan
"""

# 核心模块（框架无关，始终可用）
from loop.state import State, Milestone, TaskState, STATE_EXECUTOR, STATE_EXPECTED_MILESTONE

# AgentTeams 原生模块（参赛主路径）
from loop.agentteams_client import AgentTeamsClient, AgtCLI, WorkerInfo, TaskInfo
from loop.agentteams_loop import AgentTeamsLoop, run_pdca_task, check_platform_ready

# 上下文工程（框架无关）
from loop.context import DynamicBudgetAllocator, StageBudget, SemanticMemorySearch

# 框架无关数据结构（保留作为 I/O 契约参考）
from loop.agent_interface import (
    WorkerContext, WorkerResult, ResultStatus, AgentInterface,
)
from loop.iterative_worker import WorkStep, WorkPlan

# 消息总线 + 事件驱动
from loop.agent_bus import (
    AgentBus, EventBus, Event, EventType, MessageType, AgentMessage,
)
from loop.audit_logger import AuditLogger, AuditEntry, read_audit_log


__all__ = [
    # 状态机
    "State", "Milestone", "TaskState", "STATE_EXECUTOR", "STATE_EXPECTED_MILESTONE",
    # AgentTeams 原生（参赛主路径）
    "AgentTeamsClient", "AgtCLI", "WorkerInfo", "TaskInfo",
    "AgentTeamsLoop", "run_pdca_task", "check_platform_ready",
    # 上下文工程
    "DynamicBudgetAllocator", "StageBudget", "SemanticMemorySearch",
    # 框架无关数据结构
    "WorkerContext", "WorkerResult", "ResultStatus", "AgentInterface",
    "WorkStep", "WorkPlan",
    # 消息总线 + 事件驱动
    "AgentBus", "EventBus", "Event", "EventType", "MessageType", "AgentMessage",
    # 审计
    "AuditLogger", "AuditEntry", "read_audit_log",
]