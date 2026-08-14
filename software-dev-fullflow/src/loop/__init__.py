"""可运行的研发团队调度 Loop 系统 —— AgentTeams 原生（阿里官方协同基点）。

模块（参赛主路径，全部 AgentTeams 原生 / 框架无关）：
    agentteams_loop.py    — AgentTeams 原生调度循环（delegated/orchestrated，驱动真实 Worker）
    agentteams_client.py  — AgentTeams 平台客户端（封装 agt CLI）
    state.py              — PDCA 闭环确定性状态机（8 状态 + 里程碑 + 打回，协议层）
    team.py               — 6 个研发 Agent 角色定义（soul + 准则 + 里程碑，映射到 Worker）
    context.py            — 上下文工程（预算管理 + 三层记忆 + 迭代协议 + 动态预算 + 语义搜索，工具层）
    evaluation.py         — Agent 成员评价器（合格度 + 贡献度 + 治理评级，差异化卖点）
    iterative_worker.py   — 通用 IterativeWorker 基类（Ralph 自我迭代，所有 Worker 共享）
    agent_interface.py    — 标准化 Agent 接口层（WorkerContext/WorkerResult + AgentInterface ABC）
    agent_bus.py          — 消息总线 + 事件驱动（AgentBus pub/sub + EventBus 事件）

已归档（不参与参赛主路径，仅保留作参考，依赖 MAF）：
    manager.py            — 旧 TeamManagerLoop（MAF 底座，被 agentteams_loop 取代）
    fixer_loop.py         — 旧 FixerLoop（MAF 底座，Ralph 迭代现由 iterative_worker 取代）
"""

# 核心模块（无外部依赖，始终可用）
from loop.state import State, Milestone, TaskState, STATE_EXECUTOR, STATE_EXPECTED_MILESTONE
from loop.team import AgentRole, DEFAULT_AGENTS, get_role, AGENT_MAP

# AgentTeams 原生模块（参赛主路径，推荐使用）
from loop.agentteams_client import AgentTeamsClient, AgtCLI, WorkerInfo, TaskInfo
from loop.agentteams_loop import AgentTeamsLoop, run_pdca_task, check_platform_ready

# Layer 1: 调度 Loop 核心升级
from loop.iterative_worker import (
    IterativeWorker, WorkStep, WorkPlan,
    RootCauseWorker, TesterWorker, ReleaserWorker,
)
from loop.context import DynamicBudgetAllocator, StageBudget, SemanticMemorySearch

# Layer 2: 标准化 Agent 接口层
from loop.agent_interface import (
    WorkerContext, WorkerResult, ResultStatus,
    AgentInterface, AGENT_REGISTRY, get_agent, list_agents,
    AggregatorAgent, RootCauseAgent, FixerAgent,
    TesterAgent, ReleaserAgent, RetrospectorAgent,
)
from loop.agent_bus import (
    AgentBus, EventBus, Event, EventType, MessageType, AgentMessage,
)


# 已归档的 MAF 底座模块：不再在 __all__ 中导出。
# 需要时可通过显式 import（如 `from loop.manager import TeamManagerLoop`）访问，
# 但参赛方案不依赖它们（用户已拍板：参赛只用阿里官方 AgentTeams，不掺 MAF）。


__all__ = [
    # 状态机
    "State", "Milestone", "TaskState", "STATE_EXECUTOR", "STATE_EXPECTED_MILESTONE",
    # 团队定义
    "AgentRole", "DEFAULT_AGENTS", "get_role", "AGENT_MAP",
    # AgentTeams 原生（参赛主路径）
    "AgentTeamsClient", "AgtCLI", "WorkerInfo", "TaskInfo",
    "AgentTeamsLoop", "run_pdca_task", "check_platform_ready",
    # Layer 1: 调度 Loop 核心升级
    "IterativeWorker", "WorkStep", "WorkPlan",
    "RootCauseWorker", "TesterWorker", "ReleaserWorker",
    "DynamicBudgetAllocator", "StageBudget", "SemanticMemorySearch",
    # Layer 2: 标准化 Agent 接口层
    "WorkerContext", "WorkerResult", "ResultStatus",
    "AgentInterface", "AGENT_REGISTRY", "get_agent", "list_agents",
    "AggregatorAgent", "RootCauseAgent", "FixerAgent",
    "TesterAgent", "ReleaserAgent", "RetrospectorAgent",
    "AgentBus", "EventBus", "Event", "EventType", "MessageType", "AgentMessage",
]