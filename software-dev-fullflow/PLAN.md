# 项目总体实施计划

> GOAI 世界人工智能开源大赛 · 赛道三「软件研发全流程协同」（Agent Infra 方向三）
> 本文件是项目总计划：列明所有要实现的模块、顺序、产出与验收标准。**按编号顺序逐项实现，每项完成后再进入下一项。**
> 更新日期：2026-08-06
> **待办清单（唯一真相源）：见 [TODO.md](./TODO.md)** —— 本文件说「做什么」，TODO.md 说「还剩什么」。

---

## 赛程与硬性节点

| 阶段 | 截止 | 提交材料 |
|------|------|---------|
| 报名 | 7.16 起 | 报名信息 |
| **初赛** | **8.16** | ①作品简介(500字内) ②方案PPT ③(可选)可执行代码包 |
| 复赛 | 9.3 | ①更新版方案 ②AgentTeams代码包 ③Demo/视频 |
| 决赛 | 9.22 | 路演PPT + 现场Demo + 代码仓库最终版 |

**评审权重**：场景价值25% / 多Agent协同25% / Skill工程25% / 工程落地20% / 开源5%

---

## 作品一句话定位

> 用 AgentTeams 的声明式能力，造一支「软件研发 Agent 团队」，把「缺陷/需求聚合 → 根因定位 → 修复 → 测试验证 → 发布确认 → 复盘沉淀」做成**可验证、可回滚、可沉淀的 PDCA 闭环**。

**理论总纲**：PDCA 闭环（主框架）+ 三条子原理（自动化质量门禁 / 最小影响可回滚 / 组织记忆复用）。

**核心创新点（差异化卖点）：「AI 公司」式动态 Agent 团队**
> 作品不仅是"固定 6 个 Agent 跑流水线"，而是支持**按项目需求动态组建团队**——可以"**招人**"（按需招募新职能 Agent）、"**裁员**"（项目结束/角色不需要时移除 Agent）、新招募的 Agent **迅速与既有团队协作出结果**。这解决了"广谱开发的技术栈和提示词不可能预先写死"的痛点。
- **研究依据**：已整理到 `references/theory/DYNAMIC-AGENT-TEAM.md`（含已核实的 arXiv 编号）：
  - 动态招募：AgentInit（Pareto 团队选择，EMNLP 2025）、AgentVerse（专家招募）、AutoGen（GroupChat 增减）
  - 按需技能：Voyager（技能库）、GATE、AgentScope Toolkit、Evolving Programmatic Skill Networks（技能库治理）
  - 自组织/公司形态：MetaGPT（AI 软件公司）、ChatDev（虚拟公司）、Economy of Minds（经济淘汰）、CoMAS（ICLR 2026 团队协同进化）
- **落地可行性**：AgentTeams 原生支持"无状态 Worker 声明式创建/销毁 + 技能加载（skills/mcpServers/nacos）"，天然支撑"招人/裁员/按需扩展技能"，工程可落地。

---

## 实施阶段总览（共 9 项）

| # | 模块 | 产出目录 | 交付物 | 核心权重 |
|---|------|---------|--------|---------|
| 1 | Agent Identity 清单 | `agents/` | 6 个研发 Agent 的 soul+agents | 多Agent 25% |
| 2 | PDCA 闭环状态机 | `design/` | 8 环节状态流转图 + 状态定义 | 多Agent 25% |
| 3 | Skill 清单 | `skills/` | 7 个工程能力 Skill（9 字段） | Skill 25% |
| 4 | 协同流程设计 | `design/` | Team 结构 + 里程碑握手协议 | 多Agent 25% |
| 5 | 可观测设计 | `design/` | Trace/Log/Metrics 方案 | 工程落地 20% |
| 6 | RAG/记忆方案 | `design/` | 知识沉淀 + 共享状态方案 | 工程落地 20% |
| 7 | AgentTeams 代码包 | `src/` | Worker/Team/Skill 的 YAML 定义 | 复赛 |
| 8 | 初赛材料 | `demo/` + 根目录 | 作品简介 + 方案PPT 素材 | 初赛 |
| 9 | Demo 演示 | `demo/` | 演示脚本 + 视频 | 复赛/决赛 |

