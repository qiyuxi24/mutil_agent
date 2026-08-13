"""可运行的研发团队调度 Loop 系统。

模块：
    state.py   — PDCA 闭环状态机（8 状态 + 里程碑 + 打回）
    team.py    — 6 个研发 Agent 角色定义（soul + 准则 + 里程碑）
    manager.py — Manager 调度 Loop（派单 → 验证 → 推进/打回）
"""

from loop.state import State, Milestone, TaskState
from loop.team import AgentRole, DEFAULT_AGENTS, get_role
from loop.manager import TeamManagerLoop
from loop.fixer_loop import FixerLoop, FixStep, FixPlan

__all__ = [
    "State",
    "Milestone",
    "TaskState",
    "AgentRole",
    "DEFAULT_AGENTS",
    "get_role",
    "TeamManagerLoop",
    "FixerLoop",
    "FixStep",
    "FixPlan",
]
