# AgentTeams 内部机制详解：设计、API 与流程（可改造性评估）

> 基于本地源码实证分析（`references/refs/agent-teams/`，v1.2.0）。
> 目的：评估"我们在多大程度上能改这一套东西"，为作品方案与复赛 AgentTeams 代码包提供依据。
> 日期：2026-08-06

---

## 0.5 最关键的认知：Agent 的"具体行为和准则"由谁管？

> 你问："Agent 自己的具体行为和准则该怎么办呢？这个框架不管吗？"

**答案：框架"不管"——它不内置任何业务行为，但它提供了完整的"注入机制"让你来管。**

AgentTeams 是**编排层**（管"谁跟谁说话、谁跑在哪个容器"），**不是行为层**。Agent 的"性格、工作准则、流程、边界、安全规则"全靠一套**运行时 Markdown 文件系统**注入给 Agent。这套机制叫 `manager/agent/`（镜像内 `/opt/agentteams/agent/`），是**全项目最常改、最核心的可扩展点**。

**一句话模型：**
```
Agent 的具体行为 = SOUL.md(人格) + AGENTS.md(工作准则) + HEARTBEAT.md(周期性职责) + skills/(技能/工具) + memory/(记忆)
这 5 类 Markdown 文件被注入进 Agent 的工作区，Agent 每会话开头"读文件"，行为就由这些文件决定。
```

**类比**：AgentTeams 像是"公司行政系统"（发门禁卡、分办公室、建会议室、管报销凭证），而 `SOUL.md/AGENTS.md/SKILL.md` 像是"员工手册 + 岗位说明书 + 工作SOP"。行政系统不替你决定怎么写代码，但它保证"员工手册会被每个员工读到、权限门禁能拦住越权行为"。

---

## 0. 一句话理解

**AgentTeams 本身不写 Agent**，而是给"多个 Agent 如何像一家公司那样协作"造了一套**声明式编排底座**——你只需要用 YAML 声明"谁是什么角色、谁能跟谁说话、共享哪些文件"，剩下的（建房间、发凭证、拉容器、配网关）它自动帮你搞定。

它的设计哲学完全照搬 Kubernetes：**CRD 声明式资源 + Controller Reconcile Loop + 底层 Backend 抽象**。

---

## 1. 总体架构（4 个核心层）

```
┌────────────────────────────────────────────────────────────┐
│                    人类入口层 (Human 接入)                     │
│   Element Web / FluffyChat (Matrix 客户端) + Human CRD(3级权限) │
└──────────────────────────┬─────────────────────────────────┘
                           │ Matrix 房间 (透明可审计，人可随时介入)
┌──────────────────────────▼─────────────────────────────────┐
│                    协作编排层 (agentteams-controller)          │
│   Manager(协调) → Team Leader(委派) → Workers(执行)           │
│   Reconcile Loop 持续把"实际状态"收敛到 YAML"期望状态"          │
└──────────┬──────────────┬──────────────┬────────────────────┘
           │              │              │
   ┌───────▼────┐  ┌──────▼─────┐  ┌─────▼────────┐
   │ 通信层      │  │ 安全层      │  │ 存储层        │
   │ Tuwunel    │  │ Higress    │  │ MinIO        │
   │ (Matrix)   │  │ AI Gateway │  │ 对象存储       │
   └────────────┘  └────────────┘  └──────────────┘
```

**各层职责**：
| 层 | 组件 | 技术 | 职责 |
|----|------|------|------|
| 协作编排层 | `agentteams-controller` | Go + controller-runtime | 编排 Worker/Team/Manager/Human 四种 CR；生命周期管理 |
| 通信层 | Tuwunel | Matrix 协议（conduwuit fork） | 承载所有 Agent+人类通信，可审计、可介入 |
| 安全层 | Higress | CNCF Sandbox，Envoy 内核 | LLM 代理 + MCP 托管 + Consumer 凭证鉴权 |
| 存储层 | MinIO | S3 兼容对象存储 | 集中文件系统，Worker 无状态 |
| Agent 运行时 | OpenClaw/QwenPaw/Hermes | Node/Python | 真正"干活"的 Agent 本体 |

