---
name: test-generation
description: 基于修复内容与验收标准，生成/更新测试用例，执行测试与静态检查，作为确定性验证闸门判定修复是否通过。触发词：测试、验证、用例、test、闸门。
assign_when: 测试验证员（Tester）需要对修复结果执行验证闸门判定时分配。
---

# Skill: test-generation

基于修复 diff 与验收标准，生成/更新测试用例，执行测试与静态检查，产出**确定性验证结论**（`TEST_VERDICT`）。**本 Skill 是质量门禁，是闭环收敛的确定性裁判。**

## 输入

- 修复 diff（`fix.json`）、`task-spec.json` 的验收标准、`impact-report.json` 的受影响测试范围。

## 执行步骤

1. **测试范围确定**：结合 impact-report 确定受影响测试 + 需新增测试。
2. **用例生成**：针对验收标准生成测试用例（正常/边界/异常路径），覆盖缺陷触发点。
3. **执行**：在隔离环境跑测试 + 静态分析 + 覆盖率。
4. **判定**：按「全部通过 + 无新增静态告警」输出 `TEST_VERDICT`（PASS/FAIL）。
5. **产出**：测试用例集 + 执行报告，写入 `shared/tasks/{id}/test.json`。

## 输出（TEST_VERDICT）

```json
{
  "task_id": "T-0001",
  "verdict": "PASS|FAIL",
  "test_cases": [{"name": "TestProcessTask_NullTask", "result": "pass"}],
  "summary": {"total": 12, "passed": 12, "failed": 0, "coverage": 0.85},
  "static_check": {"lint": "pass", "type_check": "pass"},
  "evidence_refs": ["test-report://..."]
}
```

## 依赖工具

- L1 基座：`code-search`、`repo-context`、`evidence-log`
- MCP/外部：测试框架（pytest/JUnit 等）、CI、静态分析、覆盖率工具

## 失败处理

- 测试失败 → 输出失败详情 + 关联断言，**打回 Fixer**（闭环回滚）。
- 测试环境不可用 → 降级为静态分析 + 类型检查兜底并标注降级。
- 用例生成失败 → 以手工指定用例为准。

## 安全边界

- 测试在隔离环境执行，**不触碰生产数据**。
- 禁止在测试中执行生产写操作；测试结果落盘为执行证据可审计。

## 里程碑

- 输出：`TEST_PASSED`（交接 Releaser）或 `TEST_FAILED`（打回 Fixer）。
- **本 Skill 是收敛核心**：宁可漏测返回 FAIL，也不允许未验证即放行。
