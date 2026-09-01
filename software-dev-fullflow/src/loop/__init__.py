"""可运行的研发团队调度 Loop 系统 —— AgentTeams 原生（阿里官方协同基点）。

参赛主路径（AgentTeams 原生 / 框架无关）：
    agentteams_loop.py    — Python 客户端：提交任务 + 监控里程碑 + 展示结果
    agentteams_client.py  — AgentTeams 平台客户端（封装 agt CLI + Matrix 协议）
    agentteams_matrix.py  — Matrix 协议客户端（MatrixClientMixin）
    agentteams_yaml.py    — workers.yaml 解析（单一数据源）
    state.py              — PDCA 闭环确定性状态机（8 状态 + 里程碑 + 打回）
    context/              — 上下文工程包（预算/三层记忆/迭代协议/编排器）
    evaluation.py         — 成员评价器（合格度 + 贡献度 + 治理评级）
    agent_bus.py          — 消息总线（AgentBus pub/sub + 员工间 request/reply）
    event_bus.py          — 事件驱动（EventBus，替代同步轮询）
    audit_logger.py       — 结构化审计日志
    knowledge_tracker.py  — 知识/Skill 复用追踪器（成长分数据源）
    approval.py           — 人工审批留痕闭环（ApprovalManager + TTL 超时兜底）

本包对外统一导出所有已组装的子系统，供外部一键集成：
    from loop import AgentTeamsLoop, AgentMemoryRegistry, UsageTracker, ApprovalManager

"""

# 核心模块（框架无关，始终可用）
from loop.state import State, Milestone, TaskState, STATE_EXECUTOR, STATE_EXPECTED_MILESTONE

# AgentTeams 原生模块（参赛主路径）
from loop.agentteams_client import AgentTeamsClient, AgtCLI, WorkerInfo, TaskInfo
from loop.agentteams_loop import AgentTeamsLoop, run_pdca_task, check_platform_ready

# 上下文工程（框架无关，含按 Agent 维度的记忆注册表）
from loop.context import (
    DynamicBudgetAllocator,
    StageBudget,
    SemanticMemorySearch,
    ContextManager,
    AgentMemory,
    AgentMemoryEntry,
    AgentMemoryRegistry,
)

# 知识/Skill 复用追踪器（成长分数据源）
from loop.knowledge_tracker import (
    UsageTracker,
    KnowledgeEntry,
    SkillEntry,
    UsageStats,
    get_tracker,
    reset_tracker,
)

# 人工审批留痕闭环
from loop.approval import (
    ApprovalManager,
    ApprovalRequest,
    ApprovalStatus,
)

# 消息总线 + 事件驱动
from loop.agent_bus import (
    AgentBus, EventBus, Event, EventType, MessageType, AgentMessage,
)
from loop.audit_logger import AuditLogger, AuditEntry, read_audit_log

# ARIS 移植模块（2026-08-31，批次 7 集成）
from loop.evidence_check import check_claim, check_batch
from loop.threat_scan import scan_for_threats, first_threat_message, quarantine, INVISIBLE_CHARS
from loop.iteration_log import pivot_for, note, show, PIVOT_STRUCTURAL_AT, ESCALATE_HUMAN_AT
from loop.review_gate import Transition, derive_model_family, evaluate_transition
from loop.acceptance_gate import AcceptanceVerdict, accept as acceptance_accept, derive_family as acceptance_family


__all__ = [
    # 状态机
    "State", "Milestone", "TaskState", "STATE_EXECUTOR", "STATE_EXPECTED_MILESTONE",
    # AgentTeams 原生（参赛主路径）
    "AgentTeamsClient", "AgtCLI", "WorkerInfo", "TaskInfo",
    "AgentTeamsLoop", "run_pdca_task", "check_platform_ready",
    # 上下文工程
    "DynamicBudgetAllocator", "StageBudget", "SemanticMemorySearch",
    "ContextManager", "AgentMemory", "AgentMemoryEntry", "AgentMemoryRegistry",
    # 知识/Skill 复用追踪器（成长分）
    "UsageTracker", "KnowledgeEntry", "SkillEntry", "UsageStats",
    "get_tracker", "reset_tracker",
    # 人工审批留痕闭环
    "ApprovalManager", "ApprovalRequest", "ApprovalStatus",
    # 消息总线 + 事件驱动
    "AgentBus", "EventBus", "Event", "EventType", "MessageType", "AgentMessage",
    # 审计
    "AuditLogger", "AuditEntry", "read_audit_log",
    # ARIS 移植（证据预检）
    "check_claim", "check_batch",
    # ARIS 移植（注入扫描）
    "scan_for_threats", "first_threat_message", "quarantine", "INVISIBLE_CHARS",
    # ARIS 移植（停滞检测）
    "pivot_for", "note", "show", "PIVOT_STRUCTURAL_AT", "ESCALATE_HUMAN_AT",
    # ARIS 移植（评审路由）
    "Transition", "derive_model_family", "evaluate_transition",
    # ARIS 移植（验收门）
    "AcceptanceVerdict", "acceptance_accept", "acceptance_family",
]