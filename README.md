# mutil_agent — GOAI「软件研发全流程协同」多 Agent 系统架构

> 本仓库用于参赛 **GOAI 世界人工智能开源大赛 · 赛道三「软件研发全流程协同」**。
> 核心产物是 `software-dev-fullflow/` —— 一个以 **AgentTeams（比赛官方协同基点）** 构建的「软件研发多 Agent 团队」系统，
> 把 **缺陷/需求聚合 → 根因定位 → 修复 → 测试验证 → 发布确认 → 复盘沉淀** 做成**可验证、可回滚、可沉淀的 PDCA 闭环**。

本文件是**架构总览**，重点讲清「系统长什么样、各层怎么协作、代码在哪里」。进度快照与待办见 `software-dev-fullflow/PLAN.md` / `TODO.md`。

---

## 一、一句话定位与核心创新

> 用 AgentTeams 的声明式能力，造一支「软件研发 Agent 团队」，跑成一条 **PDCA 闭环**。

- **赛道**：GOAI · 赛道三「软件研发全流程协同」
- **协同基点**：AgentTeams（阿里开源，AgentScope 生态）——**比赛硬性要求**
- **LLM**：DeepSeek（OpenAI 兼容协议，`deepseek-v4-flash`）
- **本地部署**：Docker（agentteams-controller / agentteams-manager + 7 Worker 容器）+ Element Web 聊天室 + Matrix 协议

**核心创新点（差异化卖点）：「AI 公司」式动态 Agent 团队**

> 不仅是"固定 6 个 Agent 跑流水线"，而是支持**按项目需求动态组建团队**——按需"招人"（招募新职能 Agent）、"裁员"（移除不需要的角色）、新 Agent 迅速与既有团队协作出结果。AgentTeams 原生支持**无状态 Worker 声明式创建/销毁 + 技能动态加载**，天然支撑这一机制。

---

## 二、总体架构分层

系统自下而上由 **「共享协议层 → 调度 Loop 核心 → 标准化 Agent 接口层 → AgentTeams 平台深度集成」** 四层组成，
外加一组**声明式资源**（`src/agentteams/`）定义"团队长什么样"。

```
┌────────────────────────────────────────────────────────────────┐
│  Layer 4: 声明式资源层（团队怎么定义，官方 CRD）                  │
│  workers.yaml + team-rnd.yaml + team-leader.yaml + mcp/ + SOUL  │
├────────────────────────────────────────────────────────────────┤
│  Layer 3: AgentTeams 平台深度集成                                │
│  agentteams_client (agt CLI + Matrix 协议 + Human 介入)          │
│  agentteams_loop   (任务提交 + 里程碑监控 + 状态同步)              │
├────────────────────────────────────────────────────────────────┤
│  Layer 2: 标准化 Agent 接口层                                    │
│  AgentInterface (6 Worker) + AgentBus (pub/sub) + EventBus       │
├────────────────────────────────────────────────────────────────┤
│  Layer 1: 调度 Loop 核心升级                                     │
│  IterativeWorker (Ralph 迭代) + 动态预算 + 语义记忆 + 并行派单     │
├────────────────────────────────────────────────────────────────┤
│  共享协议层（确定性、框架无关）                                    │
│  state.py (PDCA 状态机) + evaluation.py (评价)                   │
│  context.py (上下文工程) + audit_logger.py (审计)                 │
└────────────────────────────────────────────────────────────────┘
```

### 关键设计原则（2026-08-15 后）

> **Python 代码是"客户端"，不是"调度引擎"。**

- **调度逻辑由 AgentTeams 平台原生提供**（LLM 驱动的 Manager 智能派单 + Matrix 房间 @mention 接力 + MinIO 持久化）。
- 本地 `AgentTeamsLoop` 只负责：提交任务给 Manager → 轮询 Matrix 里程碑 → **同步本地状态机（观测层）** → 展示 + 生成评价报告。
- 本地状态机**不干预 AgentTeams 的调度决策**，仅用于可观测、可审计、可展示。
- **协作组织已从「6 个平铺 Worker」升级为「Team + Leader 两级结构」**（见下）。

### 2.2 阿里官方组件地图（哪些组件、各干什么）

