# UModel 统一数据模型接入方案（UNIFIED-MODEL-INTEGRATION）

> GOAI · 赛道三「软件研发全流程协同」· 协同基点 AgentTeams
> 本文回答：「研发 Worker 之间共享状态（`state.json`）和知识库（RAG）的 schema 是自定义、非统一的，怎么用**阿里官方 UModel（Unified Model）** 把它统一成一份可被 AI Agent 查询的语义对象图？」
> 原则：**复用阿里官方统一数据模型，不重复造 schema，不引入第三方模型**。
> 更新日期：2026-08-15

---

## 0. 一句话结论

> 引入阿里官方 **UModel（Unified Model，alibaba/UnifiedModel）** 作为「统一数据模型」组件：把项目当前自定义的 `shared/tasks/{id}/state.json`（共享状态）与 `shared/knowledge/*.md`（知识库）的 schema，收敛为一份 **workspace-scoped 对象图模型包（`.umodel`）**，让 6 个研发 Worker 通过 `umctl` CLI 或 `umodel-mcp` 用统一的 `.entity` / `.topo` / `.umodel` 查询理解"任务 / 缺陷 / 根因 / 补丁 / 测试 / 发布 / 复盘"的实体与关系——**Agent 不再各自硬编码文件路径和字段，而是读统一语义层**。

---

## 1. 为什么需要 UModel（对齐评审维度）

评审维度 **多Agent协同 25% + 工程落地 20%** 都要求：Worker 之间是「**基于统一上下文的协作**」，而非「各自读自己约定俗成的临时文件」。

当前痛点是 **schema 碎片化**：

| 数据 | 当前自定义位置 | 问题 |
|------|---------------|------|
| 任务流转 | `shared/tasks/{id}/state.json` | 每个 Worker 靠记忆拼字段，无类型约束 |
| 知识库 | `shared/knowledge/{id}.md`（frontmatter） | 字段自由，无统一关系 |
| 交接产物 | `tasks/{id}/{spec,root-cause,fix,test-report}.md` | 文件即契约，Agent 需猜字段名 |
| 复盘沉淀 | Retrospector 输出 | 与缺陷/修复/验证**无结构化关联** |

**UModel 的解法**：把这些数据组织成 **object graph**——EntitySet（实体类型）+ 类型化关系（link）+ Storage（数据源），通过 `.umodel`（模型）/`.entity`（实体实例）/`.topo`（拓扑关系）统一查询。这正好对齐官方 REFS.md 的定位：「**统一数据模型/实体关系建模，可用于共享状态与知识库 schema 设计**」。

---

## 2. UModel 官方组件概览（复用对象）

| 官方能力 | 位置（`references/refs/unified-model/`） | 我们复用 | 我们写胶水 |
|----------|------------------------------------------|----------|-----------|
| **模型包**（EntitySet/DataSet/Link/Storage） | `examples/quickstart-multidomain/umodel/*.yaml` | YAML 语法（kind/schema/metadata/spec） | 项目专属 `.umodel` 模型包 |
| **Query Service**（`.umodel`/`.entity`/`.topo` SPL） | `docs/zh/reference/`、`sdk/` | `umctl query run <ws> "<SPL>" -o json` | 查询指引/封装脚本 |
| **Agent 技能** | `skills/umodel-query/`、`skills/umodel-rca/` | `umodel-query`（读实体/关系/模型）、`umodel-rca`（模型引导根因分析） | 映射到我们的 RootCause Worker |
| **MCP** | `umodel-mcp`（`query_spl_execute` 工具） | 通过 AgentTeams `Worker.spec.mcpServers` 挂到 Worker | 注册到 Higress（复用 `register-mcp.ps1`） |
| **CLI** | `cmd/umctl` | `umctl` 读查询 | 验证脚本 |

> **为什么是"统一数据模型"而不是又一种 RAG 存储**：UModel 不是向量库，而是**语义运行时**——它定义"对象是什么、对象之间什么关系"，让 Agent 按语义查询而非按文件路径猜。它与项目已有 MinIO 文件存储、RAG 检索是**互补**关系（UModel 提供统一 schema 视图，底层数据仍可落 MinIO）。

