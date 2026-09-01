---
name: stall-detection
description: 停滞检测：Leader 每轮迭代记录新发现数，连续 0 新发现触发结构性转向（≥2 次）或上报人类（≥4 次），避免无人值守循环原地打转。触发词：停滞、卡住、没进展、原地打转、stall、stale、pivot、转向、deadlock。
assign_when: Leader 编排迭代循环、监控任务进展、判断是否需要转向或上报人类时分配。
---

# Skill: stall-detection

无人值守迭代循环的停滞检测：每轮记录**新发现数**（具体新增条目，而非主观"有价值结果"），
连续 0 新发现累积 `stale_count`，达到阈值强制转向。基于 `iteration_log`（`src/loop/iteration_log.py`）。

## 输入

- `run_id`：运行标识（仅允许 `[A-Za-z0-9-_.]`，禁止路径逃逸）
- `phase`：当前阶段名（如 `research` / `coding` / `testing`）
- `new_findings`：本轮**新增条目数**（新证据 / 被证伪假设 / 候选方向），必须 ≥ 0
- `direction`（可选）：本轮尝试的方向，供再生成环节拒绝过于接近的候选
- 台账路径：`<root>/runs/<run_id>.iterations.jsonl`（root 为产物目录 `src/data/shared`）

## 执行步骤

1. **每轮迭代记录**：`note(root, run_id, phase, new_findings[, direction])`
   - `new_findings > 0` → `stale_count` 归零
   - `new_findings == 0` → `stale_count` 累加 1
   - 返回 `{"stale_count": N, "pivot": "none|structural|human"}`
2. **裁决转向**：
   - `stale_count >= 2` → `pivot = "structural"`：改变**结构性约束**（换问题拆解、换路径、换策略），不是调战术参数
   - `stale_count >= 4` → `pivot = "human"`：标记需要人类关注，上报 Leader/人工
   - 其余 → `pivot = "none"`：继续当前方向
3. **回读历史**：`show(root, run_id)` 取回全部记录，供复盘/审计

## 输出（STALL_STATUS）

```json
{
  "run_id": "task-20260831-01",
  "phase": "testing",
  "new_findings": 0,
  "stale_count": 2,
  "pivot": "structural",
  "action": "CHANGE_STRUCTURAL_DIRECTION"
}
```

- `pivot = "none"` → 输出 `STALL_OK`，继续迭代
- `pivot = "structural"` → 输出 `STALL_PIVOT_STRUCTURAL`，强制结构性转向
- `pivot = "human"` → 输出 `STALL_ESCALATE_HUMAN`，上报人类关注

## 依赖工具

- L1 基座：`iteration_log`（`src/loop/iteration_log.py`，纯标准库，追加式 JSONL + 防逃逸校验）
- 外部依赖：无（fcntl 仅 POSIX 可用，Windows 静默退化，依赖单编排者契约）

## 失败处理

- `run_id` 非法（`../`、含 `/`、空、`.`/`..`）→ `ValueError`，拒绝写入
- `new_findings < 0` → `ValueError`，拒绝写入
- 台账文件损坏/缺行 → 容忍跳过，保留最后一个合法 `stale_count`
- 写入失败（磁盘满/权限）→ 异常上抛给编排循环，绝不静默吞掉

## 安全边界

- 只写 `<root>/runs/` 目录，`run_id` 白名单字符防路径逃逸
- 追加式写入，永不覆盖历史记录（append-only）
- 只计数、只改方向，**不评判质量**——质量/正确性归属跨模型评审（review-gate）

## 复用价值

- Leader 编排循环的通用护栏：任何"跑不动/没进展"的迭代都能被捕获并强制转向
- 与 `evidence-log`（记录做了什么）互补：本 Skill 记录"有没有新产出"
- 台账数据可被 `retrospective`（复盘）消费，量化"卡了多久才转向"

## 协同关系

- **上游**：接收 `task-coordination`（任务派发）、`project-management`（阶段推进）的迭代上下文
- **下游**：`pivot=structural` → 通知 Leader 换策略；`pivot=human` → 触发 `ApprovalManager` 人工关注
- **并行**：与 `review-gate`（质量裁决）解耦——本 Skill 只管方向，不管质量

## 里程碑

- 记录：输出 `STALL_LOGGED`（本轮迭代已记账）
- 转向：输出 `STALL_PIVOT_STRUCTURAL` / `STALL_ESCALATE_HUMAN`
- 若 `STALL_ESCALATE_HUMAN` → 通知 Leader 上报人类关注
