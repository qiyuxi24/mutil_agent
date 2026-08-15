# Skill 清单（SKILL-LIST）

> GOAI 世界人工智能开源大赛 · 赛道三「软件研发全流程协同」· Skill 工程体系
> 本文件是项目 Skill 清单主文档：**7 个核心 Skill × 官方 9 字段**，覆盖 PDCA 闭环全流程，并映射到 AgentTeams 框架的 Skill 机制。
> 更新日期：2026-08-12

---

## 一、Skill 在作品中的定位

官方定义：**Skill 是「任务能力抽象层」，而非一次性 Agent 行为描述**。Skill 承担任务能力抽象层，MCP 承担工具连接层，Agent 承担决策层。

> 一句话：**Agent 决定「做什么」，Skill 决定「怎么做」**。Skill 把领域知识（怎么聚合缺陷、怎么做根因分析、怎么生成测试）沉淀成可复用的能力包，随项目动态加载/卸载，支撑「AI 公司式动态 Agent 团队」。

---

## 二、调研结论：三个框架的 Skill 机制（作为设计依据）

> 通过源码调研 AgentTeams（协同基点）、AgentScope（技术底座）、MAF（参考实现），提炼统一 Skill 范式：

| 维度 | AgentTeams（协同基点） | AgentScope（底座） | MAF（参考） | 我们的设计采用 |
|------|------|------|------|------|
| **载体** | 目录 + `SKILL.md` + `scripts/` + `references/` | 目录 + `SKILL.md` | frontmatter + instructions + resources + scripts | ✅ 目录 + `SKILL.md` + 可选 scripts/references |
| **frontmatter** | `name` + `description`；Worker 版额外 `assign_when` | `name` + `description` | `name` + `description` + `license` + `compatibility` + `allowed_tools` | ✅ `name` + `description` + `assign_when`（可分配） |
| **执行方式** | 提示词注入 + 脚本（render-skills.sh 白名单 envsubst） | **纯提示词注入**（Skill 非函数，SkillViewer 读取正文再遵指令） | 提示词注入 + 3 工具（load_skill/read_resource/run_script） | ✅ **纯提示词注入指令集** + 可选脚本 |
| **触发路由** | description 里的自然语言触发词 | 元数据全量注入 system prompt，Agent 按需用 Skill 工具读正文 | 渐进式披露，只列 name+description | ✅ 元数据全量注入 + 正文按需读取 |
| **挂载** | `Worker.spec.skills` | workspace.list_skills() → Toolkit | SkillsProvider（ContextProvider） | ✅ 落到 `Worker.spec.skills` |
| **分配** | 内置自动分配 / 按需 PushOnDemand / 远程 nacos | skill_paths 配置 | 组合源 + 去重 | ✅ 动态招工 / 裁员时按 `assign_when` 分配 |
| **安全边界** | render-skills.sh 白名单、envsubst | 路径穿越防护、.env/.ssh/.git 保护、沙箱解压、大小限制 | frontmatter 严格校验 | ✅ 失败处理 + 安全边界字段必填 |

**统一范式（我们遵循）**：
1. Skill = 一个目录，含 `SKILL.md`（YAML frontmatter + 分步指令正文），可附 `scripts/`（可执行脚本）与 `references/`（参考）。
2. frontmatter 只写 `name` + `description`（路由触发靠 description 里的触发词）。
3. **Skill 不是函数调用**，是"指令集"——Agent 读取 SKILL.md 正文后，遵循其中的步骤并使用 Agent 可用的工具执行。
4. description 质量决定触发准确性，指令正文质量决定执行质量，二者都要精雕。

---

## 三、Skill 工程体系：分层与协同

我们的 Skill 不是平铺的 7 个，而是**三层体系**，体现"Skill 工程与生态复用"（25% 权重）：

