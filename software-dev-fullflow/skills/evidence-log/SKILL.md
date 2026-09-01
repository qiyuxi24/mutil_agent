---
name: evidence-log
description: 执行证据沉淀：把 Trace/Log/决策/报告写入结构化审计日志，形成可追溯证据链。触发词：日志、证据、审计、记录、log、evidence、audit、trace。
assign_when: 任何 Worker 需要记录执行步骤、决策理由、中间产物时分配。
---

# Skill: evidence-log

结构化记录 Agent 执行的每一步，形成从根因→修复→测试→发布的完整证据链，支持审计追溯与复盘分析。对齐 `AuditLogger`（`src/loop/audit_logger.py`）的字段规范。

## 输入

- 记录内容：`event_type`（decision/handoff/human_intervention/milestone/error/state）、`action`（动作名）、`result`（PASS/FAIL/OK）、`detail`（附加信息）
- 关联信息：`trace_id`（任务闭环）、`agent_id`（触发者）、`room_id`（Matrix 房间，可选）
- 写入模式：`append`（追加）/ `query`（查询历史）/ `export`（导出证据链）

## 执行步骤

1. **记录写入**：
   - 补全字段：`timestamp`（ISO8601 自动生成）、`trace_id`（从任务上下文获取）、`agent_id`（当前 Worker 名）
   - 校验字段完整性（必填：`event_type`、`action`、`result`）
   - 追加写入 `shared/tasks/{id}/evidence.jsonl`（JSON Lines 格式，一行一条）
2. **证据查询**：
   - 按 `trace_id` 查询某任务的完整证据链
   - 按 `event_type` 过滤（如仅查看 `error` 事件）
   - 按时间范围查询
3. **证据导出**：
   - 导出为 JSON Lines（原始格式）
   - 导出为 Markdown 时间线（供人阅读）
   - 导出为 CSV（供工具分析）
4. **证据链验证**：
   - 检查闭环完整性：根因→修复→测试→发布 四步是否都有证据记录
   - 缺失环节标记 `EVIDENCE_GAP`

## 输出（EVIDENCE_LOGGED）

```json
{
  "task_id": "T-0001",
  "operation": "append|query|export",
  "entries_appended": 1,
  "evidence_chain": {
    "total_entries": 12,
    "gaps": [],
    "closed_loop": true
  },
  "entry": {
    "timestamp": "2026-08-16T10:30:00Z",
    "trace_id": "T-0001",
    "agent_id": "fixer",
    "event_type": "decision",
    "action": "apply_fix_patch",
    "result": "PASS",
    "detail": {
      "branch": "fix/T-0001",
      "changed_files": ["src/worker/task.go"],
      "patch_hash": "abc123"
    }
  },
  "status": "OK"
}
```

## 依赖工具

- L1 基座：`AuditLogger`（`src/loop/audit_logger.py`，提供 JSON Lines 写入与线程安全）
- 外部依赖：无（纯标准库 `json` + `logging`）

## 失败处理

- 日志目录（`shared/tasks/{id}/`）不存在 → 自动创建，标记 `DIR_CREATED`
- 日志文件写入失败（磁盘满/权限）→ 缓存到内存队列（最多 100 条），标记 `WRITE_DEGRADED`
- 查询无结果 → 返回空列表，标记 `NO_ENTRIES`
- 证据链不完整（缺失环节）→ 标记 `EVIDENCE_GAP`，列出缺失环节

## 安全边界

- 只写入 `shared/tasks/{id}/` 目录，不触及系统路径
- 不记录凭据、密钥、Token 等敏感信息（写入前自动脱敏）
- 日志文件大小限制：单文件 ≤ 10MB，超过自动轮转（`evidence.jsonl.1`）
- 线程安全：多 Worker 并发写入同一证据文件时加锁保护

## 复用价值

- 所有 Worker 在执行关键步骤时均调用本 Skill 记录证据
- 证据链可追溯性满足审计与合规要求
- 为 `retrospective`（复盘）和 `knowledge-rag`（知识写入）提供结构化输入

## 协同关系

- **上游**：接收所有其他 Skill 的执行记录（`git-operations`、`code-search`、`code-gen`、`root-cause-analysis` 等）
- **下游**：为 `retrospective`（复盘分析）、`knowledge-rag`（经验沉淀）提供结构化证据输入
- **并行**：与 `AuditLogger`（`src/loop/audit_logger.py`）协同，复用其 JSON Lines 写入引擎

## 里程碑

- 写入：输出 `EVIDENCE_LOGGED`（证据已记录）
- 导出：输出 `EVIDENCE_EXPORTED`（证据链已导出）
- 若 `EVIDENCE_GAP` → 通知 Manager 检查闭环完整性