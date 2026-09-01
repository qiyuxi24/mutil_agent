# 赛道三 · 软件研发全流程协同

> GOAI 世界人工智能开源大赛 — Agent Infra（新智基座）赛道 · 方向三
> 赛事官网：https://www.goaihz.com/tracks

## 选题方向

围绕「缺陷/需求聚合 → 代码根因定位 → 修复方案生成与执行 → 测试验证与发布确认 → 复盘与知识沉淀」构建 **多 Agent 闭环**。

可参考场景：
- 多源缺陷/需求信息聚合与去重（Issue、日志、用户反馈）
- 代码缺陷自动定位与影响面分析
- 修复方案生成与自动化编码执行
- 测试验证与灰度发布结果确认
- 上线复盘与研发知识库沉淀

## 核心要求（开发必读）

1. **多 Agent 协同（硬性）**：至少 3 个不同职能的 Agent，每个有清晰身份定义；以 **AgentTeams（原名 Hiclaw）** 为协同设计基点；需提交 Agent Identity 清单（参赛手册附录A）；说明闭环：任务输入 → 任务拆解 → 上下文传递 → 工具调用 → 结果验证 → 执行证据沉淀 → 审批与回滚 → 经验沉淀
2. **Skill（必选）**：核心 Skill 清单（名称/用途/输入输出/调用条件/依赖工具/失败处理/安全边界/复用价值）
3. **MCP 与工具集成（推荐）**：MCP 推荐接入协议；未用 MCP 需给出等价契约
4. **可观测（推荐）**：Trace / Log / Metrics 至少 1-2 类
5. **RAG 与上下文增强（推荐）**：Agent 记忆存储 / 知识库 RAG / 共享状态管理 / 轨迹可观测 4 项至少实现 2 项
6. **工具链**：AgentTeams（必须）、云 Skills 门户、Nacos/Higress/PolarDB/RocketMQ/LoongSuite（推荐）

> **初赛完成度**：全部 6 项要求均已覆盖。多 Agent 协同（9 Worker PDCA 闭环：1 Leader + 8 职能，真实平台跑通）、Skill（14 个核心 + L1 基座）、MCP（8 个 MCP 工具注册 + 声明式生效）、可观测（LoongSuite 推理轨迹 + 审计日志）、RAG（三层记忆 + 语义检索 + 知识沉淀）、工具链（AgentTeams 原生 + UModel + LoongSuite）。

## 赛程与提交

| 阶段 | 时间 | 提交材料 |
|------|------|----------|
| 报名 | 7.16 起 | 报名信息 |
| 初赛 | 7.16–8.16 | ①作品简介(500字内) ②方案PPT ③(可选)可执行代码包 |
| 初赛评审 | 8.17–8.24 | 复赛名单 Top30 |
| 复赛 | 8.25–9.3 | ①更新版方案 ②AgentTeams 代码包 ③Demo/视频 |
| 决赛 | 9.22 | 路演PPT + 现场Demo + 代码仓库最终版 |

## 📖 操作手册

> **想立刻跑起来？** 双击根目录 **`启动-命令行.bat`**（官方 agt CLI + 派单）或 **`启动-Web端.bat`**（官方 Dashboard），或 `start.bat` 菜单选择。详见 **[OPERATIONS-GUIDE.md](./OPERATIONS-GUIDE.md)** —— 项目只有两个入口，点击即用。

## 初赛交付状态（2026-08-16）

> 初赛截止 8.16，当前所有 P0/P1/P2 项已完成，**207 例确定性测试全部通过**，12 例浏览器测试因未装 Playwright 自动跳过。

### 已完成的核心实验

| 实验 | 证据 | 说明 |
|------|------|------|
| **PDCA 闭环（Mock）** | `demo/e2e-log-20260815-final.txt` | 6/6 里程碑 + RETROSPECT_DONE + 审计 + 12 成绩单 |
| **PDCA 闭环（真实平台）** | `demo/e2e-log-20260815-final.txt` | 3/6 里程碑 LLM 驱动 + workers.yaml apply 成功 + 10 容器 Running |
| **委托模式降级** | `tests/test_delegated_fallback.py`（3 PASS） | 平台不可用时自动 fallback Mock，保证演示不翻车 |
| **动态团队「Leader 挑人」** | `tests/test_e2e_dynamic_hiring.py`（15 PASS） | 治理命令模拟器 + Leader 从一套班子按阶段挑人 → 组队 → 收尾归档完整生命周期 |
| **团队建站能力（MBTI 测评）** | `demo/mbti-site-e2e-*/`（2 批） | 从零建站：index.html + style.css + app.js，HTTP 200 验证通过 |
| **LoongSuite 推理轨迹观测** | `scripts/verify-loongsuite-traces.py`（PASS） | AgentScope Worker 推理轨迹导出到 Jaeger |
| **UModel 统一数据模型** | `scripts/verify-umodel-model.py`（PASS） | 9 entity_set + 9 link + 2 storage 模型包完整性 |
| **Team + Leader 两级组织** | `agt get teams` 确认 Active | 1 Leader + 8 Worker 组织进 rnd-team，真实平台验证通过 |

