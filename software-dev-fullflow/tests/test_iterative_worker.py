"""GAP-08③ 测试：iterative_worker 工作计划数据结构。

覆盖 WorkStep / WorkPlan 的：
  - 必填字段契约（index / description 必须提供）
  - 可选字段默认值（target_file / status / retries / error_feedback）
  - status 取值合法集合
  - WorkPlan 默认字段（steps 空列表 / constraints / rollback 空串）
  - steps 的元素类型校验
  - 可变默认值安全（field(default_factory=list) 隔离实例）
"""

from __future__ import annotations

from loop.iterative_worker import WorkStep, WorkPlan


# --------------------------------------------------------------------------- #
# WorkStep
# --------------------------------------------------------------------------- #

def test_workstep_required_fields():
    """index 和 description 为必填，缺一即报 TypeError。"""
    step = WorkStep(index=1, description="定位根因")
    assert step.index == 1
    assert step.description == "定位根因"


def test_workstep_missing_required_field():
    """缺 description 必须报错。"""
    try:
        WorkStep(index=1)  # type: ignore[call-arg]
        assert False, "缺 description 不应能构造"
    except TypeError:
        pass


def test_workstep_optional_defaults():
    """可选字段默认值契约。"""
    step = WorkStep(index=2, description="写补丁")
    assert step.target_file == ""
    assert step.status == "pending"
    assert step.retries == 0
    assert step.error_feedback == ""


def test_workstep_valid_statuses():
    """status 允许的取值集合。"""
    valid = {"pending", "in_progress", "done", "failed"}
    for status in valid:
        step = WorkStep(index=1, description="x", status=status)
        assert step.status == status


def test_workstep_custom_values():
    """显式传值覆盖默认值。"""
    step = WorkStep(
        index=3,
        description="自检",
        target_file="src/app.py",
        status="in_progress",
        retries=2,
        error_feedback="校验失败",
    )
    assert step.target_file == "src/app.py"
    assert step.status == "in_progress"
    assert step.retries == 2
    assert step.error_feedback == "校验失败"


def test_workstep_equality():
    """同字段 dataclass 判等；字段不同则不等。"""
    a = WorkStep(index=1, description="a", status="done")
    b = WorkStep(index=1, description="a", status="done")
    c = WorkStep(index=1, description="a", status="pending")
    assert a == b
    assert a != c


# --------------------------------------------------------------------------- #
# WorkPlan
# --------------------------------------------------------------------------- #

def test_workplan_required_fields():
    """summary 为必填。"""
    plan = WorkPlan(summary="登录接口空用户名修复")
    assert plan.summary == "登录接口空用户名修复"


def test_workplan_missing_required_field():
    """缺 summary 必须报错。"""
    try:
        WorkPlan()  # type: ignore[call-arg]
        assert False, "缺 summary 不应能构造"
    except TypeError:
        pass


def test_workplan_optional_defaults():
    """WorkPlan 可选字段默认值：steps 空列表 / constraints / rollback 空串。"""
    plan = WorkPlan(summary="s")
    assert plan.steps == []
    assert plan.constraints == ""
    assert plan.rollback == ""


def test_workplan_steps_holds_workstep():
    """steps 元素为 WorkStep，且带步骤时按序保留。"""
    plan = WorkPlan(
        summary="s",
        steps=[
            WorkStep(index=1, description="第一步"),
            WorkStep(index=2, description="第二步"),
        ],
    )
    assert len(plan.steps) == 2
    assert all(isinstance(s, WorkStep) for s in plan.steps)
    assert [s.index for s in plan.steps] == [1, 2]


def test_workplan_mutable_default_isolated():
    """field(default_factory=list) 保证实例间 steps 隔离，避免共享可变默认值。"""
    p1 = WorkPlan(summary="s1")
    p2 = WorkPlan(summary="s2")
    p1.steps.append(WorkStep(index=1, description="x"))
    assert p2.steps == []          # p2 不受 p1 影响
    assert len(p1.steps) == 1


def test_workplan_equality():
    """同字段 WorkPlan 判等。"""
    a = WorkPlan(summary="s", constraints="c")
    b = WorkPlan(summary="s", constraints="c")
    c = WorkPlan(summary="s", constraints="不同")
    assert a == b
    assert a != c


def test_workplan_from_dict_pattern():
    """WorkPlan/WorkStep 可经 dataclasses.asdict/from_dict 模式 round-trip 重建。"""
    import dataclasses

    plan = WorkPlan(
        summary="修复登录",
        constraints="不改接口",
        rollback="git revert",
        steps=[
            WorkStep(index=1, description="定位", status="done"),
            WorkStep(index=2, description="修复", target_file="app.py"),
        ],
    )
    d = dataclasses.asdict(plan)
    rebuilt = WorkPlan(
        summary=d["summary"],
        constraints=d["constraints"],
        rollback=d["rollback"],
        steps=[WorkStep(**s) for s in d["steps"]],
    )
    assert rebuilt == plan
    assert rebuilt.steps[1].target_file == "app.py"