> 我们正在**大量复用阿里官方组件**，原则是「**最大化复用官方、不重造轮子**」。下表把每一个官方组件放在架构位置、说明它干什么、本项目接入状态。官方 AgentTeams 源码见 `references/refs/agent-teams/`（gitignore，不入库）。

```
  ┌─────────────── 基础网关 / 基础设施（agentteams-controller embedded 单容器承载）───────────────┐
  │  Higress 网关 · Tuwunel(Matrix) · MinIO · Element Web · Nacos(可选) · RocketMQ(可选)         │
  └───────┬───────────────────────────────┬──────────────────────────────┬────────────────────┘
          │ LLM/MCP/工具                  │ 协作消息 @mention             │ 共享存储 workspace
          ▼                               ▼                              ▼
  ┌─────────────────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
  │   Manager Agent（调度者）    │   │  Team + Leader        │   │  7 个 Worker 容器    │
  │  openclaw/qwenpaw 运行时     │──▶│  rnd-team (1+6)       │──▶│  copaw / hermes 运行时│
  └─────────────────────────────┘   └──────────────────────┘   └─────────────────────┘
```

| 官方组件 | 类型 | 它干什么 | 本项目接入状态 |
|---------|------|---------|---------------|
| **agentteams-controller** | Go 算子（K8s 原生） | 协调 Worker/Manager/Team/Human CRD 的生命周期；REST API；Worker 生命周期；网关 consumer 授权；本地模式为 embedded 单容器（内含 Higress+Tuwunel+MinIO+Element+controller）。`agt` CLI 从这里构建 | ✅ 已部署（本地 Docker，embedded） |
| **Manager Agent** | 协调智能体 | LLM 驱动：理解任务 → 匹配 Worker/Team → 在 Matrix 房间 @mention 派单 → 追踪里程碑 → 管理 skills/MCP/Human。它是平台真正的"调度引擎" | ✅ 已用（`run.py --mode delegated` 委托给它驱动闭环） |
| **Worker** | 任务执行容器 | 每 Worker 一个容器，无状态、可销毁重建；配置/产物存 MinIO；按需按 CRD 创建；加载 skills + MCP | ✅ 已用（7 个 Worker：1 Leader + 6 职能） |
| **Team + Team Leader** | 组织 CRD | `Team` CR 用 `workerMembers` 把 Leader + N Worker 组织成子团队；Leader 在 Team Room 内协调；强化多 Agent 协同叙事 | ✅ 已用（`rnd-team`，Active，leaderReady） |
| **Higress 网关** | AI 网关 / API 网关 | LLM 流量路由（OpenAI 兼容 + per-identity consumer key 认证）；MCP 服务器建模为网关路由；控制台管理路由/consumer/MCP | ✅ 已用（LLM + MCP 都走它） |
| **Tuwunel (Matrix)** | 消息中间件（聊天室） | Human↔Manager↔Worker 用 Matrix 协议通信；房间提供人在环路可见性；@mention 接力 + 留痕 | ✅ 已用（所有协作 + 里程碑都走 Matrix） |
| **MinIO** | 对象存储（S3 兼容） | Worker workspace（`agents/<name>/`）、共享任务树（`shared/tasks/`）、Manager 路径持久化；无状态 Worker 的"灵魂" | ✅ 已用（持久化 + 安全配置同步） |
| **Element Web** | Web 聊天 UI | 浏览器访问 Matrix 房间，人工介入 / 查看进度 / 派单 | ✅ 已用（http://127.0.0.1:18088） |
| **copaw / hermes 运行时** | Worker 运行时 | 容器内 Agent 循环：copaw=Python(QwenPaw)，hermes=Python 自主编程（自带终端沙箱+自我进化 Skill+持久记忆） | ✅ copaw 已用（6 Worker）；hermes 未用（可把 Fixer 换 Hermes 强化自主编程） |
| **Skill 体系** | Agent 能力包 | Manager 16 个 skill、Worker per-runtime 内置 + on-demand、Leader 7 个 skill；SKILL.md + scripts + references | ✅ 已用（`skills/` 三层体系，官方管理脚本） |
| **MCP + mcporter** | 工具接入 | 通过 Higress 网关把外部工具链（GitHub/代码扫描/测试平台）建模为 MCP Server；mcporter 在 Worker 内调 MCP 工具 | ✅ 已用（`src/agentteams/mcp/` 模板 + register-mcp.ps1） |
| **agt CLI** | 命令行工具 | 与 controller REST API 交互：创建/获取 Worker/Team/Human/Manager、apply YAML | ✅ 已用（部署 + 派单 + 验证） |
| **Nacos** | 配置/服务管理（推荐） | 动态配置、服务发现 | ⏳ 可选（官方推荐，部署用，暂未接入） |
| **RocketMQ** | 事件中间件（推荐） | Agent 间事件驱动消息协同 | ⏳ 可选（官方推荐，暂未接入） |
| **PolarDB for PG** | 云数据库（推荐） | 向量/RAG/长记忆/审计存储 | ⏳ 可选（托管服务，复赛考虑） |
| **AgentScope** | Agent 开发底座 | 阿里通义多 Agent 开发/运行框架（ReAct/tools/skills/memory/planning） | 📚 参考底座（源码在 `references/refs/agentscope/`，协同方案的开发底座） |
| **UnifiedModel** | 统一数据模型 | 统一描述实体/数据/关系/存储，用于共享状态与知识库 schema | 📚 参考（源码在 `references/refs/unified-model/`，schema 设计参考） |
| **AgentTeams Dashboard** | 可视化面板（v1.2 新增） | 可视化管理 Worker/Team/Human/Manager/Matrix，评审演示更直观 | ✅ 已用（2026-08-15 增量部署，http://127.0.0.1:13000，admin/AgentTeams2026!） |
| **CMS 2.0 观测** | 阿里云监控 | 设 `AGENTTEAMS_CMS_*` 环境变量即可把 Manager/Worker Trace 推阿里云 CMS 2.0（OTel） | 🔜 待接入（官方可观测，复用官方替代自研 OTel） |

