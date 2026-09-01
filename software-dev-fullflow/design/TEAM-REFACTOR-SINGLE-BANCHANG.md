# 团队架构重构：从「两套班子 + 双模式」到「一套完整班子 + 固定 Leader 编排」

> GOAI · 赛道三「软件研发全流程协同」· 协同基点 AgentTeams
> 状态：**计划（待新窗口执行）** · 日期：2026-08-16
> 决策来源：用户明确要求（见下文「用户需求」）

---

## 0. 用户需求（原话提炼）

1. **为什么有两套班子？应该是一套班子**——包含：产品经理、前端、后端、测试、运维、修理人员等等。
2. **Leader（即现在的 HR）是固定角色**：决定每个阶段需要什么样的员工。
3. **员工之间互相通信**（例如测试问后端要开发日志）。
4. **每个人员有自己的可复用记忆系统**（这个算通用的），再是各自的 soul。
5. **删掉**双模式（修复/搭建）这种割裂——HR 是固定角色。
6. 全部改（声明层 + 代码 + 调度逻辑）。

---

## 1. 现状问题诊断

### 1.1 当前是「两套班子 + 双模式路由」，割裂且复杂
- **修复班子**（`workers.yaml`）：aggregator / rootcause / fixer / tester / releaser / retrospector
- **搭建班子**（独立 CR）：architect / backend / deployer
- **HR**（`hr.yaml`）：动态招聘，`manager/SOUL.md` 里写「任务类型识别（修复 vs 搭建）→ 双模式派单」
- `create_task` 加了 `route_via_hr` 参数走 HR 动态组队

**问题**：
- 角色职责重叠/模糊（RootCause vs Architect、Fixer vs Backend、Releaser vs Deployer 界限易混）。
- `state.py` 状态机**写死 6 阶段修复流水线**（SPEC_INPUT→…→RETROSPECT），只认 6 个修复角色 + 6 个里程碑，无法表达「一套班子按阶段动态参与」。
- 记忆系统虽已有 `AgentMemory`（`src/loop/context/agent_memory.py`），但各 SOUL 里**重复手写**记忆沉淀规则，未统一为可复用框架。

### 1.2 目标架构
```
用户任务
   │
   ▼
Leader（= 现在的 HR，固定角色）   ← 团队编排者：决定每阶段需要什么员工、派单、协调
   │  ① 解析任务 → ② 按阶段挑选员工 → ③ 派单 + 协调通信 → ④ 收尾沉淀
   ▼
一套完整研发班子（同一团队，按阶段参与）
  ├─ 产品经理 ProductManager   （需求/规格）
  ├─ 前端 Frontend             （UI/前端）
  ├─ 后端 Backend              （服务器/接口）
  ├─ 测试 Tester               （质量门禁，可与前后端/后端通信要日志）
  ├─ 运维/发布 DevOps          （部署/发布/回滚）
  ├─ 修理工 Fixer              （缺陷根因定位 + 修复）
  └─ 复盘沉淀 Retrospector     （经验沉淀，通用）
  （不再有「修复/搭建」两套班子之分；Leader 按阶段从这套班子里挑人参与）
```

---

## 2. 重构方案分阶段（执行顺序）

> 每阶段做完打勾。**阶段 A/B 是基础，必须先做；阶段 C 声明层；阶段 D/E 代码。**

### 🔥 阶段 A：通用可复用记忆系统（先做，算通用的）
> 目标：把记忆系统做成**所有 Worker 复用**的统一框架，不再各 SOUL 手写。

- [ ] **A1** 泛化 `src/loop/context/agent_memory.py`：确认 `AgentMemory` 已是「按 agent_name 独立目录 + 通用读写/检索/沉淀」的通用实现（已满足），**对外暴露为统一注册表** `AgentMemoryRegistry`：
  - `registry.get(name)` → 返回/懒创建该 Agent 的 `AgentMemory`
  - `registry.all()` / `registry.consolidate_all()` / `registry.snapshot_all()`
  - 统一存储根：`shared/agents/<name>/memory/`（不变）
