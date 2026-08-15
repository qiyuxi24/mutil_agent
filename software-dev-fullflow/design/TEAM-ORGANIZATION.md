# Team + Leader 组织 6 Worker（落地文档）

> GOAI · 赛道三「软件研发全流程协同」· 协同基点 AgentTeams
> 目标：用官方 `Team` CRD（v1.2.0 契约）把当前 6 个平铺 Worker 组织成「1 Team Leader + 6 Worker」的研发子团队，强化「多 Agent 协同」「软件研发全流程协同」评审叙事。
> 前置：官方 AgentTeams 已本地部署（controller + manager + 6 worker 容器 Up），闭环已实测跑通（见 `AGENTTEAMS-RUNBOOK.md` / `EXPERIMENT-REVIEW.md`）。
> 日期：2026-08-15

---

## 一、结论先行（先读这个）

> ⚠️ **引入 Team 是架构变更，不是纯增量。** 它把当前「Manager → 6 Worker」的**单级调度**变成「Manager → Team Leader → 6 Worker」的**两级调度**。这会改变闭环的派单链路（见 §四）。**落地前必须先确认评审演示走哪条路径**，否则可能破坏已跑通的闭环。

**建议策略（二选一，推荐 A）：**
- **方案 A（推荐，低风险）**：**并行建一个新 Team（含 Leader + 现有 6 Worker）**，作为「多 Agent 协同」的**演示增强**，但**保留现有单级闭环**作为主演示路径。Team 建好后只用来展示团队拓扑 + 走一次 Team Room 派单验证，不动现有闭环。
- **方案 B（高风险，谨慎）**：把现有闭环**整体迁移到 Team 两级调度**（Manager 只发任务给 Leader，Leader 在 Team Room 内协调 6 Worker）。需要重写 `run.py` 派单逻辑（从 `@manager` 派单改为发到 Leader DM / Team Room），改动大、验证周期长，**不建议在初赛截止前做**。

本文档按 **方案 A** 落地，并给出方案 B 的改造指引。

---

## 二、官方 Team CRD 契约要点（v1.2.0）

来源：`references/refs/agent-teams/agentteams-controller/api/v1beta1/types.go` + `config/crd/teams.agentteams.io.yaml` + `manager/agent/skills/team-management/SKILL.md`

### 2.1 核心概念

- **Team = 1 个 Team Leader + N 个 Worker**。Leader 是一个**特殊 Worker 容器**（同 runtime），但由 Team reconciler 叠加 `team-leader-agent` 的 skills + 协调上下文。
- **Team 不拥有 Worker 的运行时/生命周期**：`Team.spec.workerMembers[]` 只是**引用**已存在的 Worker CR。改 Worker 配置/生命周期，直接改那个 Worker CR。
- **通信模型（关键变化）**：
  - **Manager 只和 Leader 通信**，不直接 @team workers。
  - **Team worker 只和 Leader + Team Admin 通信**（`groupAllowFrom=[Leader, Team Admin]`，**不含 Manager**）。
  - Team Room = Leader + Team Admin + 所有 team workers。
  - Leader Room = 标准三方（Manager + Global Admin + Leader），Leader DM = Team Admin ↔ Leader。

### 2.2 TeamSpec 字段（`types.go` L424-445）

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | string | 团队描述 |
| `teamName` | string | 运行时/存储 Team 身份，默认 = metadata.name |
| `admin` | `{name, matrixUserId}` | Team Admin（默认 Global Admin） |
| `humanMembers` | `[{name, matrixUserId, role}]` | 额外人类成员，role=coordinator 可进 Team Room 派活 |
| `workerMembers` | `[{name, role}]` | **引用已存在的 Worker CR**，role ∈ `team_leader`/`worker` |
| `peerMentions` | bool | team worker 之间能否互相 @mention（默认 true） |
| `channelPolicy` | `ChannelPolicySpec` | 团队级通信策略覆盖 |
| `heartbeatEvery` | string | Leader 心跳间隔（如 `30m`），空=禁用 |

### 2.3 workerMembers 校验规则（CRD L32-34）

> `self.filter(m, m.role == 'team_leader').size() == 1`
> **workerMembers 必须恰好包含 1 个 role=team_leader**，否则 CRD 校验失败。

---

## 三、落地步骤（方案 A，可执行）

### Step 0：确认环境