---

## 2. 核心 API：4 种声明式资源（CRD）

所有资源都是 `apiVersion: agentteams.io/v1beta1`，用 YAML 声明。这是整个系统**最核心的扩展点**。

### 2.1 Worker —— 基本执行单元（干活的 Agent）
```yaml
apiVersion: agentteams.io/v1beta1
kind: Worker
metadata:
  name: alice                     # 身份名
spec:
  model: qwen3.5-plus             # 必填：LLM 模型
  modelProvider: apig             # 可选：按 Worker 独立指定 LLM 提供商
  runtime: openclaw               # openclaw | copaw | hermes | qwenpaw
  image: <自定义镜像>               # 可选：完全自定义 Worker 镜像
  workerName: alice-rt            # 运行身份（Matrix localpart / OSS 路径键）
  identity: ""                    # 业务身份
  soul: |                         # ★ Agent 人格定义（最重要的可改点）
    你是一个专注于缺陷根因定位的工程师...
  agents: |                       # ★ 工作说明（AGENTS.md 覆盖）
  skills: [github-operations]     # ★ 内置技能
  remoteSkills:                   # 远程技能（nacos 注册中心）
    - source: nacos://host:port/ns
      skills: [{name: xxx}]
  mcpServers:                     # ★ MCP 服务器（通过 mcporter 调用）
    - name: github
      url: https://gw.example.com/mcp-servers/github/mcp
      transport: http             # http | sse
  package: file://./alice-pkg.zip # 自定义包（file/http/nacos）
  expose:                         # 通过网关暴露的端口
    - port: 3000
      protocol: http
  state: Running                  # Running | Sleeping | Stopped
  channelPolicy:                  # ★ 通信权限增减
    groupAllowExtra: ["@human:dom"]
  resources:                      # 资源限制
    requests: {cpu: "500m", memory: 512Mi}
  env: {}                         # 自定义环境变量（系统键优先）
  deployMode: Local               # Local | Edge | Remote
```

**每个 Worker 自动对应**：一个容器/Pod + 一个 Matrix 账号 + 一块 MinIO 空间 + 一个 Gateway Consumer Token。

### 2.2 Team —— 协作单元（一组 Worker + 一个 Leader）
```yaml
apiVersion: agentteams.io/v1beta1
kind: Team
metadata:
  name: frontend-team
spec:
  description: "前端开发团队"
  heartbeatEvery: 10m             # Leader 心跳周期
  workerMembers:                  # ★ 成员 = 已存在的 Worker CR
    - name: frontend-lead
      role: team_leader           # 特殊 Worker，负责团队内任务调度
    - name: alice
      role: worker
    - name: bob
      role: worker
  # admin:  # 可选：团队管理员
  # channelPolicy: # 团队级通信覆盖
```

创建 Team 时 Controller 自动编排房间拓扑：
```
Leader Room:  Manager + Global Admin + Leader   ← Manager 仅对接 Leader
Team Room:    Leader + Admin + W1 + W2 + …      ← Manager 不在此（委派边界）
Worker Room:  Leader + Admin + Worker           ← Leader 与单个成员的私聊
Leader DM:    Admin ↔ Leader                    ← 团队管理与对齐
```

**关键设计**：Manager 不穿透 Team——它只跟 Leader 说话，Leader 负责团队内部分工。这防止 Manager 成为瓶颈，对应你方案的"委派边界"。

### 2.3 Human —— 真人用户（3 级权限）
```yaml
apiVersion: agentteams.io/v1beta1
kind: Human
metadata:
  name: zhangsan
spec:
  displayName: "张三"
  email: zhang@example.com
  permissionLevel: 2              # 1=Admin, 2=Team, 3=Worker
  accessibleTeams: [frontend-team]
  accessibleWorkers: [alice]
```