---

## 详细分解

### ✅ 已完成（参考资料阶段）
- [x] 理论框架：`references/theory/THEORY.md`（PDCA 总纲 + 三条子原理）
- [x] 框架选型：`references/theory/FRAMEWORK-COMPARISON.md`（AgentTeams vs MAF）
- [x] AgentTeams 内部机制：`design/AGENTTEAMS-INTERNALS.md`（架构/API/流程/可改造性/行为准则/资源）
- [x] 多 Agent 拆分粒度：`references/theory/AGENT-TASK-DECOMPOSITION.md`
- [x] 单 Agent 自我迭代：`references/theory/SINGLE-AGENT-ITERATION.md`（Ralph 方法论）
- [x] 官方要求：`references/docs/OFFICIAL-REQUIREMENTS.md`

### 第 1 项前置：角色设计依据 —— 真实开发团队从零开始的角色构成

> 目的：Agent 团队的角色设计，**应当映射真实研发团队的分工**（微信/王者荣耀/淘宝这类产品团队），让"场景价值 + 多Agent协同"更有说服力。以下为业界公认的完整研发团队角色。

**一、通用软件研发团队的标准角色**（来自 PingCode/CSDN 等工程百科，多为 7-9 个核心岗位）：

| # | 角色 | 核心职责 | 是否需要"研发闭环 Agent"覆盖 |
|---|------|---------|---------------------------|
| 1 | 项目经理 (PM) | 进度、任务分配、资源协调、风险控制 | 对应 Manager/Team Leader |
| 2 | 产品经理 (Product) | 需求调研、需求文档、产品原型 | 对应「缺陷聚合员」 |
| 3 | UI/UX 设计师 | 界面与用户体验设计 | 可选（重体验产品需要） |
| 4 | 架构师 (Architect) | 整体架构、技术选型、模块划分 | 对应「根因定位员」(影响面/模块分析) |
| 5 | 前端开发 (Frontend) | 界面代码实现 | 对应「修复工程师」 |
| 6 | 后端开发 (Backend) | 服务端逻辑、数据库 | 对应「修复工程师」 |
| 7 | 测试工程师 (QA) | 测试用例、执行、缺陷跟踪、质量把关 | 对应「测试验证员」 |
| 8 | 运维工程师 (Ops/DevOps) | 部署、上线、监控、稳定性 | 对应「发布确认员」 |
| 9 | 数据分析师 (DA) | 数据洞察、产品决策支持 | 可选（沉淀阶段需要） |

**二、游戏团队（王者荣耀/天美）的特殊角色**（PingCode《王者荣耀怎么开发团队》）：
- 除程序开发外，另有：**游戏策划**（玩法/数值/关卡设计）、**美术设计师**（角色/场景/UI）、**音效设计师**、**运营推广**。→ 游戏团队比纯软件团队多出「内容创作」类角色。
- 启示：**不同的产品形态决定不同的角色集合**。我们的作品聚焦「软件研发全流程」（缺陷修复类），核心角色是 **PM + 架构 + 开发 + 测试 + 运维 + 复盘**，不涉及美术/音效这类内容创作。

**三、产品团队（微信 WXG / 淘宝）的共性**：
- 大厂团队普遍是「产品 + 技术 + 质量 + 运维」四线并行的组织，且有**专职的"复盘/知识沉淀"机制**（如技术委员会、经验库）——对应我们方案的「复盘沉淀员 + RAG 知识库」。

**参考资料（真实团队角色构成来源）**：
- PingCode《软件研发团队包含什么岗位》https://docs.pingcode.com/ask/ask-ask/745461.html
- CSDN《软件开发角色详解：分工合作的IT架构》https://blog.csdn.net/weixin_42639673/article/details/124345381
- PingCode《王者荣耀怎么开发团队》https://docs.pingcode.com/ask/858661.html
- 腾讯《谈腾讯精品游戏的基础技术体系》（游戏团队组织架构）https://gameinstitute.qq.com/course/detail/10040
- 知乎《完整的软件开发团队都需要什么技术人员》https://zhuanlan.zhihu.com/p/409264471

