---
name: review-gate
description: 跨模型评审路由裁决：对一轮评审结果做 stop/continue/escalate 确定性转移，执行同族拒绝、positive 阈值与终审器语义。触发词：评审、裁决、路由、review、verdict、score、gate、跨模型、同族。
assign_when: 需要判定一轮评审是否终结、是否继续或升级时分配（Tester/Releaser 评审环节、跨模型终审环节）。
---

# Skill: review-gate

对一轮评审结果做**确定性转移裁决**：`stop`（终结）/ `continue`（继续同后端评审）/ `review_unavailable`（裁决不可用，打回）。裁决逻辑由 `src/loop/review_gate.py`（`evaluate_transition`）可执行实现，保证安全关键的转移表可测试、可追溯，而不是只存在于散文里。

## 核心语义（安全关键，勿改动）

- **同族评审不能终结**：`executor_model` 与 `reviewer_model` 推导出的厂商家族相同 → `review_unavailable`（`identity_assurance="failed"`）。家族由 `derive_model_family` 从模型标识自动推导（`qwen/tongyi→qwen`、`deepseek→deepseek`、`glm/zhipu→zhipu`、`kimi/moonshot→moonshot`、`gpt/codex/o1..o4→openai`、`claude→anthropic`、`gemini→google`、`llama→meta`、`grok→xai` 等 13 家族），**不接受调用方直接传入家族字符串**。
- **positive 阈值**：`score >= 6` 且 `verdict ∈ {ready, almost}` 才算正向；否则 `continue`（下一轮沿用同一后端）。
- **输入校验（fail-closed）**：未知 backend / 未知 verdict / score 非有限或不在 `1..10` → `review_unavailable`。
- **终审器语义**：`requires_external_acquittal=True` 时仅 `codex` / `manual` 可担任终审；`oracle-pro` / `agy` / `llm-chat` 一律 `review_unavailable`；终审必须跨族 + 身份可推导。
- **manual 特例**：正向裁决必须 `manual_identity_reported=True`，且跨族 + 家族可推导，否则 `review_unavailable`。

## 输入

- `round_backend`：本轮评审后端（`codex` / `manual` / `oracle-pro` / `agy` / `llm-chat`，不含已剥离的 Copilot 后端）
- `score`：`1..10` 的浮点得分
- `verdict`：`ready` / `almost` / `not ready`
- `requires_external_acquittal`：本轮是否承担终审义务（默认 `False`）
- `executor_model` / `reviewer_model`：执行者与评审者的模型标识（用于推导家族）
- `manual_identity_reported`：manual 后端是否已上报模型身份（默认 `False`）

## 执行步骤

1. **取参**：收集一轮评审的 backend / score / verdict / 模型标识。
2. **调裁决**：调用 `evaluate_transition(...)`（或 CLI `python -m loop.review_gate`）。
3. **按转移行动**：
   - `stop` → 本轮评审终结，产出正向裁决（记录 `identity_assurance` 与 `reason`）。
   - `continue` → 沿用 `next_backend` 开启下一轮评审。
   - `review_unavailable` → 不终结、不通过，按 `reason` 打回（同族 → 换跨族评审者；未知族 → 补全模型标识；越界 → 修正得分）。
4. **留痕**：将 `Transition`（decision / next_backend / reason / identity_assurance）写入 `shared/tasks/{id}/evidence.jsonl`。

## 输出（REVIEW_VERDICT）

```json
{
  "task_id": "T-0001",
  "round_backend": "llm-chat",
  "score": 9,
  "verdict": "ready",
  "transition": {
    "decision": "stop",
    "next_backend": null,
    "requires_external_acquittal": false,
    "identity_assurance": "caller_declared",
    "reason": "HTTP reviewer returned a positive cross-family verdict; executor identity remains caller-declared"
  },
  "status": "REVIEW_STOP|REVIEW_CONTINUE|REVIEW_UNAVAILABLE"
}
```

## 依赖工具

- L1 基座：`evidence-log`（裁决留痕）、`loop.review_gate.evaluate_transition`（确定性裁决器）
- 外部依赖：无（纯标准库 `re` / `math` / `dataclasses`）

## 失败处理

- 未知 backend / verdict / 越界 score → `review_unavailable`，打回调用方修正参数。
- 同族评审 → `review_unavailable`（`identity_assurance="failed"`），要求换跨族评审者。
- 家族不可推导 → `review_unavailable`（`unverified`），要求补全模型标识。
- manual 未上报身份 / 终审器不合规 → `review_unavailable`，按 `reason` 指引补全。

## 安全边界

- 家族推导 fail-closed：命中多个家族返回 `unknown`，绝不猜测归属。
- 同族评审永不产生正向终结，杜绝"自己人评自己人"。
- 终审义务（`requires_external_acquittal`）只能由 `codex` / `manual` 承担，防止非策略后端混入终审。
- 裁决转移表冻结（`frozen=True`），结果可序列化审计。

## 复用价值

- 与 `root-cause-analysis` / `release-gate` 协同：评审结果先过本 Skill 裁决再进入发布门禁。
- 跨模型评审（执行者与评审者来自不同厂商）时强制保障评审独立性。
- 为 `retrospective`（复盘）提供每次裁决的 `reason` 与 `identity_assurance` 数据。

## 协同关系

- **上游**：`code-gen`（产出待评审物）、`evidence-log`（历史评审证据）
- **下游**：`release-gate`（裁决通过 → 进入发布门禁）、`root-cause-analysis`（裁决失败 → 回到根因）
- **并行**：与 `AuditLogger`（`src/loop/audit_logger.py`）协同留痕

## 里程碑

- `stop` → 输出 `REVIEW_STOP`（正向终结，交接 Releaser 进入发布门禁）
- `continue` → 输出 `REVIEW_CONTINUE`（开启下一轮，沿用同后端）
- `review_unavailable` → 输出 `REVIEW_UNAVAILABLE`（打回，附 `reason` 指引）
