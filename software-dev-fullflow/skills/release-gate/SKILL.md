---
name: release-gate
description: 发布前门禁检查（测试通过/代码评审/兼容性/回滚预案），执行灰度发布并监控，失败时触发回滚。触发词：发布、上线、灰度、回滚、release、deploy、gate。
assign_when: 发布确认员（Releaser）需要对修复结果执行发布门禁与灰度回滚时分配。
---

# Skill: release-gate

对一次修复做发布前的门禁检查，执行灰度发布并监控，失败时触发回滚。**高风险动作需人工审批（Human-in-the-loop）。**

## 输入

- `TEST_VERDICT`（必须 PASS）、变更清单、发布配置、回滚预案。

## 执行步骤

1. **门禁检查**：确认测试全绿 + 代码评审通过 + 兼容性无破坏 + 回滚预案就绪。
2. **灰度策略**：制定灰度批次（如 5% → 30% → 100%），高风险用金丝雀。
3. **发布执行**：走 CI/CD 流水线，小流量放量，实时监控。
4. **监控判定**：观察错误率/时延/告警，达阈值即触发回滚。
5. **产出**：`release-plan` + `RELEASE_VERDICT`，写入 `shared/tasks/{id}/release.json`。

## 输出（RELEASE_VERDICT）

```json
{
  "task_id": "T-0001",
  "gate_checks": {"tests": "pass", "review": "pass", "compat": "pass", "rollback_plan": "ready"},
  "gray_strategy": {"batches": [0.05, 0.3, 1.0], "canary": true},
  "verdict": "RELEASE_OK|RELEASE_ROLLED_BACK",
  "evidence_refs": ["deploy://...", "metric://..."]
}
```

## 依赖工具

- L1 基座：`evidence-log`、`knowledge-rag`（查历史发布问题）
- MCP/外部：CI/CD 流水线、监控告警、K8s/云部署、Feature Flag

## 失败处理

- 门禁未通过 → 不发布，打回相应环节（测试红→Tester；评审拒→Manager）。
- 灰度中监控异常 → **自动回滚**到上一稳定版本，记录 `RELEASE_ROLLED_BACK`。
- 回滚失败 → 升级人工 + 熔断。

## 安全边界

- 高风险发布需人工审批；灰度先小流量，权限最小化。
- 发布动作全量审计。

## 里程碑

- 输出：`RELEASE_OK`（交接 Retrospector）或 `RELEASE_ROLLED_BACK`（打回 Fixer）。