**四、对本项目 Agent 设计的映射结论**：
- 我们的 6 个研发 Agent，本质是上面「通用研发团队 9 角色」中**与代码研发闭环强相关的那部分**做了合并与聚焦：
  - `缺陷聚合员` = 产品经理(需求) + 缺陷管理
  - `根因定位员` = 架构师(影响面/RCA)
  - `修复工程师` = 前后端开发
  - `测试验证员` = 测试工程师
  - `发布确认员` = 运维/DevOps
  - `复盘沉淀员` = 数据分析 + 知识沉淀
  - （项目经理 = AgentTeams 的 Manager/Team Leader，不占 Worker 名额）
- **这样设计的好处**：既覆盖了真实研发团队的关键角色（场景价值可信），又聚焦"缺陷→发布→复盘"这条官方主线，避免了美术/音效等与软件开发无关的角色稀释。

### 第 1 项：Agent Identity 清单（`agents/`）
**产出**：`agents/AGENT-IDENTITY.md` + 每个 Agent 一个 `agents/<name>/` 目录
- 6 个研发职能 Agent，按 PDCA 四象限划分（映射真实研发角色）：
  - **P**：缺陷聚合员（Aggregator）≈ 产品经理 + 缺陷管理
  - **D**：根因定位员（RootCause）≈ 架构师（RCA + 影响面）
  - **D**：修复工程师（Fixer）≈ 前后端开发
  - **C**：测试验证员（Tester）≈ 测试工程师（质量门禁）
  - **A**：发布确认员（Releaser）≈ 运维/DevOps（灰度+回滚）
  - **A**：复盘沉淀员（Retrospector）≈ 数据分析 + 知识沉淀
- 每个 Agent 写：`soul`（人格身份）+ `agents`（工作准则）+ 权限边界 + 里程碑触发词
- 落成 AgentTeams 可直接用的 `Worker.spec` 字段内容
- 附：`AGENT-IDENTITY.md` 开头需有一段"与真实研发团队角色的映射表"（用上面的表格），作为场景价值论据

**验收**：每个 Agent 有清晰的职责、边界、输入输出、里程碑握手词，可直接映射 `Worker.spec.soul/agents`；并能说明"它对应真实研发团队的哪个角色"。

### 第 2 项：PDCA 闭环状态机（`design/`）
**产出**：`design/PDCA-CLOSED-LOOP.md`
- 把官方「闭环 8 环节」映射为状态机（P1任务输入→P2拆解→D1定位→D2修复→C1验证→A1发布→A2复盘）
- 每步定义：输入 / Agent / 产出 / 验证闸门 / 回滚点
- 状态图 + 状态定义表 + 里程碑握手协议（`ROOT_CAUSE_FOUND`→`FIX_APPLIED`→`TEST_PASSED`→`RELEASE_OK`→`RETROSPECT_DONE`）
- 借鉴 Ralph 反压思想：验证闸门用确定性工具（测试/编译/静态分析）当裁判

**验收**：8 环节全部有状态流转、验证点、回滚点，能画出完整闭环图。

### 第 3 项：Skill 清单（`skills/`）
**产出**：`skills/SKILL-LIST.md` + 每个 Skill 一个 `skills/<name>/SKILL.md`
- 7 个工程能力 Skill：`issue-parsing` / `root-cause-analysis` / `impact-analysis` / `code-gen` / `test-generation` / `release-gate` / `retrospective`
- 每个 Skill 按官方 9 字段写：名称/用途/输入输出/调用条件/依赖工具/失败处理/安全边界/复用价值/与协同流程关系

**验收**：每个 Skill 完整覆盖 9 个字段，且能落到 `Worker.spec.skills`。