### 2.4 Manager —— 协调 Agent（可选 CR）
```yaml
apiVersion: agentteams.io/v1beta1
kind: Manager
metadata:
  name: default
spec:
  model: qwen3.5-plus
  runtime: openclaw               # openclaw | copaw
  soul: | ...                     # 覆盖人格
  agents: | ...                   # 覆盖工作说明
  skills: [worker-management]     # Manager 技能
  mcpServers: [{name: github, url: ...}]
  config:
    heartbeatInterval: 15m
    workerIdleTimeout: 720m
    notifyChannel: admin-dm
  state: Running
```

**kubectl 短名**：`wk`(Worker) / `tm`(Team) / `hm`(Human) / `mgr`(Manager)

---

## 3. 核心流程：Controller Reconcile Loop

```
YAML 资源声明
    ↓ agt apply (或 kubectl apply)
kine(etcd兼容,SQLite) / K8s etcd        ← 状态存储
    ↓ Informer Watch
Controller Runtime
    ↓ Reconcile Loop（持续收敛实际状态→期望状态）
┌─────────────────────────────────────────────┐
│  Provisioner（基础设施配置）                   │
│  - Matrix 账号注册 & Room 创建               │
│  - MinIO 用户 & Bucket 配置                  │
│  - Higress Gateway Consumer & Route 配置     │
├─────────────────────────────────────────────┤
│  Deployer（配置部署）                         │
│  - Package 解析（file/http/nacos）            │
│  - openclaw.json 生成（含通信权限矩阵）        │
│  - SOUL.md / AGENTS.md / Skills 推送         │
│  - 容器启动 / Pod 创建                        │
├─────────────────────────────────────────────┤
│  Worker Backend 抽象层（可插拔）              │
│  - Docker Backend（embedded 模式）           │
│  - K8s Backend（incluster 模式）             │
│  - Cloud Backend（云上托管模式）               │
└─────────────────────────────────────────────┘
```

**两个部署模式，同一套 Reconciler**：
| 模式 | 状态存储 | Worker 运行 | 适用场景 |
|------|---------|------------|---------|
| Embedded | kine + SQLite | Docker 容器 | 本地开发、小团队 |
| Incluster | K8s etcd | K8s Pod | 企业级、云上 |

---

## 4. 协作流程：Manager → Leader → Workers 三级委派

```
Admin: "完成用户登录功能的前后端开发"
  ↓
Manager: 识别涉及前端团队，@mention Team Leader
  ↓
Team Leader: 分解任务为子任务
  ├── 子任务1 "实现登录 API"   → @mention Worker A（后端）
  ├── 子任务2 "实现登录页面"   → @mention Worker B（前端）
  └── 子任务3 "编写集成测试"   → 等待1、2完成后分配
  ↓
Worker A: 完成后端 API，在 Team Room 汇报 → @mention Leader
Worker B: 完成前端页面，在 Team Room 汇报 → @mention Leader
  ↓
Team Leader: 确认完成，分配子任务3 → @mention Worker A
  ↓
Worker A: 完成集成测试，汇报
  ↓
Team Leader: 汇总结果，@mention Manager
  ↓
Manager: 通知 Admin 任务完成
```

**全程所有对话在 Matrix Room 中可见，Admin 可随时介入任何环节。**

---

## 5. 安全模型：凭证永不下发到 Agent

```
Worker（仅持有 Consumer Token: GatewayKey）
    → Higress AI Gateway
        ├── key-auth WASM 插件验证 Consumer Token
        ├── 检查 Consumer 是否在 Route 的 allowedConsumers 列表
        ├── 注入真实凭证（API Key / GitHub PAT / OAuth Token）
        └── 代理请求到上游服务
            ├── LLM API（OpenAI / Anthropic / Qwen 等）
            ├── MCP Server（GitHub / Jira / 自定义 等）
            └── 其他外部服务
```

**核心安全原则**：真实凭证只存在于 Gateway，Agent 只持有一个可随时吊销的 Consumer Token。即使 Worker 被攻破，攻击者拿不到任何真实凭证。