---

## 3. 项目对象图设计（研发 PDCA 语义层）

我们把研发闭环建模为一组 EntitySet + Link，对齐 6 Worker 的 PDCA 分工：

### 3.1 EntitySet（实体类型）

| 实体 | 对应项目概念 | 关键字段（对齐 `state.py`/`RAG-MEMORY.md`） | 产出方 |
|------|-------------|-------------------------------------------|--------|
| `dev.task` | 共享任务（映射 `state.json`） | id / title / current_state / milestones / rollback_count / owner | Manager/Leader |
| `dev.defect` | 缺陷 | id / severity / status / description / detected_at / source | Aggregator |
| `dev.root_cause` | 根因分析 | id / symptom / evidence / root_cause / confidence / impact_scope | RootCause |
| `dev.patch` | 修复补丁 | id / change_summary / files / rollback_plan / status | Fixer |
| `dev.test_case` | 测试用例 | id / coverage / scenario / expected | Tester |
| `dev.test_report` | 测试报告 | id / pass_count / fail_count / coverage / verdict | Tester |
| `dev.release` | 发布确认 | id / version / gate_result / rollback_ready / approved_by | Releaser |
| `dev.retrospective` | 复盘沉淀（知识库条目） | id / root_cause / solution / verification / tags / reusability | Retrospector |
| `dev.worker` | Agent 成员 | id / role / status / skill_tags | Manager |

### 3.2 Link（关系，对齐 PDCA 里程碑握手链）

```
dev.task ──produces──> dev.defect
dev.defect ──analyzed_by──> dev.root_cause
dev.root_cause ──fixed_by──> dev.patch
dev.patch ──verified_by──> dev.test_report        (含 dev.test_case 集合)
dev.test_report ──approved_by──> dev.release
dev.release ──reviewed_by──> dev.retrospective
dev.retrospective ──enriches──> dev.task          (沉淀反哺新任务)
dev.task ──assigned_to──> dev.worker
dev.patch ──committed_by──> dev.worker
```

> 这条关系链正好就是项目 `PDCA-CLOSED-LOOP.md` 的里程碑握手（`ROOT_CAUSE_FOUND → FIX_APPLIED → TEST_PASSED → RELEASE_OK → RETROSPECT_DONE`），只是从"散落的文件 + 消息里的里程碑词"升级为"统一对象图 + 类型化关系"。

### 3.3 Storage（数据源绑定）

把 UModel 的 EntitySet 与底层真实数据源绑定（可绑定 MinIO 文件、或后续 PolarDB）：

| Storage | kind | 说明 |
|---------|------|------|
| `dev.minio.tasks` | minio | `shared/tasks/` 对象存储 |
| `dev.minio.knowledge` | minio | `shared/knowledge/` 对象存储 |

---

## 4. 接入步骤（分层）

### 4.1 L0 · 模型包定义（本次落地核心）
- 新增 `src/agentteams/umodel/` 目录，按官方语法写 entity_set / link / storage 的 `.umodel` 模型包 YAML。
- 这套 YAML 就是"统一数据模型"的**唯一真相源**——Worker 读 schema、写实体都对齐它。

### 4.2 L1 · Agent 技能复用（本次落地）
- 把官方 `umodel-query`、`umodel-rca` 两个 SKILL 映射到项目：
  - `umodel-query` → 所有 Worker（读实体/关系/模型）
  - `umodel-rca` → RootCause Worker（模型引导根因分析，替代纯搜索）

### 4.3 L2 · MCP 接入（复赛环境执行）
- 通过 AgentTeams `Worker.spec.mcpServers` 挂 `umodel`（`umodel-mcp`），复用现有 `register-mcp.ps1` 注册到 Higress → Worker 用 `mcporter call umodel query_spl_execute` 查询。
- 凭据只存网关，Worker 不落真实 key（与既有 MCP 安全模型一致）。

### 4.4 L3 · 运行时落地（复赛/决赛）
- 用 UModel Query Service 作为共享状态/知识库的统一读取入口，替换/叠加现有 `shared/tasks/`、`shared/knowledge/` 的硬编码文件访问。

