# Skill 总注册表（REGISTRY）

> GOAI · 赛道三「软件研发全流程协同」· Skill 运行时发现目录（Catalog）
> 本文件模拟 AgentScope/AgentTeams 运行时注入给 Agent 的那份**能力清单**（`<agent-skills>` 目录），是 Skill 的**发现层**（Discovery Layer）：Agent 靠它知道"有哪些技能可用、何时用"。
> 更新日期：2026-08-12

---

## 一、为什么要有注册表

调研结论（见 `references/theory/SKILL-REGISTRY-RESEARCH.md`）：Skill 不是"写死在 Worker 里"的代码，而是**可被运行时发现、按需加载、动态分配/回收的能力包**。所有成熟实现（AgentSkills 规范 / OpenClaw Registry / JFrog / Voyager）都依赖一个**注册表（Registry/Catalog）**作为发现入口：

| 来源 | 注册表形态 | 作用 |
|------|-----------|------|
| AgentSkills 规范 | `Catalog`（name+description+路径 列表） | 会话启动扫描注入，让 Agent 知道能力清单 |
| OpenClaw Registry | `skill.json` 元数据 + 注册服务器 | 发现/搜索/分发/版本 |
| JFrog | 集中式 Registry + 策略 | 治理/审批/签名/权限 |
| Voyager | 向量库（描述向量→程序） | 语义检索 Top-K 复用 |
| AgentScope/AgentTeams | `Workspace.list_skills()` / `Worker.spec.skills` | 运行进 system prompt 或挂载到 Worker |

**注册表 = 发现层**：它只存**元数据**（name/description/版本/分类/依赖/触发），**不存** Skill 正文（正文在各自的 `SKILL.md`，按需加载）。这避免了"一次注入全部 Skill 正文"的上下文膨胀。

---

## 二、注册表 Schema（对齐 OpenClaw skill.json）

每个 Skill 在注册表中登记一条标准元数据。字段对齐 OpenClaw `skill.json` + AgentSkills 规范 + 我们官方 9 字段：

```json
{
  "name": "code-gen",                // 唯一标识，kebab-case
  "version": "1.0.0",                // 语义化版本 SemVer
  "category": "domain|base|coordination",   // 分层：领域/基座/协同
  "description": "生成最小修复补丁并应用",   // 发现路由关键词（触发用）
  "assign_when": "技术栈开发 Worker 需要生成修复补丁时分配",
  "owner_agent": "Fixer",            // 默认归属 Agent（可动态改）
  "pdca": "D",                       // PDCA 象限
  "milestone_in": ["ROOT_CAUSE_FOUND"],
  "milestone_out": ["FIX_APPLIED"],
  "depends_on": ["git-operations", "repo-context", "code-search"],  // L1 依赖
  "mcp_servers": ["ci", "static-analysis"],      // MCP 工具连接（可选）
  "compatibility": {"runtime": "qwenpaw|openclaw", "os": "linux"},
  "license": "Apache-2.0",
  "author": "votek-dev",
  "tags": ["fix", "code", "patch"],
  "path": "skills/code-gen/SKILL.md"
}
```

> 这份 `skill.json` 是**给运行时/管理器**看的结构化元数据（OpenClaw 式），而 `SKILL.md` 是**给 Agent** 看的指令正文（Anthropic 式）。两者并存：`skill.json` 驱动注册/发现/分配，`SKILL.md` 驱动执行。

---

## 三、全量注册表（L0 + L1 + L2 + L3）

### L0 工程层（归 Manager，比赛官方 AgentTeams 编排）
| name | description（触发词） | assign_when | 依赖 |
|------|----------------------|-------------|------|
| `manage-skill` | Skill 工程全生命周期编排：创建/注册/分配/回收/同步到 Worker。触发：skill、技能、管理skill、编排skill、新建skill、分配skill | Manager 需要集中创建/分配/回收/同步 Worker 的 skills 时 | `skills/scripts/`（官方 push/render/find）+ `Worker.spec.skills` |

> L0 工程层是「用 Skill 管理 Skill」的治理中枢：Manager 通过官方脚本（`push-worker-skills.sh`/`render-skills.sh`/`agentteams-find-skill.sh`）集中管理所有 Worker 的 skills，详见 `skills/README.md` 与 `skills/ASSIGNMENT-MATRIX.md`。

### L3 协同层（归 Manager/Team Leader）
| name | description（触发词） | assign_when | 依赖 |
|------|----------------------|-------------|------|
| `collaboration-loop` | 研发闭环调度：任务拆解/里程碑握手/验证闸门/回滚判定。触发：调度、拆解、闭环、loop | Manager 需要驱动研发闭环状态流转时分配 | L1 全部 |

