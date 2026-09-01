"""验收门 Acceptance Gate —— 验收结论的机器可校验前置门槛。

定位：本模块与 `ApprovalManager`（人工审批）互补，形成一个两层把关：
  - ApprovalManager：高风险动作需「人」点头（人工审批）；
  - AcceptanceGate ：验收结论需满足「谁执行谁验收」的基本纪律（自动校验）。

设计约束：
  - 零依赖：不 import 任何其他 loop 模块（尤其不依赖 review_gate），
    便于在迁移批次内独立演进与测试。`derive_family` 为内嵌极简版，
    覆盖 deepseek / qwen / openai / anthropic / unknown 五类，字段与
    review_gate.derive_model_family 对齐（后续批次可统一收敛）。
  - 纯函数 + dataclass，无 IO，fail-closed（任何异常输入均视为「不通过」）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

# ------------------------------------------------------------------ #
# 模型家族推导（内嵌极简版）
# ------------------------------------------------------------------ #
# 与 review_gate.derive_model_family 对齐的子串规则（不 import，保持零依赖）。
# 覆盖：deepseek / qwen / openai / anthropic / unknown。


def derive_family(model: str) -> str:
    """从模型名推导其厂商家族（小写、去空白、含关键词即命中，未知归 unknown）。"""
    if not isinstance(model, str):
        return "unknown"
    m = model.strip().lower()
    if not m:
        return "unknown"
    if "deepseek" in m:
        return "deepseek"
    if "qwen" in m or "qwq" in m:  # QwQ 为通义千问（Qwen）系列推理模型
        return "qwen"
    if "openai" in m or "gpt" in m or "o1" in m or "o3" in m or "o4" in m:
        return "openai"
    if "anthropic" in m or "claude" in m:
        return "anthropic"
    return "unknown"


# ------------------------------------------------------------------ #
# 验收判定结果
# ------------------------------------------------------------------ #


@dataclass
class AcceptanceVerdict:
    """一次验收调用的结构化结果（fail-closed：不通过时给出 reason）。

    字段：
      accepted : 是否通过验收门
      reason   : 不通过原因（通过时为空字符串）
      verdict_id : 通过时回显验收单号；不通过时为空字符串
    """

    accepted: bool
    reason: str = ""
    verdict_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转为字典，方便序列化 / 落审计。"""
        return {"accepted": self.accepted, "reason": self.reason, "verdict_id": self.verdict_id}

    def __bool__(self) -> bool:
        return self.accepted


def accept(
    claim: str,
    executor: str,
    reviewer: str,
    verdict_id: str,
) -> AcceptanceVerdict:
    """校验一条验收结论是否满足验收门纪律（fail-closed）。

    校验规则（全部命中才 accepted）：
      1. verdict_id 非空且以 `review-` 开头（对齐现有 audit 习惯）；
      2. claim 非空（验收总得有内容）；
      3. reviewer 非空且 != executor（执行者不能自评验收自己）；
      4. reviewer != "self"（self 视为自评）；
      5. 评审模型家族 != 执行模型家族（同族评审视为利益相关，拒绝）。

    任何参数异常（None / 非字符串 / 校验失败）均返回不通过，不抛异常。

    参数：
      claim      : 验收结论/声明内容
      executor   : 执行者（谁交付的活）
      reviewer   : 评审者（谁验收）
      verdict_id : 验收单号（须以 `review-` 开头）

    返回：
      AcceptanceVerdict，见类文档。
    """

    def _ok(reason: str = "") -> AcceptanceVerdict:
        return AcceptanceVerdict(accepted=True, reason=reason, verdict_id=verdict_id)

    def _reject(reason: str) -> AcceptanceVerdict:
        return AcceptanceVerdict(accepted=False, reason=reason, verdict_id="")

    # 1. verdict_id：非空、字符串、以 review- 开头
    if not isinstance(verdict_id, str) or not verdict_id.strip():
        return _reject("verdict_id missing or empty")
    if not verdict_id.startswith("review-"):
        return _reject("verdict_id must start with 'review-'")

    # 2. claim：非空字符串
    if not isinstance(claim, str) or not claim.strip():
        return _reject("claim missing or empty")

    # 3. reviewer / executor：非空、字符串
    if not isinstance(reviewer, str) or not reviewer.strip():
        return _reject("reviewer missing or empty")
    if not isinstance(executor, str) or not executor.strip():
        return _reject("executor missing or empty")

    reviewer = reviewer.strip()
    executor = executor.strip()

    # 4. 执行者不能自评
    if reviewer == "self":
        return _reject("reviewer must not be 'self'")
    if reviewer == executor:
        return _reject("executor cannot review their own work")

    # 5. 同模型家族视为利益相关，拒绝
    if derive_family(reviewer) == derive_family(executor):
        return _reject(
            "same model family between executor and reviewer "
            f"(family={derive_family(executor)!r})"
        )

    return _ok()


# ------------------------------------------------------------------ #
# 模块自检（可选）：python -m loop.acceptance_gate
# ------------------------------------------------------------------ #

if __name__ == "__main__":  # pragma: no cover
    _checks = [
        accept("交付完成", "deepseek-v4-flash", "qwen-plus", "review-42"),
        accept("交付完成", "deepseek-v4-flash", "deepseek-v4", "review-42"),
        accept("交付完成", "deepseek-v4-flash", "deepseek-v4-flash", "review-42"),
        accept("", "deepseek-v4-flash", "qwen-plus", "review-42"),
        accept("交付完成", "deepseek-v4-flash", "qwen-plus", "42"),
        accept("交付完成", "deepseek-v4-flash", "self", "review-42"),
    ]
    for _v in _checks:
        print(_v.to_dict())
    print(f"total={len(_checks)} "
          f"accepted={sum(1 for _v in _checks if _v.accepted)} "
          f"rejected={sum(1 for _v in _checks if not _v.accepted)}")
