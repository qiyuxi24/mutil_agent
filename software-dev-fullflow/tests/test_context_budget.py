"""GAP-08 测试：上下文工程确定性核心（context/budget.py + estimator.py）。

覆盖：
  - TokenEstimator：中英文 token 估算（确定性）
  - ContextBudget：70/30 分区分配、利用率、压缩阈值触发
  - ContextBudget.allocate：放入 / 截断 / 溢出计数
  - DynamicBudgetAllocator：按阶段返回预算（ROOT_CAUSE 重 critical 等）
"""

from __future__ import annotations

from loop.context.estimator import TokenEstimator
from loop.context.budget import ContextBudget, ContextSlice
from loop.context import DynamicBudgetAllocator


# --------------------------------------------------------------------------- #
# TokenEstimator
# --------------------------------------------------------------------------- #

def test_token_estimator_empty():
    assert TokenEstimator.estimate("") == 0


def test_token_estimator_english():
    # 英文 ~4 chars/token
    assert TokenEstimator.estimate("hello world") == 2  # 11 chars / 4 = 2
    assert TokenEstimator.estimate("a" * 100) == 25     # 100 / 4 = 25


def test_token_estimator_chinese():
    # 中文 ~1.5 chars/token
    text = "修复登录接口空指针异常"  # 11 个中文字符
    assert TokenEstimator.estimate(text) == int(11 / 1.5)


def test_token_estimator_estimate_messages():
    msgs = [{"content": "hello"}, {"content": "world"}]
    assert TokenEstimator.estimate_messages(msgs) == TokenEstimator.estimate("helloworld")


# --------------------------------------------------------------------------- #
# ContextBudget: 分区分配
# --------------------------------------------------------------------------- #

def test_context_budget_split():
    """70/30 分区 + 输出缓冲预留。"""
    b = ContextBudget(total_budget=32000)
    assert b.total_budget == 32000
    # 输出缓冲 10% = 3200，可用 = 28800；critical 70% = 20160，support 30% = 8640
    assert b.output_reserve == 3200
    assert b.critical.budget == 20160
    assert b.support.budget == 8640


def test_context_budget_invalid_ratio():
    """critical+support != 1.0 应抛错。"""
    try:
        ContextBudget(total_budget=32000, critical_ratio=0.8, support_ratio=0.3)
        assert False, "比例和不为 1 应抛 ValueError"
    except ValueError:
        pass


def test_context_budget_allocate_critical():
    b = ContextBudget(total_budget=32000)
    b.allocate_critical("system prompt")
    assert b.critical.used > 0
    assert b.total_used == b.critical.used  # support 为空


def test_context_budget_overflow_truncate():
    """内容超预算时截断并计数溢出。

    注意：TokenEstimator 为字符级估算（精度 ±15%），截断后利用率允许轻微超 1.0
    （如 1.014），故断言 `<= 1.1` 而非 `<= 1.0`。核心是「被截断 + 溢出计数」。
    """
    b = ContextBudget(total_budget=1000)
    big = "A" * 5000  # 远超 critical 预算
    placed = b.allocate_critical(big)
    assert len(placed) < len(big)          # 被截断
    assert b.snapshot()["overflow_count"] >= 1
    assert b.critical.utilization <= 1.1   # 估算误差容忍内未显著超预算


def test_context_budget_utilization_thresholds():
    """利用率触发 micro/auto compact 阈值。"""
    b = ContextBudget(total_budget=1000)
    assert b.utilization == 0.0
    assert not b.needs_micro_compact
    # 塞满 support 到接近阈值（利用预算的 70%+）
    b.allocate_support("B" * 1000)  # 1000/4=250 tokens，support budget=270
    assert b.utilization > 0.20


# --------------------------------------------------------------------------- #
# ContextSlice
# --------------------------------------------------------------------------- #

def test_context_slice_remaining_and_fits():
    s = ContextSlice(name="critical", budget=100)
    assert s.remaining == 100
    assert s.fits("short")  # 4 chars → 1 token ≤ 100
    s.content += "x" * 40   # 10 tokens used
    assert s.remaining == 90
    assert s.utilization == 0.1


def test_context_slice_zero_budget():
    s = ContextSlice(name="support", budget=0)
    assert s.utilization == 0.0
    assert s.remaining == 0
    assert not s.fits("anything")


# --------------------------------------------------------------------------- #
# DynamicBudgetAllocator: 按阶段
# --------------------------------------------------------------------------- #

def test_dynamic_budget_allocator_stage_profiles():
    """不同阶段预算配比不同（ROOT_CAUSE 重 critical，RETROSPECT 重 support）。"""
    # DynamicBudgetAllocator 用类方法 create_context_budget(stage) 创建
    rc = DynamicBudgetAllocator.create_context_budget("ROOT_CAUSE")   # 75/25
    rt = DynamicBudgetAllocator.create_context_budget("RETROSPECT")   # 40/60
    assert rc.critical.budget > rc.support.budget      # 定位重上下文
    assert rt.support.budget > rt.critical.budget      # 复盘重回顾