> **接入原则**：`✅ 已用` = 已在本地 Docker 跑通并参与闭环；`⏳ 可选` = 官方推荐但属部署/基础设施，复赛按需；`📚 参考` = 官方生态底座，用文档不读全量源码；`🔜 待接入` = 官方高价值组件，后续落地（见 `design/AGENTTEAMS-INTERNALS.md` + `design/AGENTTEAMS-RUNBOOK.md`）。

---

## 三、协作组织：Team + Leader（最新落地，2026-08-15）

2026-08-15 把 6 个平铺 Worker 组织进一个 Team，形成两级协作：

```
AgentTeams Manager（LLM 驱动，平台层）
        │  派单
        ▼
   Team Leader（team-leader Worker，role=team_leader）
        │  在 Team Room 内 @mention 拆解/分派/跟进/汇总
        ▼
 ┌────────────┬────────────┬────────────┬────────────┬────────────┐
 │ Aggregator │ RootCause  │   Fixer    │   Tester   │  Releaser  │
 │ 缺陷聚合    │ 根因定位    │ 修复工程师   │ 测试验证    │ 发布确认    │
 └────────────┴────────────┴────────────┴────────────┴────────────┘
        └──────────────┬────────────────────────────┘
                       ▼
                  Retrospector（复盘沉淀，闭环闭合）
```

- **声明资源**：`src/agentteams/team-rnd.yaml`（Team CR，1 Leader + 6 Worker）+ `src/agentteams/team-leader.yaml`（Leader Worker CR，role=team_leader）。
- **状态**：`agt get teams` → `rnd-team` **Active** / leaderReady=true / readyWorkers=6/6；7 个 Worker 全挂 `TEAM=rnd-team`。
- **兼容性结论（实测）**：Worker 加入 Team 后，Manager **仍可直接驱动单级 PDCA 闭环**（最小链路验证通过）→ **方案 A（保留单级闭环作主演示路径、Team 作演示增强）** 成立，无需改 `agentteams_loop.py`。
- **方案 B（待复赛）**：整体迁移到 Manager→Leader→Worker 两级调度，需重写 `run.py` 派单/扫描逻辑。
- 回滚：`agt delete team rnd-team` + `agt delete worker team-leader`。指引见 `design/TEAM-ORGANIZATION.md`。

### 3.1 派单验证（2026-08-15 实测）