**细粒度权限**（对应 K8s ServiceAccount + RBAC 模型）：
| 控制维度 | 实现 | 效果 |
|---------|------|------|
| Worker 级 LLM 访问 | AI Route 的 allowedConsumers | Worker A 可用强模型，B 只能用弱模型 |
| Worker 级 MCP 访问 | MCP Server 的 allowedConsumers | Worker A 可访问 GitHub，B 不可以 |
| 动态权限变更 | 修改 allowedConsumers | 秒级生效（WASM 热同步） |
| 即时吊销 | 从 allowedConsumers 移除 | 无需轮换凭证 |

---

## 6. 共享状态：MinIO 文件系统

```
MinIO (HTTP 对象存储)
├── agents/                    # 每个 Worker 的配置空间（无状态，可重建）
│   ├── alice/
│   │   ├── SOUL.md           # 人格
│   │   ├── openclaw.json     # 运行时配置
│   │   └── skills/
│   └── bob/
├── shared/                    # ★ 共享空间（多 Agent 协作的关键）
│   ├── tasks/                # 任务规格/元数据/结果
│   │   └── task-{id}/
│   │       ├── meta.json
│   │       ├── spec.md
│   │       └── result.md
│   └── knowledge/            # 共享知识库
└── workers/                   # Worker 工作产物
```

Worker 无状态——配置全从 MinIO 拉取，可随意销毁重建不丢状态（对应 K8s 无状态 Pod + PV 持久化）。

---

## 7. 可改造性评估：我们在多大程度上能改？

> 这是本项目的核心问题。按**改造深度从浅到深**排序，越靠上越简单、越适合复赛交付。

### 7.1 零代码改造（只写 YAML + Markdown，即可交付）— ★ 复赛首选
| 改造点 | 怎么做 | 对应赛道要求 |
|--------|--------|-------------|
| **Agent 人格/职能** | `spec.soul`（SOUL.md）定义每个 Worker 的角色、职责、边界 | Agent Identity 清单 |
| **Agent 工作流程** | `spec.agents`（AGENTS.md）定义工作步骤、触发条件、输出规范 | 多 Agent 协同 8 环节 |
| **Skill 清单** | `spec.skills` + 仓库 `manager/agent/skills/<name>/SKILL.md` | Skill 工程（25%） |
| **工具集成** | `spec.mcpServers` 声明 MCP 服务器 | MCP 集成 |
| **团队结构** | `Team` CRD 定义 Leader + 多个职能 Worker | 多 Agent 协同 |
| **共享状态** | 使用 `shared/tasks/` + `shared/knowledge/` 约定任务流转格式 | 共享状态管理 |
| **人类审批** | Human 全程可见 Matrix 房间，可随时介入 | 审批与回滚 |

**结论**：仅仅靠**写 `soul`/`agents`/`skills` + 设计 Team 结构**，就能构造出一个"软件研发全流程协同"的多 Agent 团队，**完全不需要改任何代码**。这就是复赛"可执行代码包"最务实的交付路径。

### 7.2 轻改造（新增 Skill / Worker 包 / 自定义镜像）
| 改造点 | 怎么做 | 难度 |
|--------|--------|------|
| 新增平台级 Skill | 在 `manager/agent/skills/<name>/SKILL.md` + scripts/ 写技能 | 低 |
| Worker 打包发布 | `spec.package: file://./pkg.zip` 打包技能+配置 | 低 |
| 自定义 Worker 镜像 | `spec.image` 指向自建镜像（基于 openclaw-base 扩展） | 中 |

### 7.3 中改造（扩展 Controller 或运行时逻辑）
| 改造点 | 怎么做 | 难度 | 说明 |
|--------|--------|------|------|
| 新增 CRD 字段 | 改 `types.go` + 重新生成 deepcopy/CRD | 中高 | 需要懂 Go + controller-runtime |
| 新增 Controller 逻辑 | 写新的 reconciler（如"缺陷聚合"专用控制器） | 高 | 需 K8s operator 经验 |
| 改 Agent 运行时 | 改 `openclaw-base` / `copaw` / `hermes` | 中 | Node/Python |

### 7.4 深改造（替换/新增基础设施）
| 改造点 | 怎么做 | 难度 |
|--------|--------|------|
| 新增 Backend | 实现新的 `Worker Backend` 抽象 | 高 |
| 对接 NemoClaw | 作为安全沙箱后端 | 高（规划中） |
| 替换 Matrix/Gateway/存储 | 换 Tuwunel/Higress/MinIO | 中高（依赖耦合） |