```
┌─────────────────────────────────────────────────────┐
│  L3 协同层（流程编排 Skill，归 Manager/Leader）        │
│  ──────────────────────────────────────────────────  │
│  collaboration-loop：研发闭环调度（任务拆解/里程碑握手/   │
│   验证闸门/回滚判定）  —— 驱动 8 个闭环状态流转          │
├─────────────────────────────────────────────────────┤
│  L2 领域层（研发能力 Skill，归各职能 Worker）           │
│  ──────────────────────────────────────────────────  │
│  issue-parsing    → 缺陷/需求聚合（P, Aggregator）     │
│  root-cause-analysis → 根因定位（D, RootCause）        │
│  impact-analysis  → 影响面分析（D, RootCause）         │
│  code-gen         → 修复生成（D, Fixer）              │
│  test-generation  → 测试生成（C, Tester）              │
│  release-gate     → 发布门禁（A, Releaser）            │
│  retrospective    → 复盘沉淀（A, Retrospector）        │
├─────────────────────────────────────────────────────┤
│  individual 个体工程纪律层（跨角色通用素养，新增）      │
│  ──────────────────────────────────────────────────  │
│  align    → grill-me / domain-modeling（想清楚）       │
│  build    → tdd / codebase-design（写对）             │
│  diagnose → diagnosing-bugs（查出来）                 │
│  review   → code-review（把关）                       │
│  deliver  → handoff / writing-for-agents（交接）       │
│  context  → context-hygiene（沉淀/卫生）               │
├─────────────────────────────────────────────────────┤
│  L1 基座层（原子工具 Skill，跨 Agent 共享）             │
│  ──────────────────────────────────────────────────  │
│  git-operations   → Git 操作（checkout/branch/diff）  │
│  code-search      → 代码检索（ripgrep/语义搜索）        │
│  repo-context     → 仓库结构感知（模块/依赖/变更范围）    │
│  knowledge-rag    → 知识库检索（经验教训/已修复缺陷）     │
│  evidence-log     → 执行证据沉淀（Trace/Log/报告）      │
└─────────────────────────────────────────────────────┘
```

- **L1 基座层**：5 个原子 Skill，被 L2 领域 Skill 引用，跨 Agent 复用（体现"复用价值"）。
- **L2 领域层**：7 个核心 Skill（本清单重点，官方必查），对应 6 个职能 Worker，覆盖 PDCA 闭环。
- **individual 个体工程纪律层**：6 类 9 个 Skill，跨角色通用素养，回答「怎么把活干好」（借鉴 Matt Pocock，详见 `skills/individual/README.md` 与 `references/theory/INDIVIDUAL-ENGINEERING-DISCIPLINES.md`）。
- **L3 协同层**：1 个协同编排 Skill，归 Manager/Team Leader，驱动闭环状态流转（衔接 `design/PDCA-CLOSED-LOOP.md` 与 `design/MANAGER-LOOP-DESIGN.md`）。
- **数据层（UModel，2026-08-15 新增）**：`umodel-query`（全部 Worker 按统一数据模型读实体/关系/模型）+ `umodel-rca`（RootCause 模型引导根因分析）。这是阿里官方 UModel 统一数据模型的 Agent 读取面，衔接共享状态/知识库的统一对象图。接入设计见 `design/UNIFIED-MODEL-INTEGRATION.md`。

> ⚠️ 本清单重点展开 **L2 领域层 7 个 Skill**（官方必查项）。L1/L3/数据层属于辅助，在第九节简述，复赛代码包（第 7 项）再完整定义。

---

## 四、7 个核心 Skill 总览