**Team 两级协作通信链路已跑通**（验证脚本 `scripts/verify-team-dispatch.py`）：
- Team Room（`!htOj83ECTGeCeNzpP7:...`）成员确认：`@admin` + 6 Worker + `@team-leader` 共 8 人。
- 向 Team Room `@team-leader` 派单 + 给 Leader DM（`leaderDMRoomID`）发消息，**Leader 的 copaw 均收到**并创建处理队列、发起 LLM 调用 → 证明「Team Admin → Team Leader」两级通信生效。

**LLM 网关已修复（2026-08-15 晚）**：此前 worker 侧 LLM 调用的 503 已解决。
- 根因：Higress McpBridge `openai-compat` 仍指向本地反代 `host.docker.internal:9001`（已 DEPRECATED 未运行）。
- 修复：McpBridge 上游改为 `api.deepseek.com:443 https` + 用官方配置重建 controller，网关 cluster `outbound|9001 → outbound|443`，chat HTTP 200。
- **修复后**：真实 6 里程碑 PDCA 闭环跑通（`TASK_SPEC_READY → … → RETROSPECT_DONE`），audit.jsonl 确认 26 个 RETROSPECT_DONE。
- 回滚备份：`scripts/controller-env-backup-reverse-*.txt`（含凭据，已 gitignore 不提交）。

---

## 四、6 个研发 Worker（映射真实研发团队）

| Worker | 职能 | 真实研发角色 | PDCA | 里程碑握手 |
|--------|------|-------------|------|-----------|
| aggregator 缺陷聚合员 | 多源缺陷/需求聚合去重、拆解任务规格 | 产品经理 + 缺陷管理 | P | `TASK_SPEC_READY` |
| rootcause 根因定位员 | 根因分析（RCA）+ 影响面分析 | 架构师 | D | `ROOT_CAUSE_FOUND` |
| fixer 修复工程师 | 生成并执行修复方案（可多实例） | 前后端开发 | D | `FIX_APPLIED` |
| tester 测试验证员 | 质量门禁，客观 PASS/FAIL 判定 | 测试工程师 | C | `TEST_PASSED` / `TEST_FAILED` |
| releaser 发布确认员 | 灰度发布、审批、回滚 | 运维 / DevOps | A | `RELEASE_OK` / `RELEASE_ROLLED_BACK` |
| retrospector 复盘沉淀员 | 复盘 + 知识沉淀（RAG 复用） | 数据分析 + 知识沉淀 | A | `RETROSPECT_DONE` |
| (协调) team-leader | 在 Team Room 协调 6 Worker | 研发负责人/技术总监 | 全 | 汇总里程碑 |

> **身份来源（多重映射）**：`agents/AGENT-IDENTITY.md`（权威身份清单）→ `src/agentteams/workers/<name>/SOUL.md`（Worker 人格）→ `workers.yaml`（CRD 落地）→ `agents/<name>/IDENTITY.md`（身份索引卡）→ `skills/ASSIGNMENT-MATRIX.md`（Skill 分配）。

### 里程碑握手协议（闭环状态流转）

```
Aggregator → TASK_SPEC_READY → RootCause
RootCause → ROOT_CAUSE_FOUND → Fixer
Fixer → FIX_APPLIED → Tester
Tester → TEST_PASSED → Releaser   （TEST_FAILED 打回 Fixer）
Releaser → RELEASE_OK → Retrospector （RELEASE_ROLLED_BACK 打回 Fixer）
Retrospector → RETROSPECT_DONE → 闭环完成，归档
```

> 交接规则：每个 Worker 完成本职产出后，用完整 Matrix ID @mention 下一个 Worker 并发送里程碑词；噪音 @mention 会死循环，禁止。

---

## 五、PDCA 闭环状态机（共享协议层 · 确定性）

**8 状态**：`SPEC_INPUT → SPEC_DECOMPOSE → ROOT_CAUSE → FIX_APPLY → TEST_VERIFY → RELEASE → RELEASE_APPROVE → RETROSPECT`

```
SPEC_INPUT → SPEC_DECOMPOSE → ROOT_CAUSE → FIX_APPLY → TEST_VERIFY → RELEASE → RELEASE_APPROVE → RETROSPECT
                                                                   │                        │
                                   TEST_FAILED / RELEASE_ROLLED_BACK └─────── 打回 FIX_APPLY（有次数上限防死循环）
```