### 第 4 项：协同流程设计（`design/`）
**产出**：`design/COLLABORATION-DESIGN.md`
- Team 结构：Manager → Team Leader → 6 个职能 Worker 的归属
- 通信契约：谁能 @mention 谁（对应 `channelPolicy` / peer-mentions）
- 上下文传递机制：`shared/tasks/{id}/` 的 spec→plan→result 流转
- 借鉴 AGENTS.md 防死锁规则（噪音@mention、阶段交接、state.json 注册）

**验收**：能说清 6 个 Agent 之间如何组织、通信、传递上下文。

### 第 5 项：可观测设计（`design/`）
**产出**：`design/OBSERVABILITY.md`
- Trace：跨 Agent 的任务链路追踪（任务 id 贯穿全流程）
- Log：各 Agent 决策日志（Matrix 房间记录）
- Metrics：闭环时延、修复通过率、回滚次数
- 对应「工程落地、运行验证与安全可审计 20%」

### 第 6 项：RAG/记忆方案（`design/`）
**产出**：`design/RAG-MEMORY.md`
- 共享状态管理：`shared/tasks/{id}/`（任务流转）
- 知识库 RAG：`shared/knowledge/`（经验教训 + 已修复缺陷）
- Agent 记忆：`memory/YYYY-MM-DD.md` + `MEMORY.md`
- 满足官方「RAG/记忆/共享状态/轨迹可观测 4 选 2」

### 第 7 项：AgentTeams 代码包（`src/`）
**产出**：`src/` 下 Worker/Team/Human/Manager + Skills 的 YAML 定义
- 把第 1-6 项设计转成可执行的 AgentTeams 声明式资源
- 复赛可执行代码包的核心

### 第 8 项：初赛材料
**产出**：`demo/` + 作品简介
- 作品简介（500 字内）
- 方案 PPT 素材（结构、图表、数据）
- 用于 8.16 初赛提交

### 第 9 项：Demo 演示（`demo/`）
**产出**：演示脚本 + 录屏视频
- 端到端跑一个「缺陷 → 修复 → 测试 → 发布 → 复盘」的完整案例
- 用于复赛/决赛现场演示

---

## 执行原则

1. **按编号顺序**逐项实现，每项完成后再进下一项（除非用户明确调整优先级）。
2. **文档先行，代码后置**：第 1-6 项是设计文档，第 7 项才转代码，避免过早陷入实现。
3. **每项都对齐评审权重**：优先保证 25% 的三块（Agent Identity / PDCA 闭环 / Skill 清单）。
4. **参考资料不动**：`references/` 保持只读参考，自写产出进 `agents/` `design/` `skills/` `src/` `demo/`。

---

## 进度快照（2026-08-06）

**已完成：**
- 第 1 项：Agent Identity 清单 → `agents/AGENT-IDENTITY.md`（6 个研发 Agent + 动态团队机制 + 里程碑握手协议）
  - **已按用户要求标注**：6 个角色非重点，只作默认团队模板，重点在调度 loop / 动态团队 / PDCA 闭环
- 方案 B 调研 → `design/OPENCLAW-VS-QWENPAW.md`（基于 AgentScope 写 Manager loop + QwenPaw 接入 AgentTeams）
- **Manager Loop 设计** → `design/MANAGER-LOOP-DESIGN.md`（深入 AgentScope `Agent.reply` 主循环实证，设计"调度 ReAct"，8-9 个调度工具映射 AgentTeams，复用原生 HITL 做异步派单，中间件落点 Trace/Metrics/权限审计）。代码实现放第 7 项。
- **第 2 项：PDCA 闭环状态机** → `design/PDCA-CLOSED-LOOP.md`（官方 8 环节映射 8 主状态 + 里程碑握手 + 验证闸门 + 回滚 + 与 Manager Loop 衔接）

- **AgentTeams 落地运行手册** → `design/AGENTTEAMS-RUNBOOK.md`（2026-08-12，回答"怎么让 agent loop 跑起来"：环境自查→一键/非交互安装→登录→创建 Worker→派任务→命令行全流程→验证清单→故障排查（含版本错位坑）→与参赛方案衔接）。本文与 `AGENTTEAMS-INTERNALS.md`（机制）互补，重"动手跑"。

