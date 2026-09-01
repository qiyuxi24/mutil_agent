---
name: dynamic-hiring
description: 按项目需求动态组建/调整 Agent 团队——解析任务、识别角色缺口、拉人进群、裁员归档。触发词：招人、招聘、组队、动态团队、hire、fire、组建团队、拉人。
assign_when: 招聘经理（HR）需要为项目组建团队、识别能力缺口、或项目收尾时分配。
---

# Skill: dynamic-hiring

为每个项目「拉人进群」组建合适的 Agent 团队。本 Skill 是作品核心创新点「AI 公司式动态团队」的落地机制：**角色是动态的，固定的只是流程。**

## 输入

- 项目任务描述（Manager 下发）。
- 当前可用 Worker 池（`workers.yaml` 中的角色清单）。

## 执行步骤

1. **任务类型判断**：修复任务（走默认 6 角色）vs 搭建任务（按需招入 architect/backend/deployer）。
2. **角色缺口识别**：对照任务需要的 skill/能力，检查当前 Worker 池是否覆盖。缺 → 需 hire；覆盖 → 复用。
3. **组队决策**：
   - 复用：把现有 Worker 拉进项目 Team 群组。
   - 招聘：`agt create worker --name <role> --soul-file ...` 创建新 Worker + 挂载 skill，再拉进群组。
4. **建 Team**：创建/复用 Team CR，指定 Team Leader，把选定 Worker 加入 `workerMembers`。
5. **指派 Leader**：指定 Team Leader 协调。
6. **组队完成**：输出 `TEAM_READY`（含团队名单 + 群组房间）。
7. **能力缺口无法补齐**：输出 `TALENT_GAP`，不硬派不合适的人，报 Manager 决定是否外部补充/降级。

## 输出（TEAM_READY）

```json
{
  "task_id": "T-0001",
  "mode": "build",
  "team": ["architect", "frontend", "backend", "tester", "deployer"],
  "new_workers": ["backend", "deployer"],
  "team_room": "#proj-T-0001",
  "leader": "team-leader",
  "status": "TEAM_READY"
}
```

## 项目收尾（裁员 + 归档）

1. **经验归档**：把各成员的记忆沉淀到知识库（`shared/knowledge/`），不丢组织记忆。
2. **按需裁员**：项目结束 / 临时角色不再需要 → `agt delete worker <临时角色>` 回收。
3. **输出**：`PROJECT_ARCHIVED`（含归档 + 裁员清单）。

## 依赖工具

- 官方脚本：`skills/scripts/push-worker-skills.sh`（给 Worker 挂 skill）。
- AgentTeams CLI：`agt create/delete worker`、`agt create team`。

## 失败处理

- Worker 创建失败 → 重试；仍失败报 `TALENT_GAP`。
- 裁员时成员记忆未归档 → 先归档再裁，避免丢组织记忆。

## 安全边界

- 裁员前必须归档成员产出与记忆。
- 不删活跃任务在用角色；先冻结再回收。
- 组队决策留痕（写 `shared/agents/hr/memory/`），可审计。

## 里程碑

- `TEAM_READY`（组队完成）/ `TALENT_GAP`（缺能力）/ `PROJECT_ARCHIVED`（收尾）。