```powershell
# 在 controller 容器内确认 agt CLI 可用
docker exec agentteams-controller agt --help

# 确认现有 6 Worker 都在
docker exec agentteams-controller agt get workers
# 期望：aggregator / rootcause / fixer / tester / releaser / retrospector 全 Running
```

### Step 1：创建 Team Leader Worker CR

Team Leader 必须是一个**已存在的 Worker CR**（role 由 Team 资源声明）。新建 `team-leader` Worker，runtime 沿用 `copaw`，model 沿用 `deepseek-v4-flash`。

**Leader Worker CR**（`src/agentteams/team-leader.yaml`）：

```yaml
apiVersion: agentteams.io/v1beta1
kind: Worker
metadata:
  name: team-leader
spec:
  model: deepseek-v4-flash
  runtime: copaw
  soul: |-
    你是软件研发团队的【团队 Leader】（Team Leader），对应真实团队里的研发负责人/技术总监。
    你负责在 Team Room 内协调 6 个职能 Worker（aggregator/rootcause/fixer/tester/releaser/retrospector）完成研发全流程任务。
    你从 Manager 接收任务，分解并分派给合适的 Worker，跟进里程碑，汇总结果回报 Manager。
    你不直接写代码，只做协调、拆解、跟进与汇总。
  agents: |-
    ## 工作准则
    - 从 Manager 接收任务后，在 Team Room 内 @mention 对应 Worker 分派子任务
    - 按 PDCA 里程碑推进：TASK_SPEC_READY → ROOT_CAUSE_FOUND → FIX_APPLIED → TEST_PASSED → RELEASE_OK → RETROSPECT_DONE
    - 每个子任务完成后，汇总进度并向 Manager 回报里程碑
    - Worker 卡住或连续打回时，升级请求人类介入
    - 全程在 Team Room 留痕，保证可审计
  skills:
    - task-coordination
    - project-management
  state: Running
```

> 说明：Leader 的 `team-leader-agent` built-in skills（communication/file-sharing/project-management/task-management/team-coordination 等）会由 Team reconciler 在挂载为 Leader 时**自动叠加**（`SyncTeamLeaderAssets`，见 `deployer.go` L717），无需手动列全。`skills` 字段只加你额外想要的。

**应用：**

```powershell
docker cp src/agentteams/team-leader.yaml agentteams-controller:/tmp/team-leader.yaml
docker exec agentteams-controller agt apply -f /tmp/team-leader.yaml
# 期望输出：worker/team-leader created
```

> 注意：`apply -f` 对单个 Worker CR 用 `agt apply`。若 CLI 报 apply 需目录，可改用逐条：
> ```powershell
> docker exec agentteams-controller agt create worker --name team-leader --soul-file /tmp/team-leader-soul.txt
> ```

### Step 2：创建 Team CR（把 Leader + 6 Worker 组织起来）

`Team` 资源引用上面新建的 `team-leader`（role=team_leader）+ 现有 6 个 Worker（role=worker）。

**Team CR**（`src/agentteams/team-rnd.yaml`）：

```yaml
apiVersion: agentteams.io/v1beta1
kind: Team
metadata:
  name: rnd-team
spec:
  description: 软件研发全流程协同团队（1 Leader + 6 职能 Worker）
  teamName: rnd-team
  peerMentions: true
  heartbeatEvery: 30m
  workerMembers:
    - { name: team-leader,   role: team_leader }
    - { name: aggregator,    role: worker }
    - { name: rootcause,     role: worker }
    - { name: fixer,         role: worker }
    - { name: tester,        role: worker }
    - { name: releaser,      role: worker }
    - { name: retrospector,  role: worker }
```

**应用（方法 1：YAML apply）：**

```powershell
docker cp src/agentteams/team-rnd.yaml agentteams-controller:/tmp/team-rnd.yaml
docker exec agentteams-controller agt apply -f /tmp/team-rnd.yaml
```

**应用（方法 2：CLI create team）：**

```powershell
docker exec agentteams-controller agt create team `
  --name rnd-team `
  --leader-name team-leader `
  --workers aggregator,rootcause,fixer,tester,releaser,retrospector `
  --description "软件研发全流程协同团队" `
  --leader-heartbeat-every 30m