**已完成（2026-08-12 续）：**
- **第 3 项：Skill 清单** → `skills/SKILL-LIST.md` + 7 个 Skill（`skills/<name>/SKILL.md`）+ `skills/REGISTRY.md` + `skills/ASSIGNMENT-MATRIX.md`（三层 Skill 体系 L1 基座/L2 领域/L3 协同 + 官方 9 字段 + 注册表生命周期机制，详见当日记忆）
- **第 4 项：协同流程设计** → `design/COLLABORATION-DESIGN.md`（两级编排 Manager→TeamLeader→执行层；消息方向矩阵 + peerMentions 通信契约；`shared/tasks/{id}/` 上下文传递三铁律 + 完整流转示例；10 条防死锁规则）
- **第 5 项：可观测设计** → `design/OBSERVABILITY.md`（Trace+Log+Metrics 三类全覆盖，OTel 标准，task.id 贯穿，对齐 MAF observability.py；高于官方 1-2 类最低标准）
- **第 6 项：RAG/记忆方案** → `design/RAG-MEMORY.md`（共享状态 state.json + 知识库 RAG + Agent 两级记忆，官方"4 选 2"全覆盖）

**已完成（2026-08-13 续）：成员评价体系（贡献度 + 合格度）**
- 补齐动态团队缺的"HR 绩效系统"：量化评估 LLM 团队每个成员的「贡献了多少」和「合不合格」，为留任/培训/降级/裁员提供客观依据（此前只有"对产出物的验证闸门"，无"对成员本人"的评价）。
- 调研结论：贡献度归因借鉴 **C3**（arXiv:2603.06859，精确反事实、不删 agent）+ **SCG/SSV**（arXiv:2607.18255，语义 Shapley）；合格度对齐 **MAF `evaluate_workflow` 的 per-agent 评分**范式。
- 产出：
  - `design/AGENT-EVALUATION.md`（三层模型：合格度/贡献度/治理 + 六角色 KPI 表 + 计分公式 + AgentTeams 落地映射 + 评审亮点）
  - `src/loop/evaluation.py`（可运行评价器：`AgentScorecard`/`qualification_score`/`contribution_score`/`score_team`，纯 Python 只依赖 state.py，可独立单测，已自检通过）
  - `src/loop/manager.py` 接入：闭环结束自动采集打回次数/耗时，输出团队评价报告（已 mock 模式验证：贡献分按里程碑必要度差异化，fixer 100 > tester 95 > rootcause/releaser 90 > aggregator 80 > retrospector 70）
- 核心设计原则：合格度**确定性优先**（不靠 LLM 自评，延续 Ralph 反压）；贡献度**不删 agent**（替换产出物做反事实，对齐 C3 对 agent-removal 的批评）；评价闭环反哺动态团队治理。

**已完成（2026-08-13 续）：企业绩效管理体系对标（KPI Benchmark）**
- 为成员评价体系补"真实大厂管理实践"背书：对标 **华为 PBC**（结果导向 + Win/Execute/Team 三维 + IDP + 末位淘汰）、**IBM Check-in**（持续评估/减负）、**Google OKR+GRAD**（目标/评估分离 + 影响力导向）、**BSC 平衡计分卡**（四维平衡）。
- 产出：`design/KPI-BENCHMARK.md`（对标映射总表 + 6 条增量增强建议 + 分角色 KPI 增量总表 + 评审亮点）。
- 增量落点：①合格度补「团队协作 + 个人成长」两维；②持续 Check-in + 目标/评估分离；③贡献度升级「影响力」三档；④治理层引入「学习成长」权重；⑤三向 360 反馈结构化；⑥评级强制分布校准。

**下一步（计划第 7 项）：AgentTeams 代码包** —— 把第 1-6 项设计转成 `src/` 下的 Worker/Team/Skill YAML 声明式资源（复赛可执行代码包核心）。

> 初赛临近（8.16 截止）：第 8 项初赛材料（500 字简介 + 方案 PPT）时间最紧，可优先推进。