| Skill | 所属 Agent | PDCA | 闭环状态 | 一句话用途 |
|-------|-----------|------|---------|-----------|
| `issue-parsing` | Aggregator（缺陷聚合员） | P | SPEC_INPUT / SPEC_DECOMPOSE | 多源缺陷/需求聚合去重 → 结构化任务说明 |
| `root-cause-analysis` | RootCause（根因定位员） | D | ROOT_CAUSE | 定位代码缺陷根因（RCA） |
| `impact-analysis` | RootCause（根因定位员） | D | ROOT_CAUSE | 评估修复影响面（变更波及范围） |
| `code-gen` | Fixer（修复工程师） | D | FIX_APPLY | 生成/应用修复补丁 |
| `test-generation` | Tester（测试验证员） | C | TEST_VERIFY | 生成测试用例并执行验证 |
| `release-gate` | Releaser（发布确认员） | A | RELEASE / RELEASE_APPROVE | 发布门禁检查 + 灰度 + 回滚 |
| `retrospective` | Retrospector（复盘沉淀员） | A | RETROSPECT | 复盘总结 → 沉淀进知识库 |

---

## 五、官方 9 字段说明项（我们每个 Skill 都覆盖）

| 序号 | 字段 | 含义 |
|------|------|------|
| 1 | 名称 | Skill 唯一标识（小写连字符，≤64 字符） |
| 2 | 用途 | 一句话说明该 Skill 做什么、解决什么问题 |
| 3 | 输入与输出 | 输入：需要什么上下文/材料；输出：产出的结构化结果 |
| 4 | 调用条件 | 什么触发词/状态下该 Skill 被调用（路由依据） |
| 5 | 依赖工具 | 执行时依赖的 L1 基座 Skill、MCP、外部工具 |
| 6 | 失败处理 | 执行失败时的降级/重试/终止策略 |
| 7 | 安全边界 | 权限范围、危险操作防护、敏感信息保护 |
| 8 | 复用价值 | 跨项目/跨 Agent 的可复用性、版本演进 |
| 9 | 与多 Agent 协同流程的关系 | 属于闭环哪个环节、与哪些 Agent 交接 |

---

## 六、7 个核心 Skill 完整定义（9 字段）

### 6.1 `issue-parsing` — 缺陷/需求聚合

> **归 Aggregator（缺陷聚合员，PDCA-P）**

| 字段 | 内容 |
|------|------|
| **1 名称** | `issue-parsing` |
| **2 用途** | 从多源（Issue 系统、日志、用户反馈、监控告警）聚合缺陷/需求，去重、分类、归一化为结构化任务说明（`TASK_SPEC`），作为研发闭环的输入。 |
| **3 输入与输出** | **输入**：原始缺陷/需求条目列表（来源、标题、描述、优先级、严重度、复现信息、日志片段）。<br>**输出**：结构化 `task-spec.json`（任务 ID、标题、分类、优先级、验收标准、关联证据链接、预估影响模块）。 |
| **4 调用条件** | 触发词：`issue`、`需求`、`缺陷`、`聚合`、`去重`、`triage`、`inbox`。状态：`SPEC_INPUT` / `SPEC_DECOMPOSE`。Manager 分派聚合任务时调用。 |
| **5 依赖工具** | L1：`code-search`、`knowledge-rag`（查是否已有同类缺陷）、`evidence-log`；MCP/外部：Issue 系统（Jira/GitHub Issues）、日志查询、监控告警。 |
| **6 失败处理** | 单个来源不可用 → 跳过该源并标记降级；去重冲突 → 按严重度+时间排序取最新，冲突项标记待人工仲裁；无法归类的条目 → 进入"待人工确认"队列，不阻塞主流程。 |
| **7 安全边界** | 只读聚合，不修改任何缺陷源数据；敏感信息（凭据/个人信息）打码后输出；聚合结果需在共享状态 `shared/tasks/{id}/spec.json` 落盘可审计。 |
| **8 复用价值** | 缺陷分类规则（优先级/严重度模型）可沉淀为配置，跨项目复用；聚合经验（常见缺陷模式）回流知识库。 |
| **9 与协同流程关系** | 闭环**第 1-2 环节**（任务输入 + 任务拆解）。产出 `TASK_SPEC_READY` 里程碑，交接给 RootCause/Fixer。 |