### L2 领域层（7 核心，官方必查）
| name | owner | PDCA | description（触发词） | milestone_in → out | 依赖 |
|------|-------|------|----------------------|--------------------|------|
| `issue-parsing` | Aggregator | P | 多源缺陷/需求聚合去重归一化。触发：缺陷、聚合、去重、triage | — → `TASK_SPEC_READY` | code-search, knowledge-rag, evidence-log |
| `root-cause-analysis` | RootCause | D | 代码根因定位（RCA）。触发：根因、定位、RCA | `TASK_SPEC_READY` → `ROOT_CAUSE_FOUND` | code-search, repo-context, git-operations, knowledge-rag |
| `impact-analysis` | RootCause | D | 修复影响面/风险分级。触发：影响面、impact、波及 | 根因报告 → 并入根因报告 | repo-context, code-search, git-operations |
| `code-gen` | Fixer | D | 生成最小修复补丁。触发：修复、补丁、fix | `ROOT_CAUSE_FOUND` → `FIX_APPLIED` | git-operations, repo-context, code-search |
| `test-generation` | Tester | C | 生成测试并作为验证闸门。触发：测试、验证、闸门 | `FIX_APPLIED` → `TEST_PASSED/FAILED` | code-search, repo-context, evidence-log |
| `release-gate` | Releaser | A | 发布门禁+灰度+回滚。触发：发布、灰度、回滚 | `TEST_PASSED` → `RELEASE_OK/ROLLED_BACK` | evidence-log, knowledge-rag |
| `retrospective` | Retrospector | A | 复盘+知识沉淀。触发：复盘、总结、沉淀 | `RELEASE_OK` → `RETROSPECT_DONE` | knowledge-rag, evidence-log |

### L1 基座层（跨 Agent 复用）
| name | description（触发词） | 被谁依赖 |
|------|----------------------|---------|
| `git-operations` | Git 操作：分支/checkout/diff/blame/commit，安全提交审计 | root-cause, code-gen |
| `code-search` | 代码检索：ripgrep 全文 + 语义搜索 | 几乎全部 |
| `repo-context` | 仓库结构感知：模块/依赖图/变更范围 | root-cause, impact, code-gen |
| `knowledge-rag` | 知识库检索/写入：经验教训、已修复缺陷 | issue-parsing, root-cause, retrospective |
| `evidence-log` | 执行证据沉淀：Trace/Log/报告落盘可审计 | 全部 |
| `doc-gen` | 文档生成：Markdown/HTML → Word(.docx)/PDF，中文字体/表格/代码块/页码 | Leader, Aggregator, RootCause, Tester, Releaser, Retrospector |
| `doc-management` | 文档任务全生命周期状态机：多阶段推进 + 执行/验收分离（done ≠ accepted）+ 断点恢复。触发：文档管理、评审、验收、定稿、归档、长文档 | DocManager（引用 `vendor/aris/run_state.py`） |
| `evidence-check` | 确定性证据预检：验收前机械校验被引用的证据真实存在（路径+数字/字符串在源里），零模型、fail-closed。触发：证据、预检、验证报告、验收 | Tester（验收前）、Releaser（发布前）、DocManager（定稿前） |
| `injection-scan` | 上下文注入扫描：对第三方内容做 regex 威胁扫描（prompt 注入/外泄/C2），命中隔离。触发：注入、威胁、扫描、污染 | Aggregator（外部需求/抓取入库前） |
| `stall-detection` | 停滞检测：每轮记录新发现数，连续 0 发现 → 结构性转向/上报人类。触发：停滞、卡住、无进展、转向 | Leader（每轮编排） |
| `review-gate` | 跨模型评审路由裁决表：同族评审不能终结验收，仅跨族正向才 accepted，卡住 escalate。触发：评审、裁决、跨模型、accepted | Tester、Releaser（验收裁决） |
| `evidence-integrity` | 验收数据可信度准则（ARIS 协议）：禁伪造 ground truth / 归一化造假 / 幽灵结果，done ≠ accepted。触发：完整性、造假、可信度、验收准则 | Leader、Releaser、Tester（验收准则） |
| `dispatch-contract` | 派发契约化（借鉴 oil-oil codex-team-mode）：派发包七要素模板 + 派发哨兵 fail-closed（缺验收标准即拒）+ 独立复审包协议 + 角色-模型映射。触发：派发、派单、切片、契约、哨兵、dispatch、brief、复审包、路由、协调 | Coordinator（协同路由员，派发前必经哨兵） |

---

## 三·B、外部 Skill 归档区（oil-oil 参考库，2026-09-01 新增）

> 归档 GitHub 用户 **oil-oil** 的 29 个原创 Skill 至 `skills/oil-oil/`（按项目形式：目录 + `SKILL.md` + 可选 scripts/references/assets）。**不挂载任何 Worker**，仅作外部参考与理念借鉴。清单、frontmatter name 映射与借鉴建议见 `skills/oil-oil/README.md`；人物调查见 `references/oil-oil/INVESTIGATION.md`。