### 测试覆盖

```
demo\.venv\Scripts\python.exe -m pytest tests/ -q  →  207 passed, 12 skipped
```

> 核心确定性单测 + E2E（API 契约 / CLI 管道）+ 浏览器 12（未装 Playwright 时跳过，共 219 项收集）。**请用 `demo\.venv` 跑**，系统 Python 缺 pytest-asyncio 会收集失败。

| 模块 | 用例数 | 说明 |
|------|--------|------|
| test_state.py | 9 | PDCA 状态机正向流转 + 打回 |
| test_evaluation.py | 21 | 三层评价模型（合格度/贡献度/成长分/治理） |
| test_audit_logger.py | 6 | 结构化审计日志读写 |
| test_checkpoint.py | 9 | TaskCheckpoint/UUID/轮询/断点续传 |
| test_pdca_closure.py | 4 | Mock 完整闭环（RETROSPECT/state.json/审计/成绩单） |
| test_agent_bus.py | 12 | AgentBus channelPolicy + EventBus 订阅/广播 |
| test_approval.py | 9 | 审批留痕闭环 + TTL 超时兜底 |
| test_context_budget.py | 12 | TokenEstimator/DynamicBudgetAllocator |
| test_toolchains.py | 11 | 代码扫描/测试闸门确定性内核 |
| test_delegated_fallback.py | 3 | 委托模式降级策略 |
| test_e2e_dynamic_hiring.py | 15 | 一套班子 + Leader 挑人/组队/归档生命周期 |
| test_memory_registry.py | 10 | 统一可复用记忆系统（AgentMemoryRegistry） |
| test_team_comm.py | 7 | 员工间通信（Tester→Backend 要日志） |
| test_task_route.py | 9 | create_task 统一 Leader 编排一套班子 |
| test_knowledge_tracker.py | 21 | 知识复用统计 + 成长分链路 |
| test_system_assembly.py | 8 | 系统装配集成冒烟 |

## 评审权重

- 场景价值与行业可复制性 **25%**
- 多 Agent 协同与自主闭环能力 **25%**
- Skill 工程体系与生态复用 **25%**
- 工程落地、运行验证与安全可审计 **20%**
- 开放/开源贡献 **5%**

## 项目目录结构

