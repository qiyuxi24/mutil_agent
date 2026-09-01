---
name: team-management
description: 创建/导入团队、管理团队成员构成、从团队增删 Worker、向 Team Leader 委派任务。触发词：组队、建团队、拉人、team、创建团队、加入团队。
assign_when: 招聘经理（HR）或管理员需要为项目组建/调整 Team 时分配。
---

# Skill: team-management

Team = 1 个 Team Leader + N 个 Worker。Leader 是带管理技能的特殊 Worker，负责在 Team 内拆解与委派任务。Manager 委派任务给 Team Leader，不直接 @ team workers。

> 来源：对齐比赛官方 AgentTeams `team-management` skill（`references/refs/agent-teams/manager/agent/skills/team-management/SKILL.md`）。

## 核心命令

```bash
# 创建 Team（Leader + 成员 Worker 必须已存在）
agt create team --name <TEAM_NAME> --leader-name <LEADER_NAME> --workers <w1>,<w2>

# 或 YAML 方式（声明式，可版本管理）
#   spec.workerMembers: [{name: <leader>, role: team_leader}, {name: <w>, role: worker}]
#   workerMembers 必须恰好 1 个 role=team_leader（CRD 强制）
```

## 关键约束（Gotchas）

- **Team Leader 是 Worker 容器**：同 runtime，但带 team-leader-agent skills。
- **Team workers 只和 Leader 通信**：groupAllowFrom=[Leader, Team Admin]，不含 Manager。
- **Manager 只和 Team Leader 通信**：不直接 @ team workers。
- **Team Room = Leader + Team Admin + 所有 team workers**。
- **Leader Room = Manager + Global Admin + Leader**（标准三方）。
- **Team Admin 默认 = Global Admin**。
- **Team 不拥有 Worker 运行时/生命周期**：改成员配置直接改那个 Worker CR。

## 使用流程

1. 确保 Leader + 各成员 Worker CR 已存在且 Running。
2. `agt create team` 或 apply Team YAML。
3. 验证：`agt get team <name> -o json` → phase=Active / readyWorkers=N。
4. @mention Leader 在 Leader Room 派单，Leader 在 Team Room 协调成员。

## 依赖工具

- AgentTeams CLI：`agt create/get/update team`。

## 失败处理

- 引用了不存在的 Worker → Team 创建失败，先创建 Worker。
- 缺 team_leader 成员 → CRD 校验失败，补 role=team_leader。

## 安全边界

- 只在授权范围内组建团队，不越权操作非本项目的 Worker。
- 组队决策留痕（写 `shared/agents/hr/memory/`），可审计。

## 里程碑

- 产出：Team CR 创建成功（配合 `dynamic-hiring` 输出 `TEAM_READY`）。
