# -*- coding: utf-8 -*-
"""Review Gate 跨模型评审路由裁决测试：同族拒绝、positive 阈值、终审器语义。"""

from __future__ import annotations

import pytest

from loop.review_gate import (
    POSITIVE_VERDICTS,
    VALID_BACKENDS,
    VALID_VERDICTS,
    Transition,
    derive_model_family,
    evaluate_transition,
)


# --------------------------------------------------------------------------- #
# 家族推导
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o", "openai"),
        ("o3-mini", "openai"),
        ("claude-sonnet-4", "anthropic"),
        ("gemini-2.5-pro", "google"),
        ("deepseek-v3", "deepseek"),
        ("deepseek-chat", "deepseek"),
        ("qwen2.5-72b", "qwen"),
        ("qwen3-max", "qwen"),
        ("kimi-k2", "moonshot"),
        ("glm-4", "zhipu"),
        ("llama-3.1-70b", "meta"),
        ("mistral-large", "mistral"),
        ("grok-4", "xai"),
        ("minimax-abab6.5", "minimax"),
        ("doubao-seed", "bytedance"),
        ("unknown-model", "unknown"),
        ("", "unknown"),
    ],
)
def test_derive_model_family(model: str, expected: str) -> None:
    assert derive_model_family(model) == expected


def test_derive_model_family_multiple_hits_is_unknown() -> None:
    # 命中多个家族 → fail-closed 返回 unknown
    assert derive_model_family("qwen-claude-7b") == "unknown"


# --------------------------------------------------------------------------- #
# 输入校验
# --------------------------------------------------------------------------- #

def test_unknown_backend() -> None:
    t = evaluate_transition(round_backend="nosuch-backend", score=8, verdict="ready")
    assert t.decision == "review_unavailable"
    assert t.identity_assurance == "unverified"
    assert "unknown reviewer backend" in t.reason


def test_unknown_verdict() -> None:
    t = evaluate_transition(round_backend="codex", score=8, verdict="maybe")
    assert t.decision == "review_unavailable"
    assert "unknown verdict" in t.reason


@pytest.mark.parametrize("bad_score", [0, 0.5, 10.5, 11, float("inf"), float("nan")])
def test_out_of_range_score(bad_score: float) -> None:
    t = evaluate_transition(round_backend="codex", score=bad_score, verdict="ready")
    assert t.decision == "review_unavailable"
    assert "score" in t.reason


# --------------------------------------------------------------------------- #
# 正向阈值（positive = score>=6 且 verdict in {ready, almost}）
# --------------------------------------------------------------------------- #

def test_low_score_is_continue() -> None:
    t = evaluate_transition(round_backend="codex", score=5.9, verdict="ready")
    assert t.decision == "continue"
    assert t.next_backend == "codex"


def test_negative_verdict_is_continue() -> None:
    t = evaluate_transition(round_backend="llm-chat", score=8, verdict="not ready")
    assert t.decision == "continue"
    assert t.next_backend == "llm-chat"


def test_score_6_ready_is_positive() -> None:
    t = evaluate_transition(round_backend="codex", score=6, verdict="ready")
    assert t.decision == "stop"


def test_positive_verdicts_are_frozen() -> None:
    assert POSITIVE_VERDICTS == {"ready", "almost"}
    assert VALID_VERDICTS == POSITIVE_VERDICTS | {"not ready"}


# --------------------------------------------------------------------------- #
# codex / oracle-pro / agy：正向即停止（非终审时）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("backend", ["codex", "oracle-pro", "agy"])
def test_non_finalizer_positive_stop(backend: str) -> None:
    t = evaluate_transition(
        round_backend=backend,
        score=7,
        verdict="almost",
        executor_model="gpt-4o",
        reviewer_model="claude-sonnet-4",
    )
    assert t.decision == "stop"
    assert t.next_backend is None
    assert t.identity_assurance == "not_required"


def test_oracle_pro_cannot_be_finalizer() -> None:
    t = evaluate_transition(
        round_backend="oracle-pro",
        score=8,
        verdict="ready",
        requires_external_acquittal=True,
        executor_model="gpt-4o",
        reviewer_model="claude-sonnet-4",
    )
    assert t.decision == "review_unavailable"
    assert t.requires_external_acquittal is True


def test_agy_cannot_be_finalizer() -> None:
    t = evaluate_transition(
        round_backend="agy",
        score=8,
        verdict="ready",
        requires_external_acquittal=True,
        executor_model="gpt-4o",
        reviewer_model="claude-sonnet-4",
    )
    assert t.decision == "review_unavailable"


# --------------------------------------------------------------------------- #
# llm-chat：跨族正向 → stop；同族 / 未知族 → review_unavailable
# --------------------------------------------------------------------------- #

def test_llm_chat_same_family_rejected() -> None:
    t = evaluate_transition(
        round_backend="llm-chat",
        score=8,
        verdict="ready",
        executor_model="qwen-max",
        reviewer_model="qwen2.5-72b",  # 同为 qwen 族
    )
    assert t.decision == "review_unavailable"
    assert t.identity_assurance == "failed"
    assert "same-family" in t.reason


def test_llm_chat_unknown_family_rejected() -> None:
    t = evaluate_transition(
        round_backend="llm-chat",
        score=8,
        verdict="ready",
        executor_model="custom-model-x",
        reviewer_model="claude-sonnet-4",
    )
    assert t.decision == "review_unavailable"
    assert t.identity_assurance == "unverified"