---

### 6.2 `root-cause-analysis` — 根因定位

> **归 RootCause（根因定位员，PDCA-D）**

| 字段 | 内容 |
|------|------|
| **1 名称** | `root-cause-analysis` |
| **2 用途** | 基于任务说明与代码仓库，定位缺陷根因，产出根因分析报告（RCA Report），给出证据链。 |
| **3 输入与输出** | **输入**：`task-spec.json`、相关代码路径、日志/调用栈、仓库上下文。<br>**输出**：`root-cause-report.json`（根因文件/函数/行、根因类型、证据链、复现步骤、修复建议方向）。 |
| **4 调用条件** | 触发词：`根因`、`定位`、`为什么`、`root cause`、`RCA`、`调查`。状态：`ROOT_CAUSE`。收到 `TASK_SPEC_READY` 里程碑后调用。 |
| **5 依赖工具** | L1：`code-search`、`repo-context`、`git-operations`（查 blame/变更历史）、`knowledge-rag`（查历史同类根因）；MCP/外部：日志查询、Trace 检索。 |
| **6 失败处理** | 证据不足 → 输出"疑似根因 + 置信度 + 需补充证据"，标注`INCONCLUSIVE`，交 Manager 决定是否派更多 Worker 深挖；误判 → 由 Tester 的验证闸门反向打回（见闭环回滚）。 |
| **7 安全边界** | 只读代码与日志；不执行修复、不写文件；涉及安全漏洞的根因默认不写入公共日志（脱敏后入知识库）。 |
| **8 复用价值** | 根因类型分类（空指针/并发/资源泄漏/配置错误等）与对应排查套路，可沉淀为 RCA 检查清单，跨项目复用。 |
| **9 与协同流程关系** | 闭环**第 3 环节**（上下文传递 + 根因定位）。产出 `ROOT_CAUSE_FOUND` 里程碑，交接给 Fixer。 |

---

### 6.3 `impact-analysis` — 影响面分析

> **归 RootCause（根因定位员，PDCA-D），常与 RCA 联合执行**

| 字段 | 内容 |
|------|------|
| **1 名称** | `impact-analysis` |
| **2 用途** | 评估修复方案的影响面：哪些模块/调用方/测试会被改动波及，给出影响清单与风险分级，为发布决策与测试范围提供依据。 |
| **3 输入与输出** | **输入**：根因报告、拟修复的代码改动范围、依赖图。<br>**输出**：`impact-report.json`（受影响模块、调用链、可能破坏的兼容性、受影响测试、风险等级、是否需要灰度）。 |
| **4 调用条件** | 触发词：`影响面`、`影响`、`波及`、`impact`、`风险`。状态：`ROOT_CAUSE`（定位完成后、修复前）。 |
| **5 依赖工具** | L1：`repo-context`（依赖图/调用链）、`code-search`、`git-operations`；MCP/外部：编译依赖分析、静态分析工具。 |
| **6 失败处理** | 依赖图不完整 → 基于静态调用关系给出"保守影响清单"并标注不确定度；波及范围过大 → 输出风险预警并建议拆分修复，交 Manager 决策。 |
| **7 安全边界** | 只读分析；不改代码；影响面结论需可溯源（引用具体文件/行）。 |
| **8 复用价值** | 影响面评估的判定规则（改动量/耦合度/兼容性）可沉淀为配置，跨项目复用。 |
| **9 与协同流程关系** | 闭环**第 3 环节**延伸。影响报告作为 `ROOT_CAUSE_FOUND` 报告的组成部分，供 Fixer 制定最小改动方案、Releaser 评估发布风险。 |

---

### 6.4 `code-gen` — 修复方案生成

> **归 Fixer（修复工程师，PDCA-D，可多实例按技术栈）**