```
software-dev-fullflow/
├── .gitignore
├── README.md            ← 本文件
├── PLAN.md              ← 项目总计划（9 项实施清单 + 进度）
├── TODO.md              ← 待办清单（唯一真相源）
├── GOAI-QA-ESSENTIALS.md ← GOAI 大赛 FAQ 精华 + 备赛决策
├── design/              ← 架构与闭环设计（含 EXPERIMENT-REVIEW.md 实验复盘）
├── skills/              ← 核心 Skill 清单（20+ 个：核心 + UModel + L1 基座 + agent-memory/team-comm，详见 SKILL-LIST.md）
├── agents/              ← Agent 身份定义（AGENT-IDENTITY.md + 一套完整班子索引卡）
├── src/                 ← 核心实现（AgentTeams 协同代码包，可运行）
├── tests/               ← 确定性测试（13+ 文件，ALL PASS + 12 skip）
├── scripts/             ← 部署/管理/验证脚本（19 个）
├── demo/                ← Demo 与演示脚本 + 初赛材料（PPT / 500字简介）
│   ├── mbti-site-e2e-*/ ← 团队建站能力验证产物（MBTI 测评网站）
│   ├── loongsuite/      ← LoongSuite 推理轨迹观测 demo
│   └── e2e-log-*.txt    ← 端到端闭环实验证据
├── references/          ← 参考资料集（第三方源码仓库 + 理论/学习文档，整体已被 gitignore），说明见 references/README.md
│   ├── refs/            ← AgentTeams / AgentScope / UnifiedModel 参考仓库
│   ├── agent-framework/ ← MAF 微软参考实现
│   ├── theory/          ← 理论依据（THEORY / THEORY-REFERENCE / FRAMEWORK-COMPARISON）
│   └── docs/            ← OFFICIAL-REQUIREMENTS / MAF-LEARNING-PATH
└── data/                ← 运行数据（已被 gitignore）

## 理论目录（references/theory/）

> 理论文档已随参考资料整体并入 `references/`（已被 gitignore）。原内容：
- `THEORY.md`：赛道特殊性分析 + 五大理论板块（需求缺陷/流程/质量/闭环/多Agent协作）+ 推荐的"PDCA 总纲 + 三条子原理"框架
- `THEORY-REFERENCE.md`：理论速查表，供写 PPT / 作品简介 / Agent Identity 时快速引用
- `FRAMEWORK-COMPARISON.md`：AgentTeams vs Microsoft Agent Framework 深度对比（架构/并发/核心代码定位/选型建议）

## 参考框架：Microsoft Agent Framework（references/agent-framework/）

本地已通过镜像拉取微软开源的多 Agent 工作流框架（源码约 4861 个文件，Python + .NET 双实现），源码位于 `references/agent-framework/`（已被 gitignore）。

**定位**：生产级 AI Agent 与多 Agent 工作流构建框架，核心是**图式工作流引擎**（graph-based workflow）。

**与赛道三高度契合的能力**：
- **多 Agent 编排**：顺序 / **并发** / 交接（handoff）/ 群组协作
- **图式工作流**：核心源码在 `python/packages/core/src/agent_framework/_workflows/`（`_workflow.py` / `_edge.py` / `_workflow_builder.py` / `_executor.py`）
- **Agent Skills**：领域知识/能力封装（`_skills.py`）
- **MCP 集成**：原生支持（`_mcp.py`），对接赛道"工具集成"
- **可观测**：内置 OpenTelemetry（`observability.py`）
- **声明式 Agent**：YAML 定义（`declarative-agents/`）
- **审批/工具授权**：`_harness/_tool_approval.py`，对应赛道"审批与回滚"

> 注意：本仓库通过 `ghfast.top` 镜像拉取（直连 github.com 不通）。官方最新仓库：https://github.com/microsoft/agent-framework
> 建议：AgentTeams 为参赛必须的协同基点，MAF 可作为参考实现/备选技术栈，两者需在方案中说明关系（兼容性/替代原因）。
>
> **参考资料汇总见 `references/README.md`**（含 AgentTeams/AgentScope/UnifiedModel/MAF 的来源、用途与拉取说明，整体已被 gitignore）。

## 统一数据模型：UModel（2026-08-15 已落地）

阿里官方 **UModel（Unified Model）** 是厂商中立的语义运行时，把分散的 schema/实体/关系/拓扑组织成 workspace-scoped 对象图，让 AI Agent 通过 `.umodel`/`.entity`/`.topo` 统一查询。本项目用它把共享状态与知识库的自定义 schema 收敛为统一对象图。

- **接入设计**：`design/UNIFIED-MODEL-INTEGRATION.md`
- **模型包**：`src/agentteams/umodel/`（9 实体 `entity_set` + 9 关系 `link` + 2 存储 `storage`，= PDCA 里程碑链对象图化）
- **技能**：`skills/umodel-query/`（全部 Worker 读统一语义层）+ `skills/umodel-rca/`（RootCause 模型引导根因分析）
- **自检通过**：`scripts/verify-umodel-model.py`（9 entity_set / 9 link / 2 storage，PASS）
- **官方仓库**：`references/refs/unified-model/`（已被 gitignore）
- （复赛）起 UModel 服务 + 导入模型包 + MCP 注册到 Higress

## Agent 推理轨迹观测：LoongSuite（2026-08-15 已验证）

阿里官方 **LoongSuite**（alibaba/loongsuite-python）是基于 OpenTelemetry 的 GenAI 可观测套件，提供对 **AgentScope**（我们 Agent 的底座）的自动插桩，捕获 Agent 推理的完整 span 树（`invoke_agent → react step → chat/execute_tool`），并带 `gen_ai.agent.name` / `gen_ai.operation.name` 等语义属性。已本地验证：模拟「研发 Worker」的 AgentScope Agent 推理轨迹成功导出到本地 Jaeger。

- **接入设计**：`design/LOONGSUITE-INTEGRATION.md`
- **Demo**：`demo/loongsuite/agentscope_worker_demo.py`（模拟研发 Worker 根因定位）
- **验证脚本**：`scripts/verify-loongsuite-traces.py`（跑 demo + 查 Jaeger，PASS）
- **两个坑**：auto-instrumentation 不自动发现 agentscope 需手动 `AgentScopeInstrumentor().instrument()`；bootstrap 破坏 `mcp.types` 绑定需手动补
- **对齐评审**：直接命中「可观测（全链路推理轨迹）」+「工程落地/安全可审计 20%」
- （复赛）落地到 AgentTeams Worker runtime + 跨 Agent 任务链路关联

## 动态团队组织：Team + Leader 一级协作（2026-08-16 重构）

在 AgentTeams 平台上将一套完整班子组织进 `rnd-team`（Team CR），由固定 `leader` 在 Team Room 内协调员工参与，支撑"Leader 按阶段挑人"叙事核心卖点。

- **Team CR**：`src/agentteams/team-rnd.yaml`（1 固定 Leader + 8 职能 Worker）
- **Leader**：`src/agentteams/workers.yaml`（leader Worker，role=team_leader）
- **验证**：`agt get teams -o json` 确认 teamRoomID / leaderDMRoomID 已创建
- **治理命令模拟**：`tests/test_e2e_dynamic_hiring.py`（15 PASS，retain/coach/fire/hire 闭环）
- **绩效评价反哺**：`run.py` 闭环后复用 `evaluation.score_team` 输出治理命令
- （复赛）方案 B：Manager→Leader→Worker 两级调度链路

## ⭐ 核心创新点：一套完整班子 + 固定 Leader 编排（2026-08-16 重构）

> **这是本作品区别于「固定角色流水线」的最大创新点**：团队是**一套完整班子**，由固定 **Leader（编排者）** 按阶段从班子里挑人参与，员工之间可互相通信（如测试向后端要日志），每个员工有可复用记忆系统。固定的是班子与流程，参与人员由 Leader 按需编排。

**为什么重构**：此前的「HR 双模式（修复/搭建）」割裂了两套班子，用户明确要求改为**一套班子**（产品经理、前端、后端、测试、运维、修理工等）+ **固定 Leader**。

**一套完整班子（Leader 按阶段挑人）**：

| 阶段 | 员工 | 角色 | 里程碑 |
|------|------|------|--------|
| P 计划 | @aggregator | 产品经理（需求/规格） | `TASK_SPEC_READY` |
| D 分析 | @rootcause | 架构师（根因+影响面） | `ROOT_CAUSE_FOUND` |
| D 编码 | @frontend / @backend / @fixer | 前端/后端/修理工 | `SITE_READY` / `BACKEND_READY` / `FIX_APPLIED` |
| C 检查 | @tester | 测试（质量门禁） | `TEST_PASSED` / `TEST_FAILED` |
| A 处置 | @releaser | 运维/DevOps（发布+部署） | `RELEASE_OK` / `RELEASE_ROLLED_BACK` |
| A 处置 | @retrospector | 复盘沉淀 | `RETROSPECT_DONE` |

**落地成果（2026-08-16，全部已实测/校验通过）**：
- **一套班子 Worker**：`src/agentteams/workers.yaml`（9 Worker：leader + 8 职能，删除 hr/architect/deployer/backend 独立 CR）
- **统一可复用记忆系统**：`AgentMemoryRegistry`（`src/loop/context/agent_memory.py`）+ `skills/agent-memory`（含 `memory_cli.py`），所有 Worker 统一挂载
- **员工间通信**：`AgentBus` request-reply（Tester→Backend 要日志）+ `skills/team-comm`（含 `comm_cli.py`），所有 Worker 统一挂载
- **文档生成**：`skills/doc-gen`（含 `scripts/docgen.py`）Markdown/HTML → Word(.docx)/PDF，中文字体/表格/代码块/页码，挂给 Leader/Aggregator/RootCause/Tester/Releaser/Retrospector 产出正式交付物（需求/设计/测试报告/发布说明/复盘报告）
- **状态机泛化**：`state.py` 支持 Leader 每阶段覆盖执行者（`executor_for`）+ 记录 `stage_participants`
- **真实运行验证**：tester/releaser 挂 `deploy-runtime`，真实 curl 静态页 200 + POST 通 + 数据落库
- **Leader 生命周期测试**：`tests/test_e2e_dynamic_hiring.py` 新增 Leader 挑人 → 组队 → 收尾归档（PASS）
- **回归锁**：`tests/test_memory_registry.py`（10）+ `test_team_comm.py`（7）+ `test_task_route.py`（9）

**演示叙事**：用户丢「搭一个带 POST 的官网」→ Leader 从班子挑 `aggregator + rootcause + frontend + backend + tester + releaser` → 员工接力 + 互相通信（Tester 向 Backend 要日志）→ 产出可访问站点（静态页 + 真 POST）→ Retrospector 复盘 → 全员 `agent-memory` 沉淀经验 → 下个项目 Leader 重新挑人。

**设计文档**：`design/TEAM-REFACTOR-SINGLE-BANCHANG.md`
