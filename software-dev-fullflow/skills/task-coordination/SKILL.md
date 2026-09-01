---
name: task-coordination
description: 团队任务协调：Leader 从一套班子里按阶段挑人、派单、跟进里程碑、协调员工间通信、升级阻塞。触发词：协调、派单、分配、跟进、里程碑、挑人、coordinate、assign、dispatch。
assign_when: Leader（固定编排者）需要在团队内按阶段挑人派单、跟进里程碑、协调员工间通信、处理阻塞任务时分配。
---

# Skill: task-coordination

Leader（固定编排者）的**核心编排能力**：从一套完整班子里按阶段挑选员工参与、派单、跟进里程碑、协调员工间通信、处理阻塞。对应 AgentTeams Team Leader 的协调职责。

## 关键约束（Gotchas）

- **Leader 决定每阶段参与员工**：没有「修复/搭建」双模式，Leader 按任务从一套班子里挑人。
- **里程碑握手**：每个员工完成后 @mention 下一阶段并输出对应里程碑词。
- **员工间通信**：Tester 可向 Backend 要开发日志（走 `team-comm`），Leader 负责协调。
- **质量门禁不主观干预**：@tester 和 @releaser 的 PASS/FAIL 是客观裁判，Leader 尊重。

## 一套班子（按阶段挑人）

| 阶段 | 可选员工 | 里程碑 |
|------|---------|--------|
| P 计划 | @aggregator（产品经理） | `TASK_SPEC_READY` |
| D 分析 | @rootcause（架构师） | `ROOT_CAUSE_FOUND` |
| D 编码 | @frontend / @backend / @fixer | `SITE_READY` / `BACKEND_READY` / `FIX_APPLIED` |
| C 检查 | @tester（质量门禁） | `TEST_PASSED` / `TEST_FAILED` |
| A 处置 | @releaser（DevOps） | `RELEASE_OK` / `RELEASE_ROLLED_BACK` |
| A 处置 | @retrospector（复盘） | `RETROSPECT_DONE` |

## 使用流程

1. **解析任务**：判断需要哪些角色能力（需求/架构/前端/后端/修复/测试/发布/复盘）。
2. **按阶段挑人**：从一套班子决定每阶段参与者，记录到 `stage_participants`。
3. **派单**：@mention 对应员工，附上一阶段产物路径 + 期望里程碑。
4. **协调通信**：员工间需要信息时，协调走 `team-comm`（如 Tester→Backend 要日志）。
5. **跟进里程碑**：每收到一个里程碑，检查协议合规，推进下一阶段。
6. **收尾沉淀**：@retrospector 复盘后，让全员用 `agent-memory` 沉淀经验。

## 依赖工具

- `team-comm`（员工间通信）、`agent-memory`（经验沉淀）、`project-management`（计划）。
- AgentBus request-reply / Matrix @mention。

## 失败处理

- 员工无响应：超时重试一次，仍无则跳过标记 FAIL。
- 死循环：全局打回 > 10 次终止任务。
- 某阶段缺能力：升级请求人类介入，不硬派。

## 安全边界

- 只在团队授权范围内操作；全程留痕可审计。
- 尊重质量门禁（tester/releaser）的确定性裁判，不主观干预。

## 里程碑

- 组队完成：`TEAM_READY`（Leader 确认参与员工名单）。
- 闭环完成：`RETROSPECT_DONE`（全员经验已沉淀）。
