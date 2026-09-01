"""系统组装冒烟测试：把所有已开发的子系统串联成一个整体做端到端验证。

本测试的意义：
  项目里已开发了多个相对独立的子系统（PDCA 闭环 / 记忆系统 / 知识追踪·成长分 /
  审批留痕 / 审计日志 / 员工间通信 / 评价反哺），每个子系统都有独立单测。
  本测试专门验证"把它们组装成一个整体后"数据是否真正打通、闭环是否能作为
  一个整体跑通 —— 即组装正确性（integration of the assembled system）。

覆盖的组装链路（一次 mock 闭环同时打通）：
  1. 统一导出组装：`from loop import ...` 能拿到所有子系统（对外整体可见）
  2. PDCA 闭环组装：AgentTeamsLoop(mock) 跑完 8 状态 → RETROSPECT 终态 + 6 里程碑
  3. 记忆系统组装：闭环中各 Agent 迭代 → AgentMemoryRegistry 沉淀长期记忆
  4. 知识追踪·成长分组装：闭环中 UsageTracker 记录知识命中/Skill 调用 →
     get_agent_growth_score 可查 → 传入 score_team（成长分 0.15 权重）
  5. 审批留痕组装：发布审批 → EventBus human_intervention + AuditLogger 留痕
  6. 审计组装：audit.jsonl 含 RETROSPECT_DONE / human_intervention / decision
  7. 员工间通信组装：AgentBus request/reply 授权流在系统上下文中可用
  8. 评价反哺组装：score_team 输出治理命令，闭环后生成成绩单落盘

运行方式（software-dev-fullflow 根目录）：
    demo\\.venv\\Scripts\\python.exe -m pytest tests/test_system_assembly.py -v
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

# ① 统一导出组装：验证 loop 包对外一次导出所有子系统
from loop import (
    AgentMemoryRegistry,
    AgentTeamsLoop,
    ApprovalManager,
    AuditLogger,
    ContextManager,
    DynamicBudgetAllocator,
    KnowledgeEntry,
    UsageTracker,
    get_tracker,
    read_audit_log,
)
from loop.agent_bus import AgentBus, MessageType
from loop.agentteams_loop import run_pdca_task
from loop.evaluation import score_team
from loop.state import State

EXPECTED_MILESTONES = [
    "TASK_SPEC_READY",
    "ROOT_CAUSE_FOUND",
    "FIX_APPLIED",
    "TEST_PASSED",
    "RELEASE_OK",
    "RETROSPECT_DONE",
]

# 一套完整班子（Leader + 9 职能员工）
FULL_ROSTER = [
    "leader", "aggregator", "rootcause",
    "frontend", "backend", "fixer",
    "tester", "releaser", "retrospector",
    "doc-manager", "coordinator",
]


# --------------------------------------------------------------------------- #
# ① 统一导出组装
# --------------------------------------------------------------------------- #

def test_unified_exports_assembled():
    """所有子系统都应从 loop 包统一导出，供外部一键集成。"""
    assert AgentTeamsLoop is not None
    assert UsageTracker is not None
    assert AgentMemoryRegistry is not None
    assert ApprovalManager is not None
    assert AuditLogger is not None
    assert ContextManager is not None
    assert DynamicBudgetAllocator is not None
    assert KnowledgeEntry is not None
    assert callable(get_tracker)
    assert callable(read_audit_log)
    # 记忆注册表 + 知识追踪 + 审批是组装后新增的统一导出点
    assert hasattr(AgentMemoryRegistry, "consolidate_all")
    assert hasattr(UsageTracker, "record_knowledge_hit")


# --------------------------------------------------------------------------- #
# 整体组装：一次 mock 闭环同时打通所有子系统
# --------------------------------------------------------------------------- #

def test_assembled_system_full_closure(tmp_path: Path):
    """PDCA 闭环组装：mock 跑完 → RETROSPECT 终态 + 6 里程碑 + 8 产物。"""
    state = asyncio.run(run_pdca_task(
        spec="修复登录接口并发下偶发 500",
        workdir=tmp_path,
        mock=True,
        task_id="asm-closure",
    ))
    assert state.state == State.RETROSPECT
    assert state.milestones["RETROSPECT_DONE"]["verdict"] == "PASS"
    for ms in EXPECTED_MILESTONES:
        assert ms in state.milestones, f"缺少里程碑 {ms}"
    assert len(state.milestones) == 6
    assert len(state.artifacts) == 8  # 8 个状态各产出一个 md


def test_assembled_system_memory_persisted(tmp_path: Path):
    """记忆系统组装：闭环中 9 个员工都记录迭代 → 沉淀长期记忆。"""
    task_id = "asm-memory"
    loop = AgentTeamsLoop(
        task_id=task_id, spec="搭建带 POST 的网站",
        workdir=tmp_path, mock=True,
    )
    asyncio.run(loop.run())

    # AgentMemoryRegistry 已初始化并沉淀
    assert loop.agent_memories is not None
    # 每个员工都应有独立记忆目录
    memory_root = tmp_path / "shared" / "agents"
    for agent in FULL_ROSTER:
        mem_dir = memory_root / agent / "memory"
        assert mem_dir.exists(), f"{agent} 缺少记忆目录"
    # 沉淀产物：iterations.jsonl（结构化迭代记录）+ MEMORY.md/memory.json（长期记忆）
    #   说明：mock 闭环中 9 个员工都有迭代记录；其中 6 个参与里程碑的沉淀了长期记忆
    iteration_files = list(memory_root.rglob("iterations.jsonl"))
    assert len(iteration_files) >= 6, f"应 ≥6 份迭代记录，实际 {len(iteration_files)}"
    long_term_files = list(memory_root.rglob("MEMORY.md")) + list(memory_root.rglob("memory.json"))
    assert long_term_files, "应沉淀长期记忆文件（MEMORY.md / memory.json）"
    # consolidate_all 返回非空（有 Agent 沉淀了长期记忆）
    snapshot = loop.agent_memories.snapshot_all()
    assert snapshot, "注册表快照不应为空"
    assert any(m.get("long_term_entries", 0) > 0 for m in snapshot.values()), \
        "至少一个员工沉淀了长期记忆条目"


def test_assembled_system_growth_score_wired(tmp_path: Path):
    """知识追踪·成长分组装：UsageTracker 记录 → growth score 传入 score_team。"""
    task_id = "asm-growth"
    loop = AgentTeamsLoop(
        task_id=task_id, spec="修复登录接口空用户名500",
        workdir=tmp_path, mock=True,
    )
    asyncio.run(loop.run())

    # 闭环中记录了知识命中 + Skill 调用（_run_mock 每阶段埋点）
    stats_dir = tmp_path / "shared" / "stats"
    usage = loop.usage_tracker
    summary = usage.get_summary()
    assert summary["total_knowledge_entries"] >= 6, "应记录 ≥6 条知识条目"
    assert summary["total_knowledge_hits"] >= 6, "应累计 ≥6 次知识命中"
    assert summary["total_skill_invocations"] >= 6, "应累计 ≥6 次 Skill 调用"
    # retrospector 沉淀的知识产生成长分（可查）
    assert usage.get_agent_growth_score("retrospector") >= 0
    # usage_stats.json 落盘
    stats_json = stats_dir / "usage_stats.json"
    assert stats_json.exists(), "usage_stats.json 应落盘"

    # 成长分链路真正打通：score_team 接受 growth_scores 并计入综合分
    growth = {"retrospector": usage.get_agent_growth_score("retrospector")}
    evaluation = score_team(
        loop.state,
        reject_counts=loop.reject_by_agent,
        durations=loop.durations_by_agent,
        adoptions=loop.adoption_by_agent,
        protocol_oks=loop.protocol_by_agent,
        growth_scores=growth,
    )
    assert evaluation.scorecards.get("retrospector") is not None


def test_assembled_system_approval_audit_loop(tmp_path: Path):
    """审批 + 审计组装：发布审批留痕闭环（EventBus + AuditLogger）。"""
    task_id = "asm-approval"
    loop = AgentTeamsLoop(
        task_id=task_id, spec="修复登录接口空用户名500",
        workdir=tmp_path, mock=True,
    )
    asyncio.run(loop.run())

    # 审批流产生 human_intervention 事件
    events = loop.event_bus.history(task_id=task_id)
    human_events = [e for e in events if "human" in e.get("event_type", "").lower()]
    # mock 发布阶段登记审批 → human_intervention 事件（request 时广播）
    assert human_events, "审批登记应产生 human_intervention 事件"

    # 审计日志留痕闭环：human_intervention + decision + milestone
    jsonl = list((tmp_path / "shared" / "audit").glob("*.jsonl"))
    assert jsonl, "应生成审计日志"
    text = jsonl[0].read_text(encoding="utf-8")
    assert "human_intervention" in text, "审批留痕应有 human_intervention 审计"
    assert "RETROSPECT_DONE" in text, "闭环留痕应有 RETROSPECT_DONE"
    assert "decision" in text, "审批决策应有 decision 审计"

    # 用 read_audit_log 读取结构化审计，验证可审计
    records = read_audit_log(jsonl[0])
    types = {r.get("event_type") for r in records}
    assert "human_intervention" in types


def test_assembled_system_team_comm(tmp_path: Path):
    """员工间通信组装：AgentBus request/reply 在系统上下文中可用。"""
    bus = AgentBus()
    # 默认 PDCA 上下游已授权：tester → backend（要日志）
    assert bus.is_authorized("tester", "backend")
    assert bus.is_authorized("leader", "tester"), "leader 应可协调全员"

    request_id = bus.request("tester", "backend", "T-asm",
                             "请提供 POST /api/submit 的开发日志", kind="log")
    assert request_id.startswith("req-")
    assert len(bus.get_requests_for("backend")) == 1
    ok = bus.reply("backend", "tester", "T-asm", request_id, "日志已写入 /tmp/server.log")
    assert ok
    replies = [m for m in bus.receive("tester") if m.msg_type == MessageType.REPLY]
    assert len(replies) == 1
    assert replies[0].metadata["request_id"] == request_id
    # 未授权 peer 无法通信（组装后仍保持权限约束）
    assert not bus.is_authorized("aggregator", "retrospector")
    assert bus.request("aggregator", "retrospector", "T-asm", "越权请求") == ""


def test_assembled_system_evaluation_feedback(tmp_path: Path):
    """评价反哺组装：score_team 产出治理命令 + 成绩单落盘。"""
    task_id = "asm-eval"
    loop = AgentTeamsLoop(
        task_id=task_id, spec="修复登录接口空用户名500",
        workdir=tmp_path, mock=True,
    )
    asyncio.run(loop.run())

    evaluation = score_team(
        loop.state,
        reject_counts=loop.reject_by_agent,
        durations=loop.durations_by_agent,
        adoptions=loop.adoption_by_agent,
        protocol_oks=loop.protocol_by_agent,
    )
    cmds = evaluation.governance_commands()
    # mock 全员达标通常无治理命令，但 scorecards 应落盘 ≥6 份
    assert cmds is not None
    scorecards = list((tmp_path / "shared" / "agents").rglob("scorecard.json"))
    assert len(scorecards) >= 6, f"应 ≥6 份成绩单，实际 {len(scorecards)}"
    # 成绩单可解析（可审计）
    data = json.loads(scorecards[0].read_text(encoding="utf-8"))
    assert "agent" in data or "rating" in data


def test_assembled_system_state_persists(tmp_path: Path):
    """组装后共享状态落盘：state.json 保存最终 RETROSPECT + 全部里程碑。"""
    task_id = "asm-persist"
    loop = AgentTeamsLoop(
        task_id=task_id, spec="搭建官网",
        workdir=tmp_path, mock=True,
    )
    asyncio.run(loop.run())

    state_json = tmp_path / "shared" / "tasks" / task_id / "state.json"
    assert state_json.exists(), "state.json 应落盘"
    data = json.loads(state_json.read_text(encoding="utf-8"))
    assert data["state"] == "RETROSPECT"
    assert len(data["milestones"]) == 6
    # 统一导出也支持从状态机读取（组装后一致可读）
    assert State.RETROSPECT.value == "RETROSPECT"
