# AgentTeams 迁移蓝图：现状梳理 + 迁移路径

> 目的：梳理「已实现的东西」vs「AgentTeams 平台真实能力」，给出从 `src/loop`（MAF 参考实现）
> 迁移到 **AgentTeams（比赛官方协同基点）** 的完整路径。
> 日期：2026-08-13

---

## 一、现状：我们实际实现了什么

### 1.1 已实现（可复用）

| 模块 | 位置 | 内容 | 可迁移性 |
|------|------|------|---------|
| **PDCA 状态机** | `src/loop/state.py` | 8 状态 + 6 里程碑 + 打回逻辑，确定性状态图 | ✅ 核心逻辑可复用（作为 Team/Worker 的协作协议） |
| **6 个研发 Agent 定义** | `src/loop/team.py` | aggregator/rootcause/fixer/tester/releaser/retrospector 的 soul + guidelines | ✅ **直接迁移**成 AgentTeams Worker 的 `soul` + `agents` 字段 |
| **Manager 调度循环** | `src/loop/manager.py` | 派单→验证→推进/打回（MAF 底座） | ⚠️ 概念可映射到 AgentTeams（Manager/Team Leader 委派），但机制不同，需重写为 AgentTeams 方式 |
| **Skill 工程体系** | `skills/` | 7 个核心 Skill（9 字段）+ 注册表 + 分配矩阵 | ✅ 挂载到 AgentTeams Worker（`push-worker-skills.sh`） |
| **可运行 demo** | `demo/` + `src/run.py` | MAF 端到端跑通 + mock 秒级演示 | ⚠️ MAF 底座，演示用；AgentTeams 上需重新跑 |

### 1.2 AgentTeams 平台当前实际状态（已探测）

```
agt get managers → default / Running / deepseek-v4-flash / copaw   ✅ Manager 已就绪
agt get workers  → No workers found                                ⚠️ 0 个研发 Worker
agt get teams    → No teams found                                  ⚠️ 0 个团队
skills           → 通过 Worker spec.skills 挂载（非独立资源）
```

**结论**：AgentTeams 平台**只部署了空壳**（Manager default 在跑），**还没有任何研发 Worker / Team / Skill**。

---

## 二、关键差异：src/loop vs AgentTeams

| 维度 | `src/loop`（MAF 参考实现） | AgentTeams（官方） |
|------|---------------------------|-------------------|
| Agent 形态 | Python 对象（`AgentRole` dataclass） | 声明式 **Worker CR**（YAML，soul/agents/skills 字段） |
| 协同机制 | 代码循环（`TeamManagerLoop.run()`） | **Matrix 房间 + @mention 委派**（Manager→Leader→Worker） |
| 调度者 | Manager 代码循环 | AgentTeams **Manager Agent**（LLM 驱动，自动匹配 Team） |
| 状态机 | `state.py` 确定性状态图 | 靠 Worker/Team 的协作上下文 + HEARTBEAT |
| 里程碑 | 代码 `advance()` | Matrix 房间 @mention 里程碑词 |
| Skill | 纯提示词注入（前端 demo） | **Manager 集中管理**，`push-worker-skills.sh` 分发 |

---

## 三、迁移路径（官方方式）

### 第 1 步：生成 6 个研发 Worker 的 SOUL.md / AGENTS.md

把 `src/loop/team.py` 的每个 `AgentRole` 转成 AgentTeams Worker：

- `soul` → `spec.soul`（SOUL.md）
- `guidelines` → `spec.agents`（AGENTS.md）
- `expected_milestone` / `handoff_to` → 写入 `agents` 里的交接协议（@mention 下一个 Worker）

用 `agt create worker --name X --soul-file ... --skills ...` 逐个创建。

### 第 2 步：挂载 Skill

把 `skills/` 的 7 个核心 Skill 用官方 `push-worker-skills.sh` 推送到各 Worker 的 MinIO 空间，
并在 `spec.skills` 声明。参照 `skills/ASSIGNMENT-MATRIX.md` 的分配。

### 第 3 步：组建 Team（PDCA 闭环团队）

用 `agt create team` 建一个研发团队：
- Leader：用 Manager 的 team-leader-agent 模板（自动获得 team-coordination / task-management skills）
- 成员：6 个研发 Worker（或精简为核心 4 角色：aggregator/fixer/tester/releaser）

### 第 4 步：跑通闭环 Demo

- 在 Element Web 给 Manager 发任务 → Manager 自动匹配 Team → Leader 拆解 → Worker 接力
- 里程碑词在 Matrix 房间流转（对齐 `state.py` 的 6 里程碑协议）

---

## 四、差距与待补

| 项 | 状态 | 待做 |
|----|------|------|
| 6 个研发 Worker | ⚠️ 未创建 | 生成 SOUL.md + `agt create worker` |
| Team | ⚠️ 未创建 | `agt create team` 组建研发团队 |
| Skill 挂载 | ⚠️ 已编排未挂载 | `push-worker-skills.sh` 推送 + spec.skills |
| PDCA 闭环在 AgentTeams 跑通 | ❌ 未验证 | 端到端跑一个缺陷→发布→复盘 |
| 可观测（Trace/Metrics） | ⚠️ 设计中 | AgentTeams 用 Matrix 房间留痕 + 状态文件 |
| RAG 记忆 | ⚠️ 设计中 | AgentTeams 用 MinIO shared/knowledge + MEMORY.md |

---

## 五、迁移进度（2026-08-13 更新）

### ✅ 已完成：6 个研发 Worker 创建成功

- `src/agentteams/workers/<name>/SOUL.md` × 6
- `src/agentteams/workers.yaml`（6 Worker CRD 声明）
- 全部 6 个 Worker 进入 **Running**（deepseek-v4-flash / copaw），容器 `agentteams-worker-*` 全部 Up
- 验证：`agt get workers` → 6 个 Running

### ⏳ 进行中：Team 结构与闭环验证

**关键决策**：AgentTeams 的独立 Worker 可直接被 Manager 派单（groupAllowFrom 含 Manager）。
我们的 PDCA 闭环是**流水线接力**（aggregator→rootcause→fixer→tester→releaser→retrospector），
**不需要强行组建 Team**——Manager 可直接驱动 6 个独立 Worker 接力。

待办：
1. 验证 Manager 能否给 Worker 派单（Element Web 发任务 → Manager → Worker）
2. 视评审需要补建 Team（用 team-leader-agent 模板）

---

## 六、结论

- **已实现的核心资产**：PDCA 状态机设计 + 6 个 Agent 定义 + Skill 体系 —— **都可迁移**。
- **AgentTeams 平台就绪**（Manager default 在跑），**6 个研发 Worker 已全部创建并 Running**。
- **下一步最关键**：验证 Manager 驱动 6 个 Worker 跑通 PDCA 闭环（Element Web 发任务）。

> 参考：AgentTeams 声明式资源管理 → `references/refs/agent-teams/docs/zh-cn/declarative-resource-management.md`
