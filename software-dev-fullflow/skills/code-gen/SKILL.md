---
name: code-gen
description: 基于根因与影响面报告，生成最小修复补丁并应用，产出可验证的修复结果。触发词：修复、补丁、修改、fix、patch、改动。
assign_when: 修复工程师（Fixer，可多实例按技术栈）需要生成并应用修复补丁时分配。
---

# Skill: code-gen

基于 `root-cause-report` + `impact-report`，生成**最小修复补丁**并应用到独立分支，产出可验证的修复结果。**默认只改必要代码，最小影响。**

## 输入

- `root-cause-report.json`、`impact-report.json`、`task-spec.json`（验收标准）。
- 技术栈约定（由 `repo-context` 提供）。

## 执行步骤

1. **分支隔离**：在独立功能分支上操作，`git checkout -b fix/T-0001`。
2. **最小改动**：仅修改根因点及必需关联处，遵循「最小影响原则」（见 impact-report）。
3. **补丁生成**：用 `code-search` 定位上下文，产出 diff，控制改动量。
4. **静态自检**：运行编译/类型检查/静态分析，确保无新增告警。
5. **变更说明**：生成 `change-note`（改了什么、为什么、影响）。
6. **产出**：应用补丁 + 生成 `fix-summary.json`，写入 `shared/tasks/{id}/fix.json`。

## 输出（FIX_APPLIED）

```json
{
  "task_id": "T-0001",
  "branch": "fix/T-0001",
  "changed_files": ["src/worker/task.go"],
  "diff_stats": {"files": 2, "additions": 8, "deletions": 3},
  "self_check": {"compile": "pass", "lint": "pass", "type_check": "pass"},
  "change_note": "在 processTask 开头增加空值校验，避免空指针",
  "status": "FIX_APPLIED|PARTIAL_FAILED"
}
```

## 依赖工具

- L1 基座：`git-operations`、`repo-context`、`code-search`
- MCP/外部：编译构建、静态分析、IDE 工具

## 失败处理

- 编译/静态检查失败 → 迭代修正，最多 N 次。
- 仍失败 → 输出 `PARTIAL_FAILED`（部分修复 + 失败原因），回退改动，交 Manager 决定更换技术栈 Fixer 或人工介入。
- 修复引入新问题 → 由验证闸门（Tester）回滚打回。

## 安全边界

- 默认独立分支操作，**不直接改主分支**。
- 危险操作（改权限/删数据）需审批；凭据/密钥禁止硬编码。
- 改动用 `git diff` 可审计。

## 里程碑

- 输出：`FIX_APPLIED`（交接 Tester）。
- 若 `PARTIAL_FAILED` → 通知 Manager。