- [ ] **A2** 记忆系统挂成 **Skill**：新增 `skills/agent-memory/SKILL.md`（含可执行 `scripts/memory_cli.py`：`read`/`write`/`recall`/`consolidate` 子命令），所有 Worker CR 统一挂 `agent-memory` skill——让"可复用记忆"成为显式能力，而非 SOUL 里的文字描述。
- [ ] **A3** 通用记忆契约：定义统一的三段式记忆（每日日志 `YYYY-MM-DD.md` / 长期记忆 `MEMORY.md` / 迭代记录 `iterations.jsonl`），写进 `skills/agent-memory/SKILL.md` 作为所有 Worker 共享契约。

### 🧩 阶段 B：一套完整班子（声明层重构）
> 目标：删掉两套班子，合并为一套完整班子；Leader 为固定角色。

- [ ] **B1** 角色收敛表（映射旧角色 → 新角色）：
  | 新角色（一套班子） | 旧角色合并 | 真实对应 |
  |------------------|-----------|---------|
  | `product-manager` | aggregator | 产品经理（需求/规格/优先级） |
  | `frontend`        | fixer(前端部分) | 前端开发 |
  | `backend`         | fixer(后端部分) + architect(部分) | 后端开发（含接口/服务器） |
  | `tester`          | tester（保留） | 测试工程师（质量门禁） |
  | `devops`          | releaser + deployer | 运维/发布（部署/灰度/回滚） |
  | `fixer`           | rootcause + fixer(缺陷部分) | 修理工（根因定位 + 修复） |
  | `retrospector`    | retrospector（保留） | 复盘沉淀 |
  | `leader`          | hr + team-leader | 团队编排者（固定角色，决定每阶段员工） |
  - **注意**：为减少破坏，可保留旧内部名（aggregator/rootcause/...）作为"角色标识"，只改 SOUL 表述为「一套班子」+ 明确分工。**二选一，需在 B1 决策**。
- [ ] **B2** 重写 `src/agentteams/workers.yaml`：8 个 Worker（product-manager/frontend/backend/tester/devops/fixer/retrospector/leader），每个含 `skills`（统一挂 `agent-memory`）+ `soul`（各自身份）+ `mcpServers`（各自工具）。
- [ ] **B3** 删除独立 CR：`hr.yaml` / `architect.yaml` / `deployer.yaml` / `team-leader.yaml`（并入 leader）；删除或标记废弃 `backend.yaml`（若并入）。
- [ ] **B4** 重写 `src/agentteams/manager/SOUL.md`：删除「任务类型识别（修复 vs 搭建）双模式派单」，改为「Leader 编排一套班子」：
  - 每阶段由 Leader 决定需要哪些员工（产品→设计→编码→测试→发布→复盘）
  - 派单 + 协调员工间通信（如 Tester 向 Backend 要开发日志）
- [ ] **B5** 新增 `src/agentteams/leader.yaml`（固定 Leader Worker CR，role=team_leader 或 orchestrator）。

### 🔗 阶段 C：员工间通信（协作机制）
> 目标：员工之间可互相通信（如测试问后端要开发日志）。

- [ ] **C1** 确认并增强 `AgentBus`/`EventBus`（`src/loop/agent_bus.py`）：支持"定向请求/应答"（request-reply），如 Tester → Backend「请提供开发日志」。
- [ ] **C2** 新 Skill `skills/team-comm/SKILL.md`（含 `scripts/comm_cli.py`：`send`/`request`/`reply`），所有 Worker 挂载，作为员工间通信的统一入口（底层走 AgentBus/Matrix @mention）。
- [ ] **C3** 在 SOUL 里显式写「谁 @mention 谁、谁能向谁请求什么」（协作矩阵）。

### ⚙️ 阶段 D：状态机泛化（代码核心）
> 目标：`state.py` 从「写死 6 角色修复流水线」泛化为「Leader 按阶段决定参与员工」。

- [ ] **D1** `state.py`：保留 PDCA 8 状态（SPEC→ROOT_CAUSE→FIX→TEST→RELEASE→APPROVE→RETROSPECT），但把 `STATE_EXECUTOR` 改为**可配置/可由 Leader 覆盖**（默认给一套班子的角色映射，Leader 可动态调整某阶段参与者）。
- [ ] **D2** 里程碑协议：保留 6 个里程碑词，但补充「阶段参与者」字段（task 运行时记录每个阶段由哪个员工执行），支持 Leader 每阶段动态挑人。
- [ ] **D3** 兼容：`_run_mock` / `_run_delegated` 的 mock 产物与里程碑映射同步更新为「一套班子」。

