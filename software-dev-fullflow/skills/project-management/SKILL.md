---
name: project-management
description: 启动多 Worker 项目、管理 plan.md 单一真相源、跟踪任务状态/进度/依赖、处理阻塞任务。触发词：项目管理、启动项目、plan.md、任务拆解、进度跟踪。
assign_when: 招聘经理（HR）或 Team Leader 需要为项目建立 plan、拆解任务、跟踪里程碑时分配。
---

# Skill: project-management

一个项目有：Project Room（Matrix）、`plan.md`（单一真相源）、`meta.json`、以及 `shared/tasks/{task-id}/` 下各任务文件。

```
shared/projects/{project-id}/
├── meta.json
└── plan.md
```

> 来源：对齐比赛官方 AgentTeams `project-management` skill（`references/refs/agent-teams/manager/agent/skills/project-management/SKILL.md`）。

## 关键约束（Gotchas）

- **`plan.md` 是单一真相源**：所有任务状态/分配/依赖都在这，改动后必须同步到 MinIO。
- **Project Room 必须始终包含人类 admin**：不可省。
- **REVISION_NEEDED 未决时不得进入下一阶段**：先完成修订。
- **任务全部完成步骤在任何模式都强制**：更新 meta.json + plan.md + 通知 admin。
- 发消息前先读 SOUL.md，用其人格和语言。

## 使用流程

1. 建 Project Room，邀请 admin + 相关 Worker。
2. 写 `plan.md`（任务清单、状态、分配、依赖）+ `meta.json`，同步 MinIO。
3. 按 plan.md 拆解任务，分派给 Worker，跟踪状态。
4. 任务阻塞 / 计划变更 → 走 `plan-changes` 流程（升级/改计划）。
5. 全部完成后更新 meta.json + plan.md，通知 admin。

## 依赖工具

- Matrix 房间、MinIO 共享存储。

## 失败处理

- 阻塞任务 → 升级给 Manager / HR，不静默卡死。
- plan.md 不同步 → 每次改动后强制同步 MinIO。

## 安全边界

- 只在项目授权范围内操作。
- 变更计划需留痕，可审计。

## 里程碑

- 配合 `dynamic-hiring` 输出 `TEAM_READY` / `PROJECT_ARCHIVED`。