---

## 8. 对我们的方案：推荐改造策略

基于 7.1 的结论，我们的作品**不需要深改框架**，重点在：

1. **定义研发流程的 Agent 角色**（缺陷聚合员、根因定位员、修复工程师、测试验证员、复盘员）
   → 每个用 `Worker.spec.soul` + `spec.agents` 定义，形成 **Agent Identity 清单**

2. **设计 PDCA 闭环的 Team 结构**
   - Team = 一个"研发交付小组"，Leader 负责任务分解（对应 P/D 阶段）
   - 成员 Worker 对应 缺陷/编码/测试/发布 等职能

3. **用 Skill 封装工程能力**（对应 Skill 工程 25%）
   - `code-review`、`test-generation`、`dependency-analysis`、`release-gate` 等

4. **利用共享状态做闭环沉淀**
   - `shared/tasks/{id}/spec.md → result.md` 承载任务流转（对应 8 环节）
   - `shared/knowledge/` 承载复盘经验（对应 RAG/知识沉淀）

5. **用 Matrix 房间的可见性 + Human 介入做审批与回滚**（对应审批回滚环节）

---

## 9. 相关源码索引（复赛要改哪里看这里）

| 路径 | 作用 |
|------|------|
| `agentteams-controller/api/v1beta1/types.go` | **CRD 类型定义**（改字段的唯一入口） |
| `agentteams-controller/internal/controller/*.go` | 各资源的 Reconcile 循环 |
| `manager/agent/` | **Agent 可读的提示词/技能真相源**（最常改） |
| `manager/agent/skills/<name>/SKILL.md` | Skill 定义 |
| `manager/agent/{worker,copaw-worker,hermes-worker}-agent/` | 各 Worker 运行时模板 |
| `manager/scripts/init/start-manager-agent.sh` | 环境变量清单 |
| `helm/agentteams/values.yaml` | 部署可配置项 |
| `shared/lib/render-skills.sh` | 技能模板渲染 |

---

## 10. 关键结论（供 PPT 引用）

> **AgentTeams 最大的可扩展性在于"不改代码就能造一支 Agent 研发团队"** —— 通过 `soul`（人格）+ `agents`（流程）+ `skills`（能力）+ `Team`（结构）+ `shared/`（共享状态）五个声明式维度，即可完整映射赛道的"软件研发全流程多 Agent 闭环"。
> 框架本身是 Apache-2.0 开源，可自由扩展；其 K8s 式声明式设计，使我们能以极低成本实现差异化 Agent 团队，同时满足官方"以 AgentTeams 为协同基点"的硬性要求。

---

## 附录 A：Agent 行为准则机制详解（我们怎么定义 Agent 的行为）

> 核心源码真相源：`manager/agent/`（镜像内 `/opt/agentteams/agent/`）
> 写入约定：**所有此目录文件都是"Agent 运行时读取"的，必须用第二人称"you"写给 Agent 读**，不是给人看的文档。

## A.1 五类"行为准则"文件（Agent 的行为来源）

每个 Agent（Manager / Worker / Team Leader）启动后，工作区里有以下几类文件，**每会话开头先读它们**来决定自己的行为：

| 文件 | 作用 | 谁来写 | 示例内容 |
|------|------|--------|---------|
| **`SOUL.md`** | **人格 + 身份 + 安全边界** | 你通过 `Worker.spec.soul` 传入 | "你是缺陷根因定位工程师，你有 XX 权限，绝不做 XX" |
| **`AGENTS.md`** | **工作准则 + 每会话必做清单 + 各种 Gotcha** | 你通过 `Worker.spec.agents` 传入 | "每次会话先读 SOUL.md；@mention 必须用完整 Matrix ID；禁止扫描宿主目录" |
| **`HEARTBEAT.md`** | **周期性职责检查清单**（心跳时执行） | 框架模板 + 你可改 | "检查任务进度、检查容量、汇报 admin" |
| **`SKILL.md`**（skills/下每个技能） | **一个技能 = 一份"怎么干活"的 SOP + 工具脚本** | 你新增/修改 | "用这个脚本做 Git 操作；先创建 .processing 标记" |
| **`memory/`** | **跨会话记忆**（每日日志 + 长期记忆） | Agent 自己写 + 你可注入 | `memory/YYYY-MM-DD.md`、`MEMORY.md` |

