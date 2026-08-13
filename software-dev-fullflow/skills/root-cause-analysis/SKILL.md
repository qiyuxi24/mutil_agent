---
name: root-cause-analysis
description: 基于任务说明与代码仓库，定位缺陷根因，产出含证据链的根因分析报告（RCA Report）。触发词：根因、定位、为什么、root cause、RCA、调查。
assign_when: 根因定位员（RootCause）需要深入代码仓库定位缺陷根因时分配。
---

# Skill: root-cause-analysis

针对一个已结构化的 `task-spec`，在代码仓库中定位缺陷的**根因**（文件/函数/行 + 根因类型 + 证据链），产出 `root-cause-report`。**本 Skill 只做只读分析，不做修复。**

## 输入

- `task-spec.json`（含缺陷描述、复现信息、相关证据）。
- 相关代码路径 / 日志 / 调用栈（由 Manager 或共享状态提供）。

## 执行步骤

1. **假设生成**：基于缺陷现象，生成 2-3 个根因候选假设（空指针/并发/资源泄漏/配置错误/逻辑错误等）。
2. **证据收集**：用 `code-search` 定位相关符号、`repo-context` 了解模块结构、`git-operations` 查 `git blame` 与变更历史、`knowledge-rag` 查历史同类根因。
3. **逐项验证**：对每个假设用日志/Trace/复现步骤逐条排除或确认，保留置信度最高的。
4. **定位到行**：把根因收敛到具体文件/函数/行，并给出触发条件。
5. **修复方向**：给出修复建议方向（不改代码，仅建议）。
6. **产出**：生成 `root-cause-report.json`，写入 `shared/tasks/{id}/root-cause.json`。

## 输出（ROOT_CAUSE_FOUND）

```json
{
  "task_id": "T-0001",
  "root_cause": {
    "file": "src/worker/task.go",
    "function": "processTask",
    "line": 124,
    "type": "null_pointer|race|leak|config|logic",
    "trigger": "当 task 为空时..."
  },
  "evidence_chain": ["log://...", "blame://...", "trace://..."],
  "repro_steps": ["..."],
  "fix_direction": "在 processTask 开头增加空值校验",
  "confidence": "high|medium|low",
  "status": "ROOT_CAUSE_FOUND|INCONCLUSIVE"
}
```

## 依赖工具

- L1 基座：`code-search`、`repo-context`、`git-operations`、`knowledge-rag`
- MCP/外部：日志查询、Trace 检索

## 失败处理

- 证据不足 → 输出 `INCONCLUSIVE`（疑似根因 + 置信度 + 需补充证据），交 Manager 决定是否加派 Worker 深挖。
- 误判 → 由 Tester 的验证闸门反向打回（闭环回滚），重新定位。

## 安全边界

- 只读代码与日志，**不执行修复、不写文件**。
- 涉及安全漏洞的根因，脱敏后入知识库，不写入公共日志明文。

## 里程碑

- 输出：`ROOT_CAUSE_FOUND`（交接 Fixer）。
- 若 `INCONCLUSIVE` → 通知 Manager 走决策/加派。
