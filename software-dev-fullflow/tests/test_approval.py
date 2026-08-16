"""ApprovalManager 单测 —— 审批留痕闭环 + TTL 超时兜底。

覆盖：
  - 登记审批请求（approval_id / expires_at / TTL 计算）
  - 人工批准 / 驳回 → 写审计 + 发事件（留痕闭环）
  - TTL 超时自动驳回（timeout 兜底）+ 审计 + 事件
  - 重复操作幂等、找不到请求返回 None
  - snapshot / pending 查询
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from loop.approval import ApprovalManager, ApprovalRequest, ApprovalStatus
from loop.audit_logger import AuditLogger, read_audit_log
from loop.event_bus import EventBus


@pytest.fixture
def audit(tmp_path: Path) -> AuditLogger:
    return AuditLogger(tmp_path, console=False)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def am(audit: AuditLogger, bus: EventBus) -> ApprovalManager:
    return ApprovalManager(bus, audit, ttl_secs=60)


# ------------------------------------------------------------------ #
# 登记审批请求
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_request_creates_pending_with_ttl(am, bus):
    req = await am.request("t1", "灰度放量需确认", requester="releaser", kind="release")
    assert req.status == ApprovalStatus.PENDING
    assert req.task_id == "t1"
    assert req.requester == "releaser"
    assert req.kind == "release"
    # TTL 计算：expires_at = created_at + ttl
    assert req.expires_at == pytest.approx(req.created_at + 60, abs=0.5)
    # 广播 HUMAN_INTERVENTION_REQUIRED 事件
    evts = bus.history(event_type="HUMAN_INTERVENTION_REQUIRED")
    assert len(evts) == 1
    assert evts[0]["data"]["approval_id"] == req.approval_id


@pytest.mark.asyncio
async def test_request_audit_written(am, audit):
    await am.request("t1", "删除生产数据需确认", requester="fixer", kind="destructive")
    audit.close()
    records = read_audit_log(audit.log_dir / "audit.jsonl")
    assert len(records) == 1
    assert records[0]["event_type"] == "human_intervention"
    assert records[0]["result"] == "REQUIRED"
    assert records[0]["detail"]["reason"].startswith("[destructive]")


# ------------------------------------------------------------------ #
# 人工审批留痕闭环
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_decide_approve_writes_audit_and_event(am, audit, bus):
    req = await am.request("t1", "发布审批", requester="releaser", kind="release")
    before = audit.count()
    result = await am.decide(req.approval_id, approved=True, reviewer="admin")

    assert result is not None
    assert result.status == ApprovalStatus.APPROVED
    assert result.reviewer == "admin"
    assert result.decided_at > 0

    # 审计留痕：human_intervention(PASS) + decision(PASS)
    assert audit.count() == before + 2
    audit.close()
    records = read_audit_log(audit.log_dir / "audit.jsonl")
    types = [r["event_type"] for r in records]
    assert types.count("human_intervention") == 2  # 登记 1 + 批准 1
    assert "decision" in types

    # 事件：MILESTONE_REACHED (APPROVED)
    evts = bus.history(event_type="MILESTONE_REACHED")
    assert len(evts) == 1
    assert evts[0]["data"]["approval_id"] == req.approval_id


@pytest.mark.asyncio
async def test_decide_reject_writes_audit_and_event(am, audit, bus):
    req = await am.request("t1", "发布审批", requester="releaser", kind="release")
    result = await am.decide(req.approval_id, approved=False, reviewer="admin")
    assert result.status == ApprovalStatus.REJECTED
    audit.close()
    records = read_audit_log(audit.log_dir / "audit.jsonl")
    # 驳回：human_intervention result=FAIL
    reject_records = [r for r in records if r["event_type"] == "human_intervention"
                      and r["detail"].get("reason", "").startswith("[release]")]
    assert reject_records[-1]["result"] == "FAIL"
    # 事件：MILESTONE_FAILED (REJECTED)
    evts = bus.history(event_type="MILESTONE_FAILED")
    assert len(evts) == 1


@pytest.mark.asyncio
async def test_decide_missing_returns_none(am):
    result = await am.decide("nonexistent-id", approved=True)
    assert result is None


@pytest.mark.asyncio
async def test_decide_duplicate_is_idempotent(am, audit):
    req = await am.request("t1", "发布审批", requester="releaser")
    await am.decide(req.approval_id, approved=True)
    before = audit.count()
    # 重复决策：不再处置，不额外写审计
    result = await am.decide(req.approval_id, approved=False)
    assert result.status == ApprovalStatus.APPROVED  # 保持首次结果
    assert audit.count() == before


# ------------------------------------------------------------------ #
# TTL 超时兜底
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_check_timeouts_auto_reject(am, audit, bus):
    req = await am.request("t1", "删除数据需确认", requester="fixer", kind="destructive",
                           ttl_secs=0)  # 先手动登记不超时
    # 手动改 expires_at 为过去，模拟 TTL 到期
    req.expires_at = time.time() - 1

    expired = await am.check_timeouts()
    assert len(expired) == 1
    assert expired[0].status == ApprovalStatus.TIMEOUT
    assert expired[0].reviewer == "system"

    # 审计留痕：human_intervention(FAIL) + decision(timeout FAIL)
    audit.close()
    records = read_audit_log(audit.log_dir / "audit.jsonl")
    decision_records = [r for r in records if r["event_type"] == "decision"]
    assert any(r["action"] == "timeout_destructive" for r in decision_records)

    # 事件：MILESTONE_FAILED (APPROVAL_TIMEOUT)
    evts = bus.history(event_type="MILESTONE_FAILED")
    assert any(e["data"].get("approval_id") == req.approval_id for e in evts)


@pytest.mark.asyncio
async def test_background_timeout_loop(am, audit):
    req = await am.request("t1", "需确认", requester="worker", ttl_secs=0)
    req.expires_at = time.time() - 1
    await am.start()
    # 等后台 loop（每 2s 扫一次）处理
    for _ in range(15):
        if req.status != ApprovalStatus.PENDING:
            break
        await asyncio.sleep(0.2)
    await am.stop()
    assert req.status == ApprovalStatus.TIMEOUT


# ------------------------------------------------------------------ #
# 查询
# ------------------------------------------------------------------ #

@pytest.mark.asyncio
async def test_pending_and_snapshot(am):
    await am.request("t1", "A", requester="releaser", kind="release")
    r2 = await am.request("t1", "B", requester="fixer", kind="destructive")
    await am.decide(r2.approval_id, approved=True)

    pending = am.pending("t1")
    assert len(pending) == 1
    assert pending[0].kind == "release"

    snap = am.snapshot()
    assert snap["by_status"]["pending"] == 1
    assert snap["by_status"]["approved"] == 1
    assert snap["total"] == 2
    assert len(snap["pending"]) == 1