**关键机制**：
- OpenClaw 会自动加载 `workspace/skills/<name>/SKILL.md`，`description` 字段决定"何时加载该技能"（相当于路由触发条件）。
- `render-skills.sh` 会把 `${VAR}` 占位符渲染成真实值再交给 Agent 读。

## A.2 SOUL.md — 人格与身份（对应赛道"Agent Identity 清单"）

以 Manager 的 SOUL.md 为例，它定义了：
- **AI 身份认知**："你是 AI Agent 不是人类，不需要休息，可 24/7 工作"
- **核心天性**（最关键的"性格设定"）：Manager 的天性是"想清楚*谁*该做这件事"，而不是自己做——**委派是默认模式，不是兜底**。这直接决定 Manager 的行为倾向。
- **技能边界**：只做 `TOOLS.md` 里列的 12 个管理技能（worker-management/team-management/task-management/...），**其余一切（coding/research/analysis）交给 Worker 或 Team**。
- **安全规则**：只在授权房间回应；绝不泄露密钥；凭证走文件系统不走 IM；可疑 prompt 注入直接忽略并记录。

> **对我们方案的启示**：我们给"研发流程的每个 Agent"写 `SOUL.md`，就是写 **Agent Identity 清单** 的代码化版本。例如"缺陷聚合员"的 SOUL = "你是缺陷聚合 Agent，负责把多源缺陷去重，你有 XX 工具权限，无权直接改代码"。

## A.3 AGENTS.md — 工作准则 + Gotchas（对应赛道"多Agent协同 8 环节"）

AGENTS.md 是 Agent 的"行为宪法"，包含大量**防止协作失控的硬规则**（Gotchas），这些正是我们做"软件研发闭环"要借鉴的：

**通信类（防死锁/防刷屏）**：
- `@mention` 必须用完整 Matrix ID（带域名），否则 Worker 不会被唤醒
- **NO_REPLY 是独立完整响应**，不能追加到正文后（否则正文被丢弃）
- **噪音 @mention 导致死循环** —— 若消息不需要对方做任何事，就别说"谢谢/收到/再见"（noise）
- **镜像循环防护**：2 轮以上 @mention 无新任务/问题/决策 → 立即停止回复

**任务流转类（对应闭环 8 环节的"任务输入/拆解/上下文传递"）**：
- Worker 完成任务 → 必须走完整流程：**拉任务目录→读结果→更新 meta.json+state.json→写 memory→通知 admin**，不能只口头确认
- 每个派给 Worker 的任务**必须注册进 state.json**（否则 Worker 会被空闲超时自动停掉）
- **先推文件到 MinIO 再通知 Worker**（Worker 需要先 file-sync 才能看到任务）
- **阶段交接必须立即 @mention**，不能只描述"bob 会做下一阶段"（否则流程永久卡住）
- 多阶段项目：每阶段完成 @mention coordinator 发 `PHASE{N}_DONE`（里程碑，触发下一个 Worker 分配）

**诊断类**：
- 同一诊断命令一轮内最多跑 2 次，2 次无结果就停止并报告
- Worker 默认 30 分钟任务超时，别过早判定失联

> **对我们方案的启示**：赛道的"闭环 8 环节"其实 AgentTeams 的 AGENTS.md 已经隐含实现了大部分。我们要做的是**把"软件研发专属的环节"（代码根因定位、测试验证、灰度发布、复盘沉淀）写进每个 Agent 的 AGENTS.md**，并定义它们之间的"里程碑握手协议"（如 `ROOT_CAUSE_FOUND` → `FIX_APPLIED` → `TEST_PASSED` → `RELEASE_OK` → `RETROSPECT_DONE`）。