```

> 方法 1/2 二选一。方法 1 的 YAML 与 `workers.yaml` 风格一致、可版本管理，**推荐方法 1**。

### Step 3：验证 Team 创建成功

```powershell
# 查看 Team 状态
docker exec agentteams-controller agt get team rnd-team -o json
# 期望 status：
#   phase: Active
#   leaderReady: true
#   readyWorkers: 6
#   totalWorkers: 6
#   teamRoomID: !xxxx:matrix-local.agentteams.io:18080
#   leaderDMRoomID: !xxxx:...

# 查看成员详情
docker exec agentteams-controller agt get workers -o json | jq '.items[] | {name, status.phase}'
```

### Step 4：Team Room 派单验证（可选，演示增强）

在 Element Web（http://127.0.0.1:18088）里：
1. 进入 **Team Room**（`#rnd-team` 或 status 里的 `teamRoomID`）。
2. @mention **@team-leader** 派一个演示任务，例如：
   > `@team-leader 请让 fixer 修复登录接口空用户名返回 500 的问题，走完整 PDCA 闭环`
3. 观察 Leader 在 Team Room 内协调各 Worker、里程碑留痕。

> 这一步是**手动演示增强**，验证 Team 两级协作跑通，不影响现有单级闭环。

---

## 四、对现有闭环的影响 + 适配（方案 B 改造指引）

### 4.1 现状（已跑通）

`run.py --mode delegated`（`src/loop/agentteams_loop.py`）：
- `create_task` 把 PDCA 任务发到 **@manager 的 DM**（`agentteams_client.py` L546）。
- Manager 直接驱动 6 Worker，里程碑在各自房间出现，`detect_milestones` 跨房间扫描。

### 4.2 Team 化后的差异

| 维度 | 现状（单级） | Team 化（两级） |
|------|------------|----------------|
| 派单对象 | Manager → 直接 Worker | Manager → **Team Leader** → Worker |
| 任务发往 | @manager DM | **Leader DM / Team Room** |
| Manager 能否直连 Worker | 能 | **不能**（worker 只和 Leader+Admin 通） |
| 里程碑出现位置 | 各 Worker 房间 | Team Room + 各 Worker 房间 |
| 现有 `run.py` 兼容 | — | **不兼容**（派单/扫描逻辑要改） |

### 4.3 方案 B 改造要点（若真要迁移）

1. `agentteams_client.create_task`：任务发到 **Leader DM 房间**（`find_leader_room`），正文 @team-leader，而不是 @manager。
2. `detect_milestones`：除各 Worker 房间外，**必须扫描 Team Room**（Leader 的里程碑转述在那里）。
3. `wait_for_task`：等待 Leader 回报的 `RETROSPECT_DONE`（Leader 汇总，而非直接等 retrospector）。
4. `agentteams_loop._run_delegated`：manager 参数/派单目标改为 team-leader。

> ⚠️ 这套改动会重构已验证的闭环链路，**建议复赛再动**。初赛用方案 A 即可覆盖「多 Agent 协同」评审点。

---

## 五、回滚

```powershell
# 删除 Team（只删团队关系，不删 Worker）
docker exec agentteams-controller agt delete team rnd-team

# 删除 Leader Worker（若不再需要）
docker exec agentteams-controller agt delete worker team-leader
```

> 删除 Team 后，6 个 Worker 恢复 standalone 成员关系（v1.2 已修复该生命周期收敛），原有单级闭环不受影响。

---

## 六、交付清单

| 文件 | 说明 |
|------|------|
| `src/agentteams/team-leader.yaml` | Team Leader Worker CR（需创建） |
| `src/agentteams/team-rnd.yaml` | Team CR：1 Leader + 6 Worker（需创建） |
| 本文档 | 落地指引 + 影响分析 |

---

## 七、相关文档索引

- 官方 Team 契约：`references/refs/agent-teams/agentteams-controller/api/v1beta1/types.go`（L416-557）
- 官方 Team CRD：`references/refs/agent-teams/agentteams-controller/config/crd/teams.agentteams.io.yaml`
- 官方 team-management skill：`references/refs/agent-teams/manager/agent/skills/team-management/SKILL.md` + `references/create-team.md`
- 官方 Team Leader 内置资产：`references/refs/agent-teams/manager/agent/team-leader-agent/`
- 项目闭环现状：`design/AGENTTEAMS-RUNBOOK.md` / `design/EXPERIMENT-REVIEW.md` / `src/loop/agentteams_loop.py`