- **实现**：`src/loop/state.py`（`State` / `Milestone` / `TaskState` / `STATE_EXECUTOR` / `STATE_EXPECTED_MILESTONE`）
- **作用**：本地观测层镜像 AgentTeams 平台进度，做可审计展示；**不干预调度决策**。
- **打回**：`TEST_FAILED` / `RELEASE_ROLLED_BACK` → 打回 `FIX_APPLY`（有次数上限防死循环）。

---

## 六、Skill 工程体系（赛道 25% 权重重点）

Skill = 目录 + `SKILL.md`（frontmatter 必含 `name` + `description` + `assign_when`）+ 可选 `scripts/` / `references/` / `assets/`。

**Manager 集中管理，Worker 通过 `Worker.spec.skills` 挂载（不能自己改 skills）。** 对齐官方 AgentTeams 方式。

**三层编排**：`REGISTRY.md`（发现层）→ `SKILL.md`（激活层，frontmatter）→ `scripts/`（执行层，可执行脚本）。

### 7 个核心工程 Skill（官方必查）

| Skill | 归谁 | 作用 |
|-------|------|------|
| `issue-parsing` | Aggregator | 结构化多源缺陷/需求输入 |
| `root-cause-analysis` | RootCause | 定位缺陷根因（RCA） |
| `impact-analysis` | RootCause | 评估改动影响面 |
| `code-gen` | Fixer（多实例） | 生成并应用修复补丁 |
| `test-generation` | Tester | 设计测试用例，验证闸门判定 |
| `release-gate` | Releaser | 发布门禁 + 灰度回滚 |
| `retrospective` | Retrospector | 复盘 + 知识沉淀 |

### L1 基座 Skill（跨 Worker 复用）

`git-operations` / `code-search` / `repo-context` / `knowledge-rag` / `evidence-log`。
另含**管理 Skill**（`manage-skill`，Manager 编排）与**个人技能**（`individual/`：align/context/deliver/diagnose/review）。

**官方管理脚本**（`skills/scripts/`）：`push-worker-skills.sh`（分配/回收/同步）/ `render-skills.sh`（环境变量渲染）/ `agentteams-find-skill.sh`（从生态发现）。

> 真相源：`skills/ASSIGNMENT-MATRIX.md`（Skill→Worker）、`skills/REGISTRY.md`（Catalog）、`skills/SKILL-LIST.md`（官方 9 字段评审）。

---

## 七、工具链（MCP + scripts）三层模型

`design/TOOLCHAIN.md` 定义了**三层工具链**：

- **L1**：copaw 运行时内置工具（shell / 文件，沙箱已验证）
- **L2**：`Worker.spec.mcpServers` MCP（Higress 网关 + mcporter + MinIO 同步）
- **L3**：Skill 可执行 `scripts/`（确定性脚本）

| Worker | spec.mcpServers | Skill scripts（可执行） |
|--------|----------------|------------------------|
| Aggregator | `github` | — |
| RootCause | `github` | — |
| Fixer | `github` + `code-scan` | `code-gen/scripts/check-patch-integrity.py` |
| Tester | `test-platform` | `test-generation/scripts/verify_test_gate.py` |
| Releaser | `ci`（可选） | — |
| Retrospector | —（内置 RAG） | — |

**接入机制**：`scripts/register-mcp.ps1`（复用官方 setup 脚本）→ Higress 网关 upsert → Consumer 授权 → `mc cp` 推 MinIO → Worker `mcporter` 拉取。模板见 `src/agentteams/mcp/`（`mcp-code-scan.yaml` / `mcp-test-platform.yaml`）。

---

## 八、沙箱安全（三层隔离，验证通过）

- **L1**：Worker 容器隔离（独立 Docker，可销毁重建）
- **L2**：copaw 运行时守卫（`tool_guard` 拦截高危命令 + `file_guard` 拦截敏感路径 + `timeout` 掐断死循环）
- **L3**：提示词边界（SOUL.md 声明允许/禁止操作）

配置：`src/agentteams/security-config.json` + `design/SECURITY-POLICY.md`。确定性验证脚本：`scripts/verify-sandbox-guards.py`（守卫 15/15）+ `scripts/verify-sandbox-timeout.py`。