| 字段 | 内容 |
|------|------|
| **1 名称** | `code-gen` |
| **2 用途** | 基于根因与影响面报告，生成最小修复补丁并应用到代码仓库，产出可验证的修复结果。 |
| **3 输入与输出** | **输入**：`root-cause-report.json`、`impact-report.json`、`task-spec.json`、技术栈约定。<br>**输出**：修复补丁（diff）、修改文件清单、变更说明、自检结果。 |
| **4 调用条件** | 触发词：`修复`、`补丁`、`修改`、`fix`、`patch`、`改动`。状态：`FIX_APPLY`。收到 `ROOT_CAUSE_FOUND` 里程碑后调用。 |
| **5 依赖工具** | L1：`git-operations`（分支/补丁）、`repo-context`、`code-search`；MCP/外部：IDE 工具、静态分析、编译构建。 |
| **6 失败处理** | 编译/静态检查失败 → 迭代修正，最多 N 次；仍失败 → 输出"部分修复 + 失败原因"，回退改动，交 Manager 决定是否更换技术栈 Fixer 或人工介入；修复引入新问题 → 由验证闸门回滚。 |
| **7 安全边界** | 默认在独立分支操作，不直接改主分支；危险操作（改权限/删数据）需审批；凭据/密钥禁止硬编码；改动用 `git diff` 可审计。 |
| **8 复用价值** | 修复模式（针对常见缺陷类型的标准改法）可沉淀为代码模板；多技术栈 Fixer 共享同一 `code-gen` Skill，靠 repo-context 差异化。 |
| **9 与协同流程关系** | 闭环**第 4 环节**（工具调用 + 修复执行）。产出 `FIX_APPLIED` 里程碑，交接给 Tester。 |

---

### 6.5 `test-generation` — 测试生成与验证

> **归 Tester（测试验证员，PDCA-C），质量门禁**

| 字段 | 内容 |
|------|------|
| **1 名称** | `test-generation` |
| **2 用途** | 基于修复内容与验收标准，生成/更新测试用例，执行测试与静态检查，作为**确定性验证闸门**判定修复是否通过。 |
| **3 输入与输出** | **输入**：修复 diff、`task-spec.json` 的验收标准、`impact-report.json` 的受影响测试范围。<br>**输出**：测试用例集、测试执行报告（通过/失败/覆盖率）、`TEST_VERDICT`（PASS/FAIL）。 |
| **4 调用条件** | 触发词：`测试`、`验证`、`用例`、`test`、`用例生成`、`闸门`。状态：`TEST_VERIFY`。收到 `FIX_APPLIED` 里程碑后调用。 |
| **5 依赖工具** | L1：`code-search`、`repo-context`、`evidence-log`；MCP/外部：测试框架（pytest/JUnit 等）、CI、静态分析、覆盖率工具。 |
| **6 失败处理** | 测试失败 → 输出失败详情 + 关联断言，**打回 Fixer**（闭环回滚）；测试环境不可用 → 降级为静态分析 + 类型检查兜底并标注降级；用例生成失败 → 以手工指定用例为准。 |
| **7 安全边界** | 测试在隔离环境执行，不触碰生产数据；禁止在测试中执行生产写操作；测试结果需落盘为执行证据可审计。 |
| **8 复用价值** | 测试用例生成规则 + 覆盖策略可沉淀，跨项目复用；回归测试套件积累提升长期质量。 |
| **9 与协同流程关系** | 闭环**第 5 环节**（结果验证）。产出 `TEST_PASSED` 或 `TEST_FAILED` 里程碑（FAILED 打回 Fixer），是收敛的核心确定性裁判。 |

---

### 6.6 `release-gate` — 发布门禁与回滚

> **归 Releaser（发布确认员，PDCA-A）**