## A.4 HEARTBEAT.md — 周期性职责（对应"复盘/监控/发布确认"）

心跳是 Agent 的"主动巡检"，不是被动响应。Manager 的 HEARTBEAT.md 定义每轮心跳做：
1. 读 `state.json` 追踪所有进行中任务
2. 检查 finite 任务进度（先确保 Worker 容器活着，再 @mention 催进度）
3. 检查 Team 委派任务（只找 Leader，不直接联系团队 Worker）
4. 检查 infinite 定时任务是否到点（到点才触发，记录与触发分离防死循环）
5. 监控项目进度（扫 `shared/projects/*/meta.json`）
6. 容量评估（数有限任务 + 找空闲 Worker）
7. Worker 容器生命周期管理（空闲超时自动暂停）
8. 向 admin 汇报（HEARTBEAT_OK 表示一切正常）

> **对我们方案的启示**：用 HEARTBEAT.md 实现"发布确认 / 上线复盘 / 知识沉淀"这类**周期性职责**，让 Agent 主动巡检任务状态、触发下一步，而不是等人喂。

## A.5 Skill — 一个技能 = 一份 SOP + 一组工具（对应赛道"Skill 工程 25%"）

Skill 是**行为准则的最小可复用单元**。每个 skill 目录含：
```
skills/<name>/
├── SKILL.md      # frontmatter(name+description) + 使用说明/SOP/Gotchas
├── scripts/      # 可执行脚本（真正的工具）
└── references/   # 可选：分场景的深度文档
```

**SKILL.md 的 frontmatter 是路由触发条件**：
```markdown
---
name: task-management
description: Use when admin gives a task to delegate to a Worker, when a Worker reports task completion...
---
```
Agent 读到"当前该做什么"时，根据 `description` 决定是否加载这个技能。

**Manager 的内置管理技能（15个）**：
`worker-management` / `team-management` / `task-management` / `task-coordination` / `project-management` / `human-management` / `channel-management` / `matrix-server-management` / `mcp-server-management` / `model-switch` / `worker-model-switch` / `file-sync-management` / `git-delegation-management` / `agentteams-find-worker` / `service-publishing`

**Worker 的内置技能（5个）**：
`file-sync`(同步文件) / `task-progress`(任务进度日志) / `project-participation`(项目参与) / `mcporter`(调MCP) / `find-skills`(搜索技能)

> **对我们方案的启示**：我们把"软件研发能力点"封装成 Skill，例如：`code-review`、`test-generation`、`root-cause-analysis`、`dependency-analysis`、`release-gate`、`retrospective`。每个 Skill 就是一个可复用、可评估的工程能力单元，正好命中 **Skill 工程 25% 权重**。

---

## 附录 B：AgentTeams 框架资源（Resource）全景清单

> "资源" = 框架为你提供的、可以创建/查询/修改/删除的"实体"。
> 分两层：**声明式 CRD 资源**（你写 YAML 定义）+ **运行时工作区资源**（Agent 自己持有的文件/状态）。

## B.1 声明式 CRD 资源（YAML 层，4 大类 + 子资源）

| 资源类型 | 是什么 | 关键字段 | 对应概念 |
|---------|--------|---------|---------|
| **Worker** | 一个干活的 Agent 容器 | model/runtime/soul/agents/skills/mcpServers/state | K8s 的 Pod |
| **Team** | 一组 Worker + 一个 Leader | workerMembers/description/heartbeatEvery | K8s 的 Deployment |
| **Human** | 真人用户，3 级权限 | displayName/permissionLevel/accessibleTeams | K8s 的用户+RBAC |
| **Manager** | 协调 Agent（可选） | model/soul/agents/skills/config | K8s 的 control-plane |