---

## 九、可观测与记忆

- **可观测**（`design/OBSERVABILITY.md`）：Trace（task.id 贯穿）+ Log（Matrix 房间 + 决策日志）+ Metrics（闭环时延/修复通过率/回滚次数）
- **RAG/记忆**（`design/RAG-MEMORY.md`）：共享状态 `shared/tasks/{id}/state.json` + 知识库 `shared/knowledge/`（经验沉淀）+ Agent 两级记忆
- **审计日志**：`src/loop/audit_logger.py`（纯标准库 JSON-Lines 落盘），已接入 `agentteams_loop.py`

---

## 十、目录结构

```
mutil_agent/
├── README.md                    ← 本文件（架构总览）
├── LICENSE
└── software-dev-fullflow/       ← 项目主体（GOAI 赛道三参赛作品）
    ├── PLAN.md                  ← 项目总计划（9 项实施清单 + 进度）
    ├── TODO.md                  ← 待办清单（唯一真相源）
    ├── GOAI-QA-ESSENTIALS.md    ← GOAI 大赛 FAQ 精华 + 备赛决策
    │
    ├── agents/                  ← Agent Identity 清单（6 个研发 Agent + 索引卡）
    │   └── AGENT-IDENTITY.md
    │
    ├── design/                  ← 架构与闭环设计（19 篇文档）
    │   ├── PDCA-CLOSED-LOOP.md / MANAGER-LOOP-DESIGN.md
    │   ├── COLLABORATION-DESIGN.md / TEAM-ORGANIZATION.md
    │   ├── OBSERVABILITY.md / RAG-MEMORY.md
    │   ├── AGENTTEAMS-INTERNALS.md / AGENTTEAMS-RUNBOOK.md
    │   ├── TOOLCHAIN.md / MCP-INTEGRATION.md
    │   ├── SANDBOX-PLAN.md / SANDBOX-VERIFICATION.md
    │   ├── AGENT-EVALUATION.md / KPI-BENCHMARK.md
    │   └── ...
    │
    ├── skills/                  ← Skill 工程体系
    │   ├── ASSIGNMENT-MATRIX.md / REGISTRY.md / SKILL-LIST.md
    │   ├── scripts/             ← 官方管理脚本（push/render/find）
    │   ├── manage-skill / individual/
    │   └── <7 个核心 Skill>/     ← 每个 Skill 一个目录（SKILL.md + scripts/references）
    │
    ├── scripts/                 ← AgentTeams 部署 / 管理脚本
    │   ├── agentteams-install-patched.ps1 / reinstall-agentteams.ps1
    │   ├── apply-security-config.ps1 / register-mcp.ps1
    │   ├── verify-agentteams-min.py / verify-sandbox-guards.py
    │   ├── verify-team-dispatch.py   ← Team Room 派单验证（Leader 两级协作）
    │   ├── watch-pdca-closed-loop.py / dispatch-task.ps1
    │   └── README.md
    │
    ├── src/                     ← 可运行代码（PLAN 第 7 项落地）
    │   ├── run.py               ← 交互主入口（AgentTeams 原生）
    │   ├── AGENTTEAMS-MIGRATION.md
    │   ├── loop/                ← 调度 Loop 核心
    │   │   ├── state.py              ← PDCA 状态机（协议层）
    │   │   ├── agentteams_loop.py    ← AgentTeams 客户端调度循环（纯客户端，观测层）
    │   │   ├── agentteams_client.py  ← 平台客户端（agt CLI + Matrix + Human）
    │   │   ├── agentteams_matrix.py  ← Matrix 协议封装
    │   │   ├── agentteams_yaml.py    ← CRD YAML 解析/生成
    │   │   ├── context/              ← 上下文工程模块（estimator/budget/memory_tiers）
    │   │   ├── event_bus.py          ← 事件总线 + 订阅/广播
    │   │   ├── agent_interface.py    ← 标准化 Agent 接口
    │   │   ├── agent_bus.py          ← 消息总线 + 事件驱动
    │   │   ├── audit_logger.py       ← 结构化审计日志
    │   │   ├── evaluation.py         ← 成员评价器 + 治理命令
    │   │   ├── dashboard.py / web_dashboard.py  ← 仪表盘
    │   │   ├── reverse_gateway.py / workbuddy_client.py
    │   │   └── ...
    │   ├── agentteams/          ← 声明式资源（官方 CRD）
    │   │   ├── workers.yaml / team-rnd.yaml / team-leader.yaml  ← 7 Worker + 1 Team CR
    │   │   ├── umodel/          ← UModel 统一数据模型包（9 entity + 9 link + 2 storage）
    │   │   ├── toolchains/      ← 代码扫描 / 测试平台服务
    │   │   ├── security-config.json / SECURITY-POLICY.md
    │   │   ├── manager/SOUL.md / workers/<name>/SOUL.md
    │   │   └── mcp/             ← MCP 服务器配置（code-scan / test-platform / ci）
    │   └── shared/              ← 共享状态/知识库（运行产物，gitignore）
    │
    ├── tests/                   ← 确定性测试（115 核心单测 + e2e API/CLI/浏览器）
    ├── demo/                    ← Demo 与演示脚本 + 初赛材料（PPT / 500字简介 / LoongSuite）
    └── references/              ← 官方组件源码（整体 gitignore，只读参考，不入库）
        ├── refs/agent-teams/    ← AgentTeams 官方（controller/copaw/hermes/manager/plugins）
        ├── refs/agentscope/     ← AgentScope 开发底座
        ├── refs/unified-model/  ← UnifiedModel 统一数据模型
        └── agent-framework/     ← MAF 微软参考实现（仅作选型对比）
```

