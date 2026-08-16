"""审批管理器（ApprovalManager）—— 人工审批留痕闭环 + TTL 超时兜底。

解决两个 P0 评审关切：
  1. **审批留痕闭环**：每次人工审批（批准/驳回）都写 EventBus 事件 + AuditLogger
     `human_intervention` 审计，让「审批决策 → 审计 → 事件广播」成为闭环，
     满足「工程落地 / 安全可审计」评审项。
  2. **审批 TTL 超时兜底**：待审批请求带过期时间（TTL），后台定时扫描，
     超时自动降级为「驳回（timeout）」并写审计 + 发事件，避免演示卡死在审批环节。

设计原则：
  - 纯标准库（asyncio + dataclasses），零额外依赖。
  - 与 AgentTeams copaw 的 `needs_approval` 决策流对齐：`approval_id` 唯一标识一次审批。
  - 独立模块，通过依赖注入复用既有 EventBus / AuditLogger，不破坏现有 API。

用法：
    am = ApprovalManager(event_bus, audit, ttl_secs=60)
    await am.request(task_id, requester="releaser", reason="灰度放量需人工确认",
                     kind="release")     # 登记一条待审批
    await am.decide(approval_id, approved=True, reviewer="admin")  # 人工审批
    await am.check_timeouts()            # 手动扫一次超时（或由 _timeout_loop 自动）
    await am.start()  # 启动后台超时扫描
    await am.stop()   # 停止后台扫描
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loop.audit_logger import AuditLogger
from loop.event_bus import EventBus


class ApprovalStatus(str, Enum):
    """审批请求状态。"""

    PENDING = "pending"          # 待人工审批
    APPROVED = "approved"        # 已批准
    REJECTED = "rejected"        # 已驳回（人工）
    TIMEOUT = "timeout"          # 超时自动降级驳回


@dataclass
class ApprovalRequest:
    """一条待审批请求。"""

    approval_id: str
    task_id: str
    reason: str
    requester: str = "worker"            # 请求审批的 Agent（如 releaser）
    kind: str = "approve"                # 审批类别（如 release / destructive）
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0              # TTL 截止时间戳；0 = 不超时
    decided_at: float = 0.0
    reviewer: str = "human"              # 审批人
    detail: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: float | None = None) -> bool:
        """是否已超过 TTL。"""
        if self.expires_at <= 0:
            return False
        return (now if now is not None else time.time()) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "task_id": self.task_id,
            "reason": self.reason,
            "requester": self.requester,
            "kind": self.kind,
            "status": self.status.value,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "decided_at": self.decided_at,
            "reviewer": self.reviewer,
            "detail": self.detail,
        }


class ApprovalManager:
    """人工审批管理器。

    Args:
        event_bus: 复用的 EventBus（发审批事件 + 审计广播）。
        audit: 复用的 AuditLogger（审批留痕闭环）。
        ttl_secs: 待审批请求的默认存活时间（秒）；<=0 表示不超时（仅人工审批）。
        timeout_reject: 超时后默认动作：True=自动驳回并记审计，False=仅告警不处置。
    """

    DEFAULT_TTL_SECS = 60

    def __init__(
        self,
        event_bus: EventBus,
        audit: AuditLogger,
        ttl_secs: int = DEFAULT_TTL_SECS,
        timeout_reject: bool = True,
    ):
        self.event_bus = event_bus
        self.audit = audit
        self.ttl_secs = int(ttl_secs)
        self.timeout_reject = timeout_reject

        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = asyncio.Lock()
        self._timeout_task: asyncio.Task | None = None
        self._running = False

    # ------------------------------------------------------------------ #
    # 登记审批请求
    # ------------------------------------------------------------------ #

    async def request(
        self,
        task_id: str,
        reason: str,
        requester: str = "worker",
        kind: str = "approve",
        ttl_secs: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """登记一条待审批请求，返回带唯一 approval_id 的请求。

        若配置了 TTL（默认），同时启动超时兜底；`expires_at = now + ttl`。
        """
        req = ApprovalRequest(
            approval_id=uuid.uuid4().hex[:12],
            task_id=task_id,
            reason=reason,
            requester=requester,
            kind=kind,
            detail=detail or {},
        )
        ttl = self.ttl_secs if ttl_secs is None else ttl_secs
        if ttl > 0:
            req.expires_at = time.time() + ttl

        async with self._lock:
            self._requests[req.approval_id] = req

        # 广播「需要人工介入」事件（HITL 入口）
        await self.event_bus.human_intervention(
            task_id,
            reason=f"[{kind}] {reason}",
            data={"approval_id": req.approval_id, "requester": requester, "kind": kind},
        )
        # 审批留痕：登记动作写审计（result=REQUIRED）
        self.audit.log_human_intervention(
            task_id, requester,
            reason=f"[{kind}] {reason}",
            approved=None,
        )
        print(f"  ⏳ 审批待决: {req.approval_id} [{kind}] {reason} "
              f"(ttl={ttl}s, 超时自动{'驳回' if self.timeout_reject else '仅告警'})")
        return req

    # ------------------------------------------------------------------ #
    # 人工审批
    # ------------------------------------------------------------------ #

    async def decide(
        self,
        approval_id: str,
        approved: bool,
        reviewer: str = "human",
        detail: dict[str, Any] | None = None,
    ) -> ApprovalRequest | None:
        """人工审批：批准（approved=True）或驳回（False）。

        写 EventBus 里程碑事件 + AuditLogger `human_intervention` 审计，
        实现审批留痕闭环。返回被处置的请求；找不到返回 None。
        """
        async with self._lock:
            req = self._requests.get(approval_id)
            if req is None:
                print(f"  ⚠ 审批 {approval_id} 不存在（可能已超时/已处置）")
                return None
            if req.status != ApprovalStatus.PENDING:
                print(f"  ⚠ 审批 {approval_id} 已是 {req.status.value}，忽略重复操作")
                return req
            req.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            req.decided_at = time.time()
            req.reviewer = reviewer
            if detail:
                req.detail.update(detail)

        # 审批留痕闭环：EventBus 里程碑事件（驱动前端 + 下游）
        if approved:
            await self.event_bus.milestone_reached(
                reviewer, req.task_id, "APPROVED",
                data={"approval_id": approval_id, "kind": req.kind,
                      "reason": req.reason},
            )
        else:
            await self.event_bus.milestone_failed(
                reviewer, req.task_id, "REJECTED",
                data={"approval_id": approval_id, "kind": req.kind,
                      "reason": req.reason},
            )

        # 审批留痕闭环：AuditLogger 审计（PASS / FAIL）
        self.audit.log_human_intervention(
            req.task_id, req.requester,
            reason=f"[{req.kind}] {req.reason}",
            approved=approved,
        )
        self.audit.log(
            req.task_id, reviewer, "decision", f"decide_{req.kind}",
            result="PASS" if approved else "FAIL",
            detail={"approval_id": approval_id, "reviewer": reviewer},
        )
        print(f"  {'✅' if approved else '❌'} 人工审批: {approval_id} "
              f"→ {'批准' if approved else '驳回'}（by {reviewer}）")
        return req

    # ------------------------------------------------------------------ #
    # TTL 超时兜底
    # ------------------------------------------------------------------ #

    async def check_timeouts(self) -> list[ApprovalRequest]:
        """扫描并处置已过期的待审批请求（超时自动驳回）。

        每个超时请求写 `human_intervention` 审计（result=TIMEOUT）+
        发 `MILESTONE_FAILED` 事件（超时降级），实现「审批不卡死」兜底。
        """
        now = time.time()
        expired: list[ApprovalRequest] = []

        async with self._lock:
            pending = [r for r in self._requests.values() if r.status == ApprovalStatus.PENDING]
            for req in pending:
                if req.is_expired(now):
                    req.status = ApprovalStatus.TIMEOUT
                    req.decided_at = now
                    req.reviewer = "system"
                    expired.append(req)

        for req in expired:
            self.audit.log_human_intervention(
                req.task_id, req.requester,
                reason=f"[{req.kind}] {req.reason} (审批超时 {self.ttl_secs}s)",
                approved=False,
            )
            self.audit.log(
                req.task_id, "system", "decision", f"timeout_{req.kind}",
                result="FAIL",
                detail={"approval_id": req.approval_id,
                        "elapsed_s": round(req.decided_at - req.created_at, 1)},
            )
            if self.timeout_reject:
                await self.event_bus.milestone_failed(
                    "system", req.task_id, "APPROVAL_TIMEOUT",
                    data={"approval_id": req.approval_id, "kind": req.kind,
                          "reason": req.reason},
                )
                print(f"  ⏰ 审批超时自动驳回: {req.approval_id} "
                      f"[{req.kind}] {req.reason} ({self.ttl_secs}s)")
        return expired

    # ------------------------------------------------------------------ #
    # 后台超时扫描
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """启动后台超时扫描任务（每 2s 扫一次）。"""
        if self._running:
            return
        self._running = True
        self._timeout_task = asyncio.create_task(self._timeout_loop())

    async def stop(self) -> None:
        """停止后台超时扫描。"""
        self._running = False
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass
            self._timeout_task = None

    async def _timeout_loop(self) -> None:
        while self._running:
            try:
                await self.check_timeouts()
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 - 后台任务不应因单次异常退出
                print(f"  ⚠ 审批超时扫描异常: {e}")
            await asyncio.sleep(2)

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #

    def pending(self, task_id: str = "") -> list[ApprovalRequest]:
        """查询待审批请求。"""
        return [r for r in self._requests.values()
                if r.status == ApprovalStatus.PENDING and (not task_id or r.task_id == task_id)]

    def all(self) -> list[ApprovalRequest]:
        return list(self._requests.values())

    def snapshot(self) -> dict[str, Any]:
        """汇总统计，供 /api/status 展示。"""
        by_status: dict[str, int] = {}
        for r in self._requests.values():
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        pending_list = [
            {"approval_id": r.approval_id, "task_id": r.task_id,
             "reason": r.reason, "kind": r.kind,
             "expires_in_s": round(max(0.0, r.expires_at - time.time()), 1)
             if r.expires_at > 0 else -1}
            for r in self.pending()
        ]
        return {"total": len(self._requests), "by_status": by_status,
                "pending": pending_list}


# ========================================================================== #
# 自检
# ========================================================================== #

async def _self_test():
    import tempfile
    from pathlib import Path

    print("=== ApprovalManager 自检 ===")
    with tempfile.TemporaryDirectory() as tmp:
        audit = AuditLogger(Path(tmp))
        bus = EventBus()
        am = ApprovalManager(bus, audit, ttl_secs=1)

        # 1. 登记 + 人工批准
        req = await am.request("t1", "灰度放量需确认", requester="releaser", kind="release")
        await am.decide(req.approval_id, approved=True, reviewer="admin")
        assert req.status == ApprovalStatus.APPROVED
        records = audit._count
        assert records >= 3  # request(1) + decide human_intervention(1) + decision(1)

        # 2. 登记 + 超时自动驳回
        req2 = await am.request("t2", "删除生产数据需确认", requester="fixer", kind="destructive")
        await asyncio.sleep(1.2)
        expired = await am.check_timeouts()
        assert len(expired) == 1
        assert expired[0].status == ApprovalStatus.TIMEOUT
        assert expired[0].approval_id == req2.approval_id

        # 3. 审计文件确实落盘（审批留痕闭环）
        from loop.audit_logger import read_audit_log
        records_all = read_audit_log(Path(tmp) / "audit.jsonl")
        types = {r["event_type"] for r in records_all}
        assert "human_intervention" in types
        assert "decision" in types

        audit.close()
    print("✓ ApprovalManager 自检通过")


if __name__ == "__main__":
    asyncio.run(_self_test())