**Worker 的完整子字段（决定"这个 Agent 是谁、能干嘛"）**：
| 字段 | 说明 | 赛道对应 |
|------|------|---------|
| `model` | LLM 模型（必填） | 可给不同职能 Agent 配不同模型 |
| `modelProvider` | 独立 LLM 提供商 | — |
| `runtime` | openclaw/copaw/hermes/qwenpaw | 选运行时 |
| `image` | 自定义镜像 | 深度定制 |
| `soul` / `agents` | 人格 / 工作准则 | **Agent Identity** |
| `skills` / `remoteSkills` | 技能（本地/远程注册中心） | **Skill 工程** |
| `mcpServers` | MCP 服务器 | **MCP 集成** |
| `package` | 自定义包（file/http/nacos） | 打包复用 |
| `state` | Running/Sleeping/Stopped | 生命周期 |
| `channelPolicy` | 通信权限增减 | 协同边界 |
| `resources` | CPU/内存 | — |
| `expose` | 暴露端口 | 发布 |
| `deployMode` | Local/Edge/Remote | 部署位置 |

## B.2 运行时工作区资源（Agent 持有的文件，`~/` 和 `shared/`）

**每个 Agent 的私有工作区 `~/`**（本地，不同步 MinIO）：
```
~/SOUL.md          人格
~/AGENTS.md        工作准则
~/HEARTBEAT.md     周期性职责
~/openclaw.json    运行时配置（通信权限矩阵等）
~/memory/          记忆（YYYY-MM-DD.md 日志 + MEMORY.md 长期）
~/skills/          技能（内置只读 + 自定义可写）
~/state.json       任务状态机（Manager 特有）
~/yolo-mode        YOLO 模式标记（admin 全权授权标记）
```

**共享工作区 `shared/`**（同步 MinIO，多 Agent 协作核心）：
```
shared/tasks/{task-id}/         任务流转
  ├── spec.md      任务规格（coordinator 写，Worker 只读）
  ├── base/        参考文件（只读）
  ├── plan.md      执行计划（Worker 写）
  ├── result.md    最终结果（finite 任务）
  └── progress/    进度日志
shared/projects/{title}/        项目流转
  ├── meta.json    项目元数据（status/room_id）
  └── plan.md      项目计划（含 [~] 进行中标记）
shared/knowledge/               共享知识库（RAG/沉淀）
agents/{name}/                  每个 Agent 的 MinIO 命名空间
```

## B.3 基础设施资源（部署层组件）

| 组件 | 作用 | 是否可替换 |
|------|------|-----------|
| `agentteams-controller` | K8s operator（Reconcile 循环） | 核心，可扩展 |
| `Tuwunel` (Matrix) | Agent+人类通信服务器 | 可替换（Matrix 协议标准） |
| `Higress` | AI Gateway（LLM代理+MCP托管+凭证） | 可替换 |
| `MinIO` | 对象存储（共享状态） | 可替换（OSS） |
| `Element Web` | Matrix 浏览器客户端 | 可替换 |
| OpenClaw/QwenPaw/Hermes | Agent 运行时 | 可选新增 |

## B.4 我们方案的"资源映射"（如何用这些资源造研发团队）

| 赛道需求 | 用什么资源实现 |
|---------|--------------|
| 缺陷聚合 Agent | `Worker` + `soul`(聚合职责) + `skills`(issue/log解析) + `mcpServers`(Jira/GitHub) |
| 根因定位 Agent | `Worker` + `soul`(代码分析) + `skills`(root-cause) + MCP(代码仓库) |
| 修复执行 Agent | `Worker` + `soul`(编码) + `skills`(code-review) + MCP(提PR) |
| 测试验证 Agent | `Worker` + `soul`(测试) + `skills`(test-generation) + `expose`(测试服务) |
| 发布确认 Agent | `Worker` + `soul`(发布) + `skills`(release-gate) + 灰度状态 |
| 复盘沉淀 Agent | `Worker` + `soul`(复盘) + `skills`(retrospective) + `shared/knowledge/`(RAG沉淀) |
| 团队编排 | `Team` + Leader 负责任务拆解（对应 P/D 阶段） |
| 审批与回滚 | `Human` 在 Matrix 房间可见介入 + `channelPolicy` 边界 |
| 闭环状态流转 | `shared/tasks/{id}/` 的 spec→plan→result + 各 Agent 的 @mention 里程碑 |
| 可观测 | Matrix 房间全记录 + MinIO 审计 + 心跳日志 |