---

## 十一、如何运行

### 11.1 命令行交互入口（AgentTeams 原生，推荐）

```powershell
cd software-dev-fullflow\src

# Mock 模式（秒级演示完整闭环，不调 API）
..\demo\.venv\Scripts\python.exe run.py --mock --dashboard "定位并修复用户列表加载慢的问题"

# 委托 AgentTeams 官方 Manager 驱动（推荐，真实闭环）
..\demo\.venv\Scripts\python.exe run.py "登录接口并发下偶发 500"

# 交互式输入
..\demo\.venv\Scripts\python.exe run.py --interactive

# 终端仪表盘（Rich 实时进度 + Worker 状态 + 事件流）
..\demo\.venv\Scripts\python.exe run.py --dashboard "你的任务描述"

# Web 浏览器仪表盘（SSE 实时推送 + 人工审批）
..\demo\.venv\Scripts\python.exe run.py --web "你的任务描述"
```

### 11.2 AgentTeams 环境（本地 Docker）

- 部署/重装脚本：`software-dev-fullflow/scripts/`（`agentteams-install-patched.ps1` / `reinstall-agentteams.ps1`）
- 落地运行手册：`software-dev-fullflow/design/AGENTTEAMS-RUNBOOK.md`
- 一键入口：根目录 `启动-命令行.bat`（agt CLI + 派单）/ `启动-Web端.bat`（官方 Dashboard）/ `start.bat` 菜单
- 最小链路验证：`scripts/verify-agentteams-min.py`
- Team 派单验证（Leader 两级协作）：`scripts/verify-team-dispatch.py`
- 沙箱守卫验证：`scripts/verify-sandbox-guards.py`（15/15）+ `verify-sandbox-timeout.py`
- UModel 模型自检：`scripts/verify-umodel-model.py`（PASS）
- LoongSuite 轨迹观测：`scripts/verify-loongsuite-traces.py`（导出 Jaeger，PASS）
- 团队建站验证：`scripts/verify-team-builds-website.py`（MBTI 网站从零搭建）
- 委托降级验证：`scripts/verify-delegated-e2e.py`
- Element Web：http://127.0.0.1:18088（admin / AgentTeams2026!）；AgentTeams Dashboard：http://127.0.0.1:13000

### 11.3 环境变量

```
AGENTTEAMS_MATRIX_URL        (默认 http://127.0.0.1:18080)
AGENTTEAMS_MATRIX_DOMAIN     (默认 matrix-local.agentteams.io:18080)
AGENTTEAMS_ADMIN_USER        (默认 admin)
AGENTTEAMS_ADMIN_PASSWORD    (必填，本项目 AgentTeams2026!)
AGENTTEAMS_MANAGER_USER      (默认 manager)
```