def test_llm_chat_cross_family_stop() -> None:
    t = evaluate_transition(
        round_backend="llm-chat",
        score=9,
        verdict="ready",
        executor_model="deepseek-v3",
        reviewer_model="claude-sonnet-4",  # deepseek 族 ≠ anthropic 族
    )
    assert t.decision == "stop"
    assert t.identity_assurance == "caller_declared"


def test_llm_chat_cannot_be_finalizer() -> None:
    t = evaluate_transition(
        round_backend="llm-chat",
        score=9,
        verdict="ready",
        requires_external_acquittal=True,
        executor_model="deepseek-v3",
        reviewer_model="claude-sonnet-4",
    )
    assert t.decision == "review_unavailable"


# --------------------------------------------------------------------------- #
# manual：需要报告身份、跨族、可推导
# --------------------------------------------------------------------------- #

def test_manual_missing_identity() -> None:
    t = evaluate_transition(
        round_backend="manual",
        score=8,
        verdict="ready",
        executor_model="qwen-max",
        reviewer_model="claude-sonnet-4",
        manual_identity_reported=False,
    )
    assert t.decision == "review_unavailable"
    assert "missing" in t.reason


def test_manual_same_family_rejected() -> None:
    t = evaluate_transition(
        round_backend="manual",
        score=8,
        verdict="ready",
        executor_model="glm-4",
        reviewer_model="zhipu-coder",  # 同为 zhipu 族
        manual_identity_reported=True,
    )
    assert t.decision == "review_unavailable"
    assert t.identity_assurance == "failed"


def test_manual_unknown_family_rejected() -> None:
    t = evaluate_transition(
        round_backend="manual",
        score=8,
        verdict="ready",
        executor_model="custom-x",
        reviewer_model="claude-sonnet-4",
        manual_identity_reported=True,
    )
    assert t.decision == "review_unavailable"


def test_manual_cross_family_stop() -> None:
    t = evaluate_transition(
        round_backend="manual",
        score=8,
        verdict="ready",
        executor_model="qwen-max",
        reviewer_model="claude-sonnet-4",
        manual_identity_reported=True,
    )
    assert t.decision == "stop"
    assert t.identity_assurance == "caller_declared"


# --------------------------------------------------------------------------- #
# 终审器语义（requires_external_acquittal）：仅 codex/manual 且必须跨族
# --------------------------------------------------------------------------- #

def test_codex_finalizer_cross_family_stop() -> None:
    t = evaluate_transition(
        round_backend="codex",
        score=9,
        verdict="ready",
        requires_external_acquittal=True,
        executor_model="gpt-4o",
        reviewer_model="claude-sonnet-4",  # openai 族 ≠ anthropic 族
    )
    assert t.decision == "stop"
    assert t.requires_external_acquittal is False
    assert t.identity_assurance == "caller_declared"


def test_codex_finalizer_same_family_rejected() -> None:
    t = evaluate_transition(
        round_backend="codex",
        score=9,
        verdict="ready",
        requires_external_acquittal=True,
        executor_model="gpt-4o",
        reviewer_model="codex-mini",  # 同为 openai 族 → 同族不能终结
    )
    assert t.decision == "review_unavailable"
    assert t.identity_assurance == "failed"


def test_codex_finalizer_unknown_family_rejected() -> None:
    t = evaluate_transition(
        round_backend="codex",
        score=9,
        verdict="ready",
        requires_external_acquittal=True,
        executor_model="custom-x",
        reviewer_model="claude-sonnet-4",
    )
    assert t.decision == "review_unavailable"
    assert t.requires_external_acquittal is True


def test_manual_finalizer_cross_family_stop() -> None:
    t = evaluate_transition(
        round_backend="manual",
        score=9,
        verdict="ready",
        requires_external_acquittal=True,
        executor_model="qwen-max",
        reviewer_model="deepseek-v3",  # qwen 族 ≠ deepseek 族
        manual_identity_reported=True,
    )
    assert t.decision == "stop"
    assert t.requires_external_acquittal is False


def test_manual_finalizer_same_family_rejected() -> None:
    t = evaluate_transition(
        round_backend="manual",
        score=9,
        verdict="ready",
        requires_external_acquittal=True,
        executor_model="qwen-max",
        reviewer_model="tongyi-lite",  # 同为 qwen 族
        manual_identity_reported=True,
    )
    assert t.decision == "review_unavailable"
    assert t.identity_assurance == "failed"


# --------------------------------------------------------------------------- #
# 常量 / CLI 冒烟
# --------------------------------------------------------------------------- #

def test_backends_exclude_copilot() -> None:
    # 已剥离 Copilot 集成：不应残留 copilot 相关后端
    assert VALID_BACKENDS == {"codex", "manual", "oracle-pro", "agy", "llm-chat"}
    assert not any("copilot" in b for b in VALID_BACKENDS)


def test_transition_is_frozen_and_serializable() -> None:
    t = evaluate_transition(round_backend="codex", score=8, verdict="ready")
    assert isinstance(t, Transition)
    # dataclass(frozen=True) → 修改会抛 FrozenInstanceError
    with pytest.raises(Exception):
        t.decision = "stop"  # type: ignore[misc]


def test_cli_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    from loop.review_gate import main

    # 通过 sys.argv 注入参数，验证 CLI 输出 JSON
    import sys

    old_argv = sys.argv
    try:
        sys.argv = ["review_gate.py", "--round-backend", "codex", "--score", "8", "--verdict", "ready"]
        main()
    finally:
        sys.argv = old_argv
    out = capsys.readouterr().out.strip()
    import json

    parsed = json.loads(out)
    assert parsed["decision"] == "stop"