| 字段 | 内容 |
|------|------|
| **1 名称** | `release-gate` |
| **2 用途** | 发布前门禁检查（测试通过、代码评审、兼容性、回滚预案），执行灰度发布并监控，失败时触发回滚。 |
| **3 输入与输出** | **输入**：`TEST_VERDICT`、变更清单、发布配置、回滚预案。<br>**输出**：`release-plan`（灰度策略、金丝雀批次）、`RELEASE_VERDICT`（OK/ROLLED_BACK）、发布/回滚执行证据。 |
| **4 调用条件** | 触发词：`发布`、`上线`、`灰度`、`回滚`、`release`、`deploy`、`gate`。状态：`RELEASE` / `RELEASE_APPROVE`。收到 `TEST_PASSED` 里程碑后调用；高风险动作需人工审批。 |
| **5 依赖工具** | L1：`evidence-log`、`knowledge-rag`（查历史发布问题）；MCP/外部：CI/CD 流水线、监控告警、K8s/云部署、Feature Flag。 |
| **6 失败处理** | 门禁未通过（测试红/评审拒绝）→ 不发布，打回相应环节；灰度中监控异常 → **自动回滚**到上一稳定版本，记录 `RELEASE_ROLLED_BACK`；回滚失败 → 升级人工 + 熔断。 |
| **7 安全边界** | 高风险发布需人工审批（Human-in-the-loop）；灰度先小流量，权限最小化；发布动作全量审计。 |
| **8 复用价值** | 发布门禁清单（必备检查项）与灰度/回滚流程可沉淀为配置，跨项目复用；发布历史回流知识库。 |
| **9 与协同流程关系** | 闭环**第 6-7 环节**（发布确认 + 审批回滚）。产出 `RELEASE_OK`（交 Retrospector）或 `RELEASE_ROLLED_BACK`（打回 Fixer）。 |

---

### 6.7 `retrospective` — 复盘与知识沉淀

> **归 Retrospector（复盘沉淀员，PDCA-A）**

| 字段 | 内容 |
|------|------|
| **1 名称** | `retrospective` |
| **2 用途** | 对一次完整闭环进行复盘，提炼经验教训、失败模式、可复用规则，沉淀到知识库（RAG），形成组织记忆。 |
| **3 输入与输出** | **输入**：任务全生命周期记录（spec → root-cause → fix → test → release → 回滚/证据）。<br>**输出**：`retrospect-report`（复盘总结、经验教训、失败模式、改进建议）、知识库条目（结构化、可检索）。 |
| **4 调用条件** | 触发词：`复盘`、`总结`、`沉淀`、`回顾`、`retrospect`、`review`。状态：`RETROSPECT`。收到 `RELEASE_OK` 里程碑后调用。 |
| **5 依赖工具** | L1：`knowledge-rag`（写入知识库）、`evidence-log`（读取证据）；MCP/外部：知识库存储（PolarDB/向量库）、RAG 检索。 |
| **6 失败处理** | 记录不全 → 基于现有证据生成复盘并标注缺口；知识库写入失败 → 本地暂存，待重试，不阻塞交付。 |
| **7 安全边界** | 复盘内容脱敏（去敏感信息/凭据）；知识库写入需有来源溯源；不自动传播到生产配置。 |
| **8 复用价值** | **组织记忆核心**：经验教训、失败模式、改进建议回流知识库，供后续 Agent 通过 RAG 复用，形成"越用越聪明"的闭环。 |
| **9 与协同流程关系** | 闭环**第 8 环节**（经验沉淀）。产出 `RETROSPECT_DONE`，**闭环闭合**，为下一轮任务提供 RAG 上下文。 |

---

## 七、Skill × Agent × 闭环 映射矩阵