### 11.4 实测证据

真实 AgentTeams 平台驱动 6 Worker 跑通「登录接口空用户名 500」完整 PDCA 闭环（181 秒），Matrix 房间留痕：
`TASK_SPEC_READY → ROOT_CAUSE_FOUND → FIX_APPLIED → TEST_PASSED(10/10) → RELEASE_OK → RETROSPECT_DONE`。
详见 `src/AGENTTEAMS-MIGRATION.md` §八 和 `design/EXPERIMENT-REVIEW.md`。

---

## 十二、评审权重对照

| 权重 | 赛道要求 | 本项目落地 |
|------|---------|-----------|
| 25% | 场景价值与行业可复制性 | 研发缺陷修复 PDCA 闭环，映射真实研发团队 6 角色，天然 B 端 |
| 25% | 多 Agent 协同与自主闭环 | 6 Agent + Team/Leader + Manager 调度 + PDCA 状态机 + 动态团队机制 + 真实平台闭环实测通过 |
| 25% | Skill 工程体系与生态复用 | 7 个核心 Skill + 注册表 + 分配矩阵 + 管理 Skill + 个人技能（官方 AgentTeams 方式） |
| 20% | 工程落地、运行验证与安全可审计 | 可运行代码 + 状态文件可审计 + 验证闸门 + 回滚 + 三层沙箱隔离 + AgentTeams 实跑 + Matrix 留痕 |
| 5%  | 开放/开源贡献 | 确定性调度层 + 沙箱守卫配置计划贡献回 AgentTeams 开源生态 |

---

## 十三、关键文档索引

| 主题 | 文档 |
|------|------|
| 项目总计划 | `software-dev-fullflow/PLAN.md` |
| 待办清单 | `software-dev-fullflow/TODO.md` |
| 备赛 FAQ | `software-dev-fullflow/GOAI-QA-ESSENTIALS.md` |
| AgentTeams 迁移蓝图 + 实测证据 | `software-dev-fullflow/src/AGENTTEAMS-MIGRATION.md` |
| 官方组件地图（深度版） | `software-dev-fullflow/design/AGENTTEAMS-INTERNALS.md` + `AGENTTEAMS-RUNBOOK.md` |
| Team + Leader 组织指引 | `software-dev-fullflow/design/TEAM-ORGANIZATION.md` |
| 实验复盘 | `software-dev-fullflow/design/EXPERIMENT-REVIEW.md` |
| Skill 管理手册 | `software-dev-fullflow/skills/README.md` |
| AgentTeams 运行手册 | `software-dev-fullflow/design/AGENTTEAMS-RUNBOOK.md` |
| 工具链设计 | `software-dev-fullflow/design/TOOLCHAIN.md` |
| MCP 接入方案 | `software-dev-fullflow/design/MCP-INTEGRATION.md` + `src/agentteams/mcp/README.md` |
| 沙箱验证报告 | `software-dev-fullflow/design/SANDBOX-VERIFICATION.md` |
| Team + Leader 组织 | `software-dev-fullflow/design/TEAM-ORGANIZATION.md` |
| UModel 统一数据模型 | `software-dev-fullflow/design/UNIFIED-MODEL-INTEGRATION.md` |
| LoongSuite 推理轨迹 | `software-dev-fullflow/design/LOONGSUITE-INTEGRATION.md` |

---

## 十四、重要提醒（防混淆）

- **"官方" = 比赛官方 AgentTeams（阿里开源）**，不是 Microsoft Agent Framework，也不是 IDE 的 skill 框架。
- **MAF 已归档**：`manager.py` / `fixer_loop.py` 不再参与参赛主路径，仅作选型对比参考。参赛协同基点必须是 AgentTeams。
- **`agt` CLI 没有 task/send/messages 子命令**：与 Worker 交互走 Matrix 协议（`agentteams_client.py` 已实现）。
- `references/` 整体被 gitignore（第三方源码 + 学习笔记，不入库）。
- `data/`、`shared/`、`*.log`、`controller-env-*`（含凭据）等运行产物/敏感文件均被根目录 `.gitignore` 排除，不参与提交。
- 当前主项目 = `software-dev-fullflow`（GOAI 赛道三）。