---

## 5. 与现有组件的衔接

| 现有组件 | 与 UModel 衔接 |
|---------|---------------|
| `RAG-MEMORY.md`（共享状态 + 知识库） | UModel 为它提供**统一 schema 视图**；文件仍落 MinIO |
| `PDCA-CLOSED-LOOP.md`（里程碑握手） | UModel link 链 = 里程碑链的对象图化 |
| `state.py`（确定性状态机） | 状态仍是确定性 enum；UModel 负责**查询**状态，不负责**流转** |
| `MCP-INTEGRATION.md`（工具链） | `umodel` 作为新的 MCP Server 加入工具链矩阵 |
| `skills/ASSIGNMENT-MATRIX.md` | 新增 `umodel-query`（all）/ `umodel-rca`（rootcause）挂载 |
| `SANDBOX`（Worker 容器隔离） | `umctl`/`mcporter` 只在容器内读，只读安全 |

---

## 6. 落地产物清单

| 文件 | 用途 | 状态 |
|------|------|:---:|
| `design/UNIFIED-MODEL-INTEGRATION.md` | 本接入方案 | ✅ 本文 |
| `src/agentteams/umodel/entity_set/*.yaml` | 9 个研发实体类型定义 | ✅ |
| `src/agentteams/umodel/link/*.yaml` | 9 条关系定义 | ✅ |
| `src/agentteams/umodel/storage/*.yaml` | 2 个存储绑定（minio tasks/knowledge） | ✅ |
| `src/agentteams/umodel/README.md` | 模型包使用指南 | ✅ |
| `scripts/verify-umodel-model.py` | 模型包 YAML 完整性自检 | ✅（PASS：9 entity / 9 link / 2 storage） |
| `skills/umodel-query/SKILL.md` / `skills/umodel-rca/SKILL.md` | 复用官方技能（指向官方 refs） | ✅ |
| `skills/ASSIGNMENT-MATRIX.md` | 分配矩阵 §三-b/§七 已加 UModel skill + MCP | ✅ |
| `src/agentteams/workers.yaml` | 6 Worker 已挂 `umodel-query`（rootcause 另挂 `umodel-rca`）+ `umodel` MCP | ✅ |

> 2026-08-15 补齐：9 条 link 全量、`storage/` 2 个存储、README、`workers.yaml` 的 skill/mcpServers 挂载。`python scripts/verify-umodel-model.py` → `{"status":"PASS","entity_sets":9,"links":9,"storages":2,"failures":[]}`。

---

## 7. 下一步（待办）

- [x] 补全模型包：9 entity + 9 link + 2 storage + README + verify 脚本（已全部落地并自检通过）。
- [ ] 本地 `make quickstart QUICKSTART_SAMPLE=examples/quickstart-multidomain` 起 UModel 服务，导入本模型包，`umctl query run demo ".umodel with(kind='entity_set')" -o json` 验证实体类型可枚举。
- [ ] 复赛环境：把 `umodel` MCP 注册到 Higress + 挂载到 Worker（复用 `register-mcp.ps1`）。
- [ ] 把 `shared/tasks/{id}/state.json`、`shared/knowledge/*.md` 的写入逻辑按 `.umodel` 字段约束落地（UModel 提供 schema 校验）。
- [ ] 更新 `README.md` / `TODO.md` 回填 UModel 接入状态（本文已同步）。

---

## 8. 文档索引

- 官方 UModel 仓库：`references/refs/unified-model/`（README.zh-CN.md）
- 官方模型包示例：`references/refs/unified-model/examples/quickstart-multidomain/umodel/`
- 官方 Agent 技能：`references/refs/unified-model/skills/`
- 官方 MCP 参考：`references/refs/unified-model/docs/zh/reference/mcp.md`
- 共享状态/知识库现状：`design/RAG-MEMORY.md`
- 里程碑握手：`design/PDCA-CLOSED-LOOP.md`
- 工具链 MCP 接入：`design/MCP-INTEGRATION.md`
- 待办：`TODO.md`