### 🔧 阶段 E：调度与客户端（代码落地）
- [ ] **E1** `agentteams_loop.py`：`mock_outputs` / `agent_names` 更新为「一套班子」8 个员工；`record_agent_iteration` / `consolidate_all_agent_memories` 走新的 `AgentMemoryRegistry`。
- [ ] **E2** `agentteams_client.py`：`create_task` 的 `route_via_hr` 参数**移除**（不再需要双模式）；任务消息改为「交给 Leader 编排一套班子」。
- [ ] **E3** `PDCA_WORKERS` / `STATE_EXECUTOR` 常量更新为新班子。
- [ ] **E4** 删除/废弃双模式相关：`design/TEAM-ECOSYSTEM-RESTRUCTURE.md`（或改写为「一套班子 + Leader 编排」）。

### ✅ 阶段 F：验证与回归
- [ ] **F1** `scripts/verify-skill-refs.py` 更新角色清单，全 PASS（所有 Worker 挂 `agent-memory` + `team-comm`）。
- [ ] **F2** `scripts/verify-worker-single-source.py` 更新 ROLE_KEYWORDS，全 PASS。
- [ ] **F3** 新增测试：`tests/test_memory_registry.py`（通用记忆注册表）+ `tests/test_team_comm.py`（员工间请求/应答，如 Tester→Backend 要日志）。
- [ ] **F4** 全量回归：`demo\.venv\Scripts\python.exe -m pytest tests/ -q` 无回归。
- [ ] **F5** 更新 `AGENT-IDENTITY.md` / `ASSIGNMENT-MATRIX.md` / `README.md` / `TODO.md` 同步新架构。

---

## 3. 关键设计决策（需执行窗口拍板）

| # | 决策点 | 建议 | 理由 |
|---|--------|------|------|
| 1 | 旧角色内部名是否保留 | **保留旧内部名**（aggregator 等）作为角色标识，只重构 SOUL 表述 + 分工，**降低对 state.py/测试的破坏** | 改名会牵动状态机/测试/文档大量改动，收益低 |
| 2 | 是否新增 product-manager / frontend / devops 独立角色 | **建议新增** frontend + devops（原 fixer 前后端混、releaser+deployer 合并），product-manager 可由 aggregator 演进 | 更贴近"一套完整班子"，评审叙事更清晰 |
| 3 | HR/team-leader 是否合并为一个 Leader | **合并**：一个固定 Leader（orchestrator），承担原 HR 编排 + 原 team-leader 协调 | 用户明确"Leader 固定角色" |
| 4 | 通用记忆是否作为 Skill 暴露 | **是**：`skills/agent-memory` + 脚本，所有 Worker 挂 | 让"可复用记忆"成为显式能力 |

---

## 4. 验收标准

- [ ] `workers.yaml` 只剩**一套班子**（≤8 个角色 + 1 个固定 Leader），无 architect/backend/deployer/hr 分裂 CR。
- [ ] 每个 Worker 挂 `agent-memory` + `team-comm` skill（通用记忆 + 员工通信）。
- [ ] `create_task` 不再有 `route_via_hr`，统一「交给 Leader 编排一套班子」。
- [ ] `state.py` 保留 PDCA 8 状态，但 Leader 可每阶段动态决定参与者。
- [ ] Tester 能向 Backend 请求开发日志（`tests/test_team_comm.py` 通过）。
- [ ] 记忆系统通用可复用（`tests/test_memory_registry.py` 通过）。
- [ ] 全量回归无回归（155+ passed）。

---

## 5. 相关文档索引
- 现状角色：`../src/agentteams/workers.yaml` / `../src/agentteams/manager/SOUL.md` / `../agents/AGENT-IDENTITY.md`
- 记忆实现：`../src/loop/context/agent_memory.py` / `../src/loop/context/__init__.py`
- 状态机：`../src/loop/state.py`
- 调度客户端：`../src/loop/agentteams_loop.py` / `../src/loop/agentteams_client.py`
- 通信：`../src/loop/agent_bus.py`
- 旧双模式方案（将被改写/废弃）：`../design/TEAM-ECOSYSTEM-RESTRUCTURE.md`