代表性借鉴候选：

| 归档目录 | frontmatter name | 潜在借鉴点 |
|---|---|---|
| `oil-oil/codex-team-mode` | `team-mode` | 多 Agent 派发/协作（已借鉴出 `dispatch-contract`） |
| `oil-oil/oil-skill-creator` | `oil-skill-creator` | Skill 工程方法论 → 完善 `manage-skill` |
| `oil-oil/git-ship` | `git-ship` | 分支/PR/发布一键流 → 简化 `release-gate` |
| `oil-oil/html-doc` | `html-doc` | 视觉优先文档 → 借鉴 `doc-gen` HTML 中间层 |
| `oil-oil/oil-tone` | `oil-tone` | 文案文风规范 → 团队报告/复盘表达 |
| `oil-oil/react-flow-advanced-best-practices` | `react-flow-advanced-best-practices` | 关系图/流程图前端 → UModel 可视化 |

---

## 四、注册表的三层加载（对齐 AgentSkills 渐进式披露）

> 借鉴 AgentSkills 规范的 **Catalog → Instructions → Resources** 三层加载，避免上下文膨胀：

| 层 | 内容 | 时机 | 我们落点 |
|----|------|------|---------|
| **Catalog（发现）** | 全部 Skill 的 `name` + `description`（本注册表第二节的元数据，不含正文） | 会话启动 / 动态团队组建时 | 注入 Manager 的 system prompt（`<agent-skills>` 目录） |
| **Instructions（激活）** | 命中任务的 `SKILL.md` 完整正文 | Manager/Agent 决定调用该 Skill 时 | 通过 SkillViewer / load_skill 读取正文 |
| **Resources（执行）** | `scripts/` `references/` `assets/` 具体文件 | 正文引用且需要时 | 按需读取 |

> **本注册表就是 Catalog 层**：它只列出 name/description/依赖等元数据，供 Agent 判断"何时用哪个 Skill"。正文仍在各 `SKILL.md`，用到才加载。

---

## 五、注册表如何被运行时消费（三种机制对应）

| 场景 | 消费方式 | 对应 AgentTeams 能力 |
|------|---------|---------------------|
| **固定 Worker 启动** | 按 `Worker.spec.skills` 挂载 → 注入 Catalog | 内置 skill 自动分配（pushBuiltinSkills） |
| **动态招工** | Manager 查注册表 → 按 `assign_when` + `compatibility` 选 Skill → 挂载给新 Worker | 按需分配（PushOnDemandSkills） |
| **远程共享** | 从 nacos:// 拉取注册表元数据 → 分发 | 远程 skill（pushRemoteSkills） |

> 注册表本身也可作为**共享资源**存于 `shared/skills/registry.json`，供多个项目/团队复用（对齐 JFrog "单一系统记录" + Voyager "可移植技能库"）。

---

## 六、版本与演化（对齐 OpenClaw/JFrog 最佳实践）

- **语义化版本**：`MAJOR.MINOR.PATCH`。`description` 变更视为 MAJOR（直接影响触发召回），需回归测试。
- **来源溯源**：每条注册项记录 `author`/`license`/`path`，保证可审计（JFrog 血缘追踪）。
- **质量门控**：新 Skill 入注册表前必须通过 `evals/` 评测（正向触发/负向不触发/边界/异常），对齐 Anthropic 规范。
- **冲突处理**：同 `name` 冲突时按「项目级 > 用户级 > 内置」优先级，记录冲突告警。

---

## 文档索引
- 调研依据：`references/theory/SKILL-REGISTRY-RESEARCH.md`
- 动态生命周期设计：`design/SKILL-LIFECYCLE.md`
- Skill 清单主文档：`skills/SKILL-LIST.md`
- 外部 Skill 归档区（oil-oil 参考库）：`skills/oil-oil/README.md`
- 各 Skill 正文：`skills/<name>/SKILL.md`
- 比赛官方 Skill 手册：`skills/README.md`
- Skill → Worker 分配真相源：`skills/ASSIGNMENT-MATRIX.md`
- 官方管理脚本：`skills/scripts/`（`push-worker-skills.sh` / `render-skills.sh` / `agentteams-find-skill.sh`）
- 引入的 ARIS 长时间工作管理模块（原封不动）：`vendor/aris/README.md`
- L0 元 Skill（编排）：`skills/manage-skill/SKILL.md`
- 官方 AgentTeams 源码：`references/refs/agent-teams/`

> 比赛官方 = 定义 + 管理脚本（管 Skill 如何定义/分配/同步到 Worker）；本注册表 = 发现层（管运行时如何发现/分配）。两者配合，参见 `skills/README.md` 第七节。