| Skill | Agent | 里程碑（输入） | 里程碑（输出） | 失败流向 |
|-------|-------|--------------|--------------|---------|
| issue-parsing | Aggregator | — | `TASK_SPEC_READY` | 待人工仲裁 |
| root-cause-analysis | RootCause | `TASK_SPEC_READY` | `ROOT_CAUSE_FOUND` | INCONCLUSIVE→Manager |
| impact-analysis | RootCause | 根因报告 | 并入根因报告 | 风险预警→Manager |
| code-gen | Fixer | `ROOT_CAUSE_FOUND` | `FIX_APPLIED` | 部分修复→Manager |
| test-generation | Tester | `FIX_APPLIED` | `TEST_PASSED`/`TEST_FAILED` | `TEST_FAILED`→打回 Fixer |
| release-gate | Releaser | `TEST_PASSED` | `RELEASE_OK`/`ROLLED_BACK` | 回滚→打回 Fixer |
| retrospective | Retrospector | `RELEASE_OK` | `RETROSPECT_DONE`（闭环闭合） | 暂存重试 |

> 与 `design/PDCA-CLOSED-LOOP.md` 的 8 状态、`design/MANAGER-LOOP-DESIGN.md` 的调度工具（`read_milestone`/`write_milestone`）完全对齐。Manager 通过里程碑驱动 Skill 串联。

---

## 八、落成 AgentTeams 资源的映射

每个 Skill 落成 AgentTeams 的 `Worker.spec.skills` 挂载：

```yaml
# 以 code-gen 为例（Fixer Worker 的 skill 挂载）
# Worker.spec.skills
skills:
  - name: code-gen          # Skill 名（L2 领域）
    description: 生成最小修复补丁并应用   # description 即路由触发词来源
    assign_when: "技术栈开发 Worker 需要生成/应用修复补丁时分配"   # Manager 自动分配依据
  - name: git-operations    # L1 基座（被 code-gen 依赖）
  - name: repo-context      # L1 基座
  - name: code-search       # L1 基座
```

对应 AgentTeams 三种分配机制：
- **内置**：固定 Worker（Aggregator/Tester/Releaser/Retrospector）自动挂载其专属 Skill。
- **按需**（动态招工）：Manager 依据 `assign_when` 通过 `PushOnDemandSkills` 给新招募的 Fixer 分配对应技术栈 Skill。
- **远程**：从 nacos:// 拉取共享 Skill（如基座 Skill）统一分发。

---

## 九、L1 基座 / L3 协同 / L0 工程层 Skill（简述，复赛代码包展开）

### L0 工程层（1 个，归 Manager / 比赛官方 AgentTeams 编排）
| Skill | 用途 |
|-------|------|
| `manage-skill` | **元 Skill**：Manager 集中编排 skills/ 全生命周期（创建/注册/分配/回收/同步到 Worker），调用比赛官方 AgentTeams 管理脚本（`scripts/push-worker-skills.sh` / `render-skills.sh` / `agentteams-find-skill.sh`），对齐 `skills/README.md` 与 `ASSIGNMENT-MATRIX.md` |

> L0 工程层是「用 Skill 管理 Skill」的治理中枢，Manager 通过官方脚本集中管理所有 Worker 的 skills，保证整个 Skill 生态与比赛官方 AgentTeams 机制对齐。

### L1 基座层（5 个，跨 Agent 复用）
| Skill | 用途 |
|-------|------|
| `git-operations` | Git 操作：分支/checkout/diff/blame/commit/push，安全提交审计 |
| `code-search` | 代码检索：ripgrep 全文 + 语义搜索，定位符号/调用/引用 |
| `repo-context` | 仓库结构感知：模块划分、依赖图、变更范围、构建入口 |
| `knowledge-rag` | 知识库检索/写入：查历史经验教训、已修复缺陷、失败模式 |
| `evidence-log` | 执行证据沉淀：把 Trace/Log/报告写入审计日志，可追溯 |

### L3 协同层（1 个，归 Manager/Team Leader）
| Skill | 用途 |
|-------|------|
| `collaboration-loop` | 研发闭环调度：任务拆解 → 里程碑驱动 → 验证闸门判定 → 回滚判定，驱动 8 个闭环状态流转（衔接 `MANAGER-LOOP-DESIGN.md`） |

