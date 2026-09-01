"""AcceptanceGate 单测 —— 验收门机器校验（零依赖、fail-closed）。

覆盖：
  - 跨模型家族评审 → accepted（正向）
  - 同模型家族评审 → rejected（利益相关）
  - 执行者自评 / reviewer 为 self → rejected
  - verdict_id 缺失 / 格式不合法 → rejected
  - 空 claim / reviewer / executor → rejected
  - fail-closed：任意异常输入不抛错、一律返回 rejected
  - derive_family 覆盖 deepseek/qwen/openai/anthropic/unknown 五类
"""

from __future__ import annotations

import pytest

from loop.acceptance_gate import AcceptanceVerdict, accept, derive_family


# ------------------------------------------------------------------ #
# 正向：跨族评审
# ------------------------------------------------------------------ #


def test_cross_family_review_accepted():
    v = accept("功能验收通过，符合需求", "deepseek-v4-flash", "qwen-plus", "review-42")
    assert v.accepted is True
    assert v.verdict_id == "review-42"
    assert v.reason == ""
    assert v.to_dict() == {"accepted": True, "reason": "", "verdict_id": "review-42"}
    assert bool(v) is True
    assert isinstance(v, AcceptanceVerdict)


def test_cross_family_review_other_families():
    """任意两两不同族（deepseek/qwen/openai/anthropic）均应通过。"""
    pairs = [
        ("deepseek-v4-flash", "qwen-plus"),
        ("deepseek-v4-flash", "gpt-4o"),
        ("deepseek-v4-flash", "claude-3-5-sonnet"),
        ("qwen-plus", "gpt-4o"),
        ("qwen-plus", "claude-3-5-sonnet"),
        ("gpt-4o", "claude-3-5-sonnet"),
    ]
    for executor, reviewer in pairs:
        v = accept("验收通过", executor, reviewer, "review-1")
        assert v.accepted is True, f"{executor} / {reviewer} 应通过"


# ------------------------------------------------------------------ #
# 同族拒绝
# ------------------------------------------------------------------ #


def test_same_family_rejected():
    v = accept("验收通过", "deepseek-v4-flash", "deepseek-reasoner", "review-42")
    assert v.accepted is False
    assert "same model family" in v.reason
    assert v.verdict_id == ""


def test_same_family_rejected_other():
    v = accept("验收通过", "gpt-4o", "o3-mini", "review-7")
    assert v.accepted is False
    assert "same model family" in v.reason


# ------------------------------------------------------------------ #
# 自评拒绝
# ------------------------------------------------------------------ #


def test_executor_self_review_rejected():
    v = accept("验收通过", "deepseek-v4-flash", "deepseek-v4-flash", "review-42")
    assert v.accepted is False
    assert "cannot review their own" in v.reason


def test_reviewer_named_self_rejected():
    v = accept("验收通过", "qwen-plus", "self", "review-42")
    assert v.accepted is False
    assert "must not be 'self'" in v.reason


# ------------------------------------------------------------------ #
# verdict_id 校验
# ------------------------------------------------------------------ #


def test_verdict_id_missing_rejected():
    v = accept("验收通过", "deepseek-v4-flash", "qwen-plus", "")
    assert v.accepted is False
    assert "verdict_id" in v.reason


def test_verdict_id_wrong_prefix_rejected():
    v = accept("验收通过", "deepseek-v4-flash", "qwen-plus", "accepted-42")
    assert v.accepted is False
    assert "review-" in v.reason


# ------------------------------------------------------------------ #
# 空参数拒绝
# ------------------------------------------------------------------ #


def test_empty_claim_rejected():
    v = accept("  ", "deepseek-v4-flash", "qwen-plus", "review-42")
    assert v.accepted is False
    assert "claim" in v.reason


def test_empty_reviewer_rejected():
    v = accept("验收通过", "deepseek-v4-flash", " ", "review-42")
    assert v.accepted is False
    assert "reviewer" in v.reason


def test_empty_executor_rejected():
    v = accept("验收通过", "", "qwen-plus", "review-42")
    assert v.accepted is False
    assert "executor" in v.reason


# ------------------------------------------------------------------ #
# fail-closed：异常输入不抛错、一律拒绝
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("kwargs", [
    {"claim": None, "executor": "a", "reviewer": "b", "verdict_id": "review-1"},
    {"claim": "ok", "executor": None, "reviewer": "b", "verdict_id": "review-1"},
    {"claim": "ok", "executor": "a", "reviewer": None, "verdict_id": "review-1"},
    {"claim": "ok", "executor": "a", "reviewer": "b", "verdict_id": None},
    {"claim": "ok", "executor": "a", "reviewer": "b", "verdict_id": 42},
    {"claim": 123, "executor": "a", "reviewer": "b", "verdict_id": "review-1"},
    {"claim": "ok", "executor": ["a"], "reviewer": "b", "verdict_id": "review-1"},
    {"claim": "ok", "executor": "a", "reviewer": ["b"], "verdict_id": "review-1"},
])
def test_fail_closed_on_bad_input(kwargs):
    v = accept(**kwargs)
    assert v.accepted is False
    assert v.reason  # 必须有原因
    assert v.verdict_id == ""


def test_fail_closed_never_raises():
    """各种畸形输入整体不抛异常。"""
    cases = [
        (None, None, None, None),
        ("", "", "", ""),
        ("ok", "a", "b", "nope"),
        ("ok", "a", "a", "review-1"),
    ]
    for args in cases:
        v = accept(*args)
        assert isinstance(v, AcceptanceVerdict)
        assert v.accepted in (True, False)


# ------------------------------------------------------------------ #
# derive_family 五类覆盖
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("model,family", [
    ("deepseek-v4-flash", "deepseek"),
    ("DeepSeek-R1", "deepseek"),
    ("  qwen-plus  ", "qwen"),
    ("QwQ-32B", "qwen"),
    ("gpt-4o", "openai"),
    ("openai/gpt-4.1", "openai"),
    ("o3-mini", "openai"),
    ("claude-3-5-sonnet", "anthropic"),
    ("anthropic/claude-3-7-sonnet", "anthropic"),
    ("llama-3.1-70b", "unknown"),
    ("gemini-2.0-flash", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
    (42, "unknown"),
])
def test_derive_family(model, family):
    assert derive_family(model) == family
