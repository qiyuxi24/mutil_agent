"""GAP-08 测试：AgentInterface I/O 数据类序列化契约。

覆盖 WorkerContext / WorkerResult / ResultStatus 的：
  - 序列化 round-trip（to_dict/from_dict、to_json/from_json）
  - 辅助属性（context_summary / is_success / summary / get_upstream）
  - from_dict 对缺失字段宽容
"""

from __future__ import annotations

from loop.agent_interface import (
    WorkerContext,
    WorkerResult,
    ResultStatus,
    AgentInterface,
)


# --------------------------------------------------------------------------- #
# WorkerContext
# --------------------------------------------------------------------------- #

def test_worker_context_round_trip():
    ctx = WorkerContext(
        task_id="t1",
        spec="修复登录空指针",
        stage="ROOT_CAUSE",
        expected_milestone="ROOT_CAUSE_FOUND",
        upstream_artifacts={"SPEC_DECOMPOSE": "TASK_SPEC_READY\n规格"},
    )
    d = ctx.to_dict()
    assert d["task_id"] == "t1"
    ctx2 = WorkerContext.from_dict(d)
    assert ctx2.spec == "修复登录空指针"
    assert ctx2.get_upstream("SPEC_DECOMPOSE").startswith("TASK_SPEC_READY")
    # json round-trip
    ctx3 = WorkerContext.from_json(ctx.to_json())
    assert ctx3.stage == "ROOT_CAUSE"


def test_worker_context_from_dict_partial():
    """from_dict 对可选字段缺失时用默认；必填 spec 必须提供。"""
    ctx = WorkerContext.from_dict({"task_id": "t1", "spec": "修复登录"})
    assert ctx.task_id == "t1"
    assert ctx.spec == "修复登录"
    assert ctx.stage == ""                    # 可选字段默认
    assert ctx.expected_milestone == ""
    assert ctx.upstream_artifacts == {}


def test_worker_context_summary():
    ctx = WorkerContext(
        task_id="t1", spec="修复登录空指针",
        constraints="不得破坏现有接口",
        upstream_artifacts={"ROOT_CAUSE": "根因：空值未检查"},
    )
    s = ctx.context_summary
    assert "修复登录空指针" in s
    assert "不得破坏现有接口" in s
    assert "根因：空值未检查" in s


# --------------------------------------------------------------------------- #
# WorkerResult
# --------------------------------------------------------------------------- #

def test_worker_result_round_trip():
    r = WorkerResult(
        task_id="t1", worker_name="fixer",
        status=ResultStatus.SUCCESS, milestone="FIX_APPLIED",
        output="已修复", handoff_to="tester",
        metrics={"elapsed": 1.5},
    )
    d = r.to_dict()
    assert d["status"] == "SUCCESS"  # 枚举 → 字符串
    r2 = WorkerResult.from_dict(d)
    assert r2.status == ResultStatus.SUCCESS
    assert r2.worker_name == "fixer"
    # json round-trip
    r3 = WorkerResult.from_json(r.to_json())
    assert r3.milestone == "FIX_APPLIED"


def test_worker_result_properties():
    r = WorkerResult(
        task_id="t1", worker_name="rootcause",
        status=ResultStatus.SUCCESS, milestone="ROOT_CAUSE_FOUND",
        output="根因报告", handoff_to="fixer",
        metrics={"elapsed": 2.0},
    )
    assert r.is_success
    assert r.summary.startswith("[rootcause] SUCCESS")
    assert "ROOT_CAUSE_FOUND" in r.summary
    assert "2.0s" in r.summary


def test_worker_result_failure():
    r = WorkerResult(
        task_id="t1", worker_name="fixer",
        status=ResultStatus.FAILED, milestone="",
        error="补丁完整性校验失败",
    )
    assert not r.is_success
    assert r.error == "补丁完整性校验失败"


# --------------------------------------------------------------------------- #
# ResultStatus 枚举
# --------------------------------------------------------------------------- #

def test_result_status_values():
    assert ResultStatus.SUCCESS.value == "SUCCESS"
    assert ResultStatus.FAILED.value == "FAILED"
    assert ResultStatus.TIMEOUT.value == "TIMEOUT"
    # 所有枚举可 round-trip
    for status in ResultStatus:
        assert ResultStatus(status.value) == status


# --------------------------------------------------------------------------- #
# AgentInterface 抽象基类
# --------------------------------------------------------------------------- #

def test_agent_interface_is_abstract():
    """AgentInterface 是抽象基类，不能直接实例化。"""
    try:
        AgentInterface()  # type: ignore[abstract]
        assert False, "不应能实例化抽象类"
    except TypeError:
        pass