---

## 十、Skill 工程体系的评审亮点（自检）

1. **分层清晰**：L1 原子能力 / L2 领域能力 / L3 协同能力，体现"任务能力抽象层"而非一次性行为描述。
2. **对齐官方 9 字段**：每个 Skill 完整覆盖 9 项，失败处理 + 安全边界 + 复用价值尤其突出（评审重点核验项）。
3. **确定性验证**：`test-generation` / `release-gate` 作为确定性裁判（Ralph 反压思想），收敛不靠 Agent 自律。
4. **动态团队支撑**：Skill 可随招工/裁员动态加载/卸载（`assign_when` + PushOnDemandSkills），支撑"AI 公司式动态 Agent 团队"创新点。
5. **组织记忆闭环**：`retrospective` → `knowledge-rag` → 后续任务 RAG 复用，形成"越用越聪明"的飞轮。
6. **完全落成 AgentTeams**：每个 Skill 可映射 `Worker.spec.skills`，评审核验"是否真正映射框架能力"无障碍。

---

## 十一、每个 Skill 的 SKILL.md 落地

> 每个核心 Skill 一个目录 + `SKILL.md`（frontmatter + 分步指令正文），详见各 `skills/<name>/SKILL.md`。目录结构统一采用 **比赛官方 AgentTeams 框架**（对齐 `worker-skills/`）：`SKILL.md`（frontmatter: name+description+assign_when）+ 可选 `scripts/` `references/` `assets/`，管理手册见 `skills/README.md`，管理脚本见 `skills/scripts/`。

| Skill | SKILL.md 路径 |
|-------|--------------|
| issue-parsing | `skills/issue-parsing/SKILL.md` |
| root-cause-analysis | `skills/root-cause-analysis/SKILL.md` |
| impact-analysis | `skills/impact-analysis/SKILL.md` |
| code-gen | `skills/code-gen/SKILL.md` |
| test-generation | `skills/test-generation/SKILL.md` |
| release-gate | `skills/release-gate/SKILL.md` |
| retrospective | `skills/retrospective/SKILL.md` |
| manage-skill（L0 工程层） | `skills/manage-skill/SKILL.md` |
| git-operations（L1 基座） | `skills/git-operations/SKILL.md` |
| code-search（L1 基座） | `skills/code-search/SKILL.md` |
| repo-context（L1 基座） | `skills/repo-context/SKILL.md` |
| knowledge-rag（L1 基座） | `skills/knowledge-rag/SKILL.md` |
| evidence-log（L1 基座） | `skills/evidence-log/SKILL.md` |

> L1 基座 5 个 Skill（git-operations/code-search/repo-context/knowledge-rag/evidence-log）当前为**初赛占位空壳**（frontmatter 对齐官方格式），复赛补齐指令正文。GAP-11 核对脚本：`python scripts/verify-skill-refs.py --create`。

> **Skill 工程管理脚本（比赛官方 AgentTeams）**：
> - 分配：`bash skills/scripts/push-worker-skills.sh --worker <name> --add-skill <skill>`
> - 回收：`bash skills/scripts/push-worker-skills.sh --worker <name> --remove-skill <skill>`
> - 同步：`bash skills/scripts/push-worker-skills.sh --skill <skill>`
> - 渲染：`bash skills/scripts/render-skills.sh skills/<name>`

---

## 文档索引
- 理论总纲：`references/theory/THEORY.md`
- 个体工程纪律理论：`references/theory/INDIVIDUAL-ENGINEERING-DISCIPLINES.md`
- 个体纪律层手册：`skills/individual/README.md`
- 闭环状态机：`design/PDCA-CLOSED-LOOP.md`
- 调度 loop 设计：`design/MANAGER-LOOP-DESIGN.md`
- Agent 清单：`agents/AGENT-IDENTITY.md`
- 官方要求：`references/docs/OFFICIAL-REQUIREMENTS.md`
