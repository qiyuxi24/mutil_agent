---
name: impact-analysis
description: 评估修复方案的影响面：受影响模块/调用方/测试/兼容性，给出影响清单与风险分级，为发布与测试范围提供依据。触发词：影响面、影响、波及、impact、风险。
assign_when: 根因定位员（RootCause）在定位完成后、修复前评估改动波及范围时分配。
---

# Skill: impact-analysis

评估「根因修复」将会波及的范围：哪些模块、调用方、测试、外部契约受影响，给出影响清单与风险分级。**本 Skill 只读分析，不改代码。**

## 输入

- `root-cause-report.json`（根因位置）。
- 拟修复的改动范围（文件/函数级）。
- 仓库依赖图 / 调用链（`repo-context` 提供）。

## 执行步骤

1. **改动点确认**：明确拟修改的文件/函数/接口。
2. **下游调用追踪**：用 `code-search` 找出所有调用点、`repo-context` 看模块依赖。
3. **契约与兼容性**：判断是否破坏对外接口/数据结构/配置格式。
4. **测试范围**：列出受影响或需新增的测试（对齐 `test-generation`）。
5. **风险分级**：按「改动量 + 耦合度 + 兼容性破坏」给出 `risk`（low/medium/high）。
6. **产出**：生成 `impact-report.json`，并入 `shared/tasks/{id}/impact.json`。

## 输出（并入根因报告）

```json
{
  "task_id": "T-0001",
  "changed_files": ["src/worker/task.go"],
  "affected_modules": ["worker", "scheduler"],
  "callers": ["src/api/handler.go:88"],
  "compatibility_break": false,
  "affected_tests": ["test_task_test.go::TestProcessTask"],
  "risk": "low|medium|high",
  "needs_gray_release": false
}
```

## 依赖工具

- L1 基座：`repo-context`、`code-search`、`git-operations`
- MCP/外部：编译依赖分析、静态分析工具

## 失败处理

- 依赖图不完整 → 基于静态调用给出「保守影响清单」并标注不确定度。
- 波及范围过大（high risk）→ 输出风险预警 + 建议拆分修复，交 Manager 决策。

## 安全边界

- 只读分析，不改代码。
- 影响面结论需可溯源（引用具体文件/行）。

## 里程碑

- 并入 `ROOT_CAUSE_FOUND` 报告，供 Fixer 制定最小改动方案、Releaser 评估发布风险。
