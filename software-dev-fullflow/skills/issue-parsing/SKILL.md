---
name: issue-parsing
description: 从多源（Issue系统/日志/用户反馈/监控告警）聚合缺陷与需求，去重、分类、归一化为结构化任务说明（TASK_SPEC），作为研发闭环输入。触发词：缺陷、需求、聚合、去重、triage、inbox。
assign_when: 缺陷聚合员（Aggregator）需要接收并结构化多源缺陷/需求输入时分配。
---

# Skill: issue-parsing

将多源原始缺陷/需求条目，加工成一份结构化、可执行的 `task-spec`，作为研发闭环（PDCA-P）的输入。**本 Skill 只做聚合与归一化，不做根因定位、不做修复。**

## 输入

- 原始条目列表，每条含：`source`（来源：issue/日志/反馈/告警）、`title`、`description`、`priority`、`severity`、`repro`（复现信息）、`log`（日志片段，可选）。
- 通过 `code-search` 或 `knowledge-rag` 检索是否存在同类已记录缺陷（用于去重与关联）。

## 执行步骤

1. **收集**：从各来源拉取未处理的原始条目。
2. **去重**：按「标题语义 + 涉及模块 + 日志特征」判定重复，保留最完整的一条，其余合并进 `related_issues`。
3. **分类**：按预置分类模型归入 `defect` / `feature` / `enhancement` / `unknown`。
4. **归一化**：将字段统一为规范 schema，计算 `priority`（P0/P1/P2/P3）与 `severity`。
5. **风险标记**：含敏感信息（凭据/个人信息）的条目脱敏打码；无法归类的进入「待人工确认」队列。
6. **产出**：生成 `task-spec.json`，写入共享状态 `shared/tasks/{id}/spec.json`。

## 输出（TASK_SPEC）

```json
{
  "task_id": "T-0001",
  "title": "...",
  "category": "defect|feature|enhancement",
  "priority": "P0|P1|P2|P3",
  "severity": "critical|major|minor|trivial",
  "acceptance_criteria": ["..."],
  "affected_modules": ["..."],
  "evidence_refs": ["issue://#123", "log://...", "alert://..."],
  "related_issues": ["T-0000"],
  "needs_human_review": false
}
```

## 依赖工具

- L1 基座：`code-search`、`knowledge-rag`、`evidence-log`
- MCP/外部：Issue 系统、日志查询、监控告警

## 失败处理

- 某来源不可用 → 跳过该源并标记 `source_degraded`，不阻塞整体。
- 去重冲突 → 按严重度 + 时间排序取最新，冲突项标记待人工仲裁。
- 无法归类 → 进「待人工确认」队列，`needs_human_review=true`。

## 安全边界

- 只读聚合，**绝不修改**任何缺陷源数据。
- 敏感信息脱敏后再输出；产物落盘 `shared/tasks/{id}/spec.json` 可审计。

## 里程碑

- 输出：`TASK_SPEC_READY`（交接 RootCause / Fixer）。
- 若有待人工确认项，同时 `@mention` 通知 Manager 走 Human-in-the-loop。
