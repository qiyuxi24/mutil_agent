# mutil_agent — GOAI「软件研发全流程协同」多 Agent 系统

> 本仓库用于参赛 **GOAI 世界人工智能开源大赛 · 赛道一「新智基座 Agent Infra」· 方向三「软件研发全流程协同」**。
> 核心产物是 `software-dev-fullflow/` 子目录 —— 一个以 **AgentTeams（比赛官方协同基点）** 构建的「软件研发多 Agent 团队」系统，
> 把「缺陷/需求聚合 → 根因定位 → 修复 → 测试验证 → 发布确认 → 复盘沉淀」做成 **可验证、可回滚、可沉淀的 PDCA 闭环**。

---

## 一、这是什么 / 一句话定位

> 用 AgentTeams 的声明式能力，造一支「软件研发 Agent 团队」，把 **缺陷/需求聚合 → 根因定位 → 修复 → 测试验证 → 发布确认 → 复盘沉淀**
> 做成 **可验证、可回滚、可沉淀的 PDCA 闭环**。

- **赛道**：GOAI 大赛 · 赛道一「新智基座 Agent Infra」· 方向三「软件研发全流程协同」
- **协同基点**：AgentTeams（原名 Hiclaw，AgentScope 生态，阿里开源）——**比赛硬性要求，必须用它**
- **参考实现**：Microsoft Agent Framework（MAF）——用于提前实证跑通调度 loop（第三方参考，非参赛官方）

---

## 二、仓库当前情况（2026-08-13 快照）

### 2.1 仓库结构

```
mutil_agent/
├── README.md                    ← 本文件（项目总览）
├── LICENSE
└── software-dev-fullflow/       ← 项目主体（GOAI 赛道三参赛作品）
    ├── PLAN.md                  ← 项目总计划（9 项实施清单 + 进度快照）
    ├── GOAI-QA-ESSENTIALS.md    ← GOAI 大赛 FAQ 精华 + 备赛决策
    ├── README.md                ← 子项目 README（赛道介绍 + 评审权重）
    ├── .gitignore
    │
    ├── agents/                  ← Agent Identity 清单（6 个研发 Agent 定义）
    │   └── AGENT-IDENTITY.md
    │
    ├── design/                  ← 架构与闭环设计（第 1-6 项设计文档）
    │   ├── PDCA-CLOSED-LOOP.md       ← PDCA 闭环状态机（8 状态 + 6 里程碑 + 打回）
    │   ├── MANAGER-LOOP-DESIGN.md    ← Manager 调度 Loop 设计
    │   ├── COLLABORATION-DESIGN.md   ← 协同流程设计（两级编排 + 通信契约）
    │   ├── OBSERVABILITY.md          ← 可观测设计（Trace/Log/Metrics）
    │   ├── RAG-MEMORY.md             ← RAG/记忆方案（共享状态 + 知识库 + Agent 记忆）
    │   ├── AGENTTEAMS-INTERNALS.md   ← AgentTeams 内部机制梳理
    │   ├── AGENTTEAMS-RUNBOOK.md     ← AgentTeams 落地运行手册
    │   ├── SKILL-LIFECYCLE.md        ← Skill 生命周期设计
    │   ├── AGENT-EVALUATION.md       ← 成员评价体系（贡献度 + 合格度三层模型）
    │   └── OPENCLAW-VS-QWENPAW.md    ← 方案 B 调研（Manager loop 选型）
    │
    ├── skills/                  ← Skill 工程体系（赛道 25% 权重重点）
    │   ├── README.md                ← Skill 管理手册（对齐官方 AgentTeams 方式）
    │   ├── SKILL-LIST.md            ← Skill 清单主文档（官方 9 字段）
    │   ├── REGISTRY.md              ← Skill 注册表（发现层/Catalog）
    │   ├── ASSIGNMENT-MATRIX.md     ← Skill → Worker 分配真相源
    │   ├── manage-skill/            ← 管理 Skill（Manager 集中编排）
    │   ├── scripts/                 ← 官方 Skill 管理脚本（push-worker-skills / render / find）
    │   └── <7 个核心 Skill>/         ← 每个 Skill 一个目录（SKILL.md + scripts/references/assets）
    │       issue-parsing / root-cause-analysis / impact-analysis /
    │       code-gen / test-generation / release-gate / retrospective
    │
    ├── scripts/                 ← AgentTeams 部署 / 管理脚本
    │   ├── agentteams-install-patched.ps1  ← 官方安装补丁（修复 AS_TOKEN 缺失 bug）
    │   ├── reinstall-agentteams.ps1        ← 自动化重装
    │   └── README.md
    │
    ├── src/                     ← 可运行代码（PLAN 第 7 项落地）
    │   ├── run.py                   ← 研发团队调度 Loop 交互入口
    │   ├── loop/                    ← Manager 调度 Loop（MAF 底座参考实现）
    │   │   ├── state.py             ← PDCA 状态机 + 里程碑 + 打回
    │   │   ├── team.py              ← 6 个研发 Agent 角色定义
    │   │   ├── manager.py           ← Manager 调度循环（核心）
    │   │   ├── fixer_loop.py        ← Fixer 单 Agent 自我迭代引擎（Ralph 方法论）
    │   │   └── evaluation.py        ← 成员评价器（贡献度 + 合格度计分）
    │   ├── agentteams/              ← AgentTeams 声明式资源（比赛官方 CRD）
    │   │   ├── workers.yaml         ← 6 个 Worker CRD 声明
    │   │   └── workers/<name>/SOUL.md ← 每个 Worker 的 SOUL
    │   ├── AGENTTEAMS-MIGRATION.md  ← 从 MAF 迁移到 AgentTeams 的蓝图 + 进度
    │   └── data/                    ← 运行产物（gitignore）
    │
    ├── demo/                    ← Demo 与演示脚本（MAF 实证跑通）
    │   ├── maf_sequential_deepseek.py
    │   ├── maf_sequential_interactive.py
    │   ├── OFFICIAL-MAF-GUIDANCE.md
    │   └── README.md
    │
    └── references/              ← 参考资料集（第三方源码 + 学习文档，整体 gitignore）
        ├── refs/                ← AgentTeams / AgentScope / UnifiedModel 官方参考仓库
        ├── agent-framework/     ← MAF 微软参考实现（Python + .NET 双实现）
        ├── theory/              ← 理论依据（PDCA / 动态 Agent 团队 / 拆解 / 迭代）
        └── docs/                ← 官方要求 / 学习路径
```

### 2.2 当前进度（2026-08-13）

**✅ 已完成（设计文档）：**
- 理论框架 + 框架选型对比（AgentTeams vs MAF）
- **第 1 项**：Agent Identity 清单 → `agents/AGENT-IDENTITY.md`（6 个研发 Agent + 动态团队机制）
- **第 2 项**：PDCA 闭环状态机 → `design/PDCA-CLOSED-LOOP.md`
- **第 3 项**：Skill 清单 → `skills/`（7 个核心 Skill + 注册表 + 分配矩阵 + 管理 Skill）
- **第 4 项**：协同流程设计 → `design/COLLABORATION-DESIGN.md`
- **第 5 项**：可观测设计 → `design/OBSERVABILITY.md`
- **第 6 项**：RAG/记忆方案 → `design/RAG-MEMORY.md`
- **成员评价体系** → `design/AGENT-EVALUATION.md`（贡献度 + 合格度三层模型，反哺动态团队治理）
- AgentTeams 落地运行手册 → `design/AGENTTEAMS-RUNBOOK.md`

**✅ 已完成（可运行代码）：**
- **第 7 项（部分）**：`src/loop/`（MAF 底座参考实现）已可运行，可秒级 mock 演示完整 8 阶段闭环，也可调 DeepSeek 跑真实闭环
- **AgentTeams 已部署到本地 Docker**（补丁修复官方安装脚本缺失 token 的 bug）
- **6 个研发 Worker 已创建并全部 Running**（`src/agentteams/workers.yaml`，deepseek-v4-flash / copaw）
- **成员评价体系（贡献度 + 合格度）**：`design/AGENT-EVALUATION.md` 三层模型 + `src/loop/evaluation.py` 可运行评价器 + scorecard 落盘 + 治理命令（留任/培训/降级/裁员）
- **Fixer 单 Agent 自我迭代引擎**：`src/loop/fixer_loop.py`（Ralph 方法论：写完代码 → 自我校验 → 失败修正 → 再校验，减少打回）

**⏳ 进行中 / 待办：**
- 验证 Manager 驱动 6 个 Worker 在 AgentTeams 上跑通 PDCA 闭环（Element Web 发任务）
- 视评审需要补建 Team（用 team-leader-agent 模板）
- **第 8 项（初赛材料，时间最紧）**：500 字作品简介 + 方案 PPT（初赛 8.16 截止）
- **第 9 项**：Demo 演示脚本 + 视频（复赛/决赛）

> ⚠️ 初赛硬性节点 **8.16** 只剩几天：初赛**只需方案设计**（不强制真实部署），优先保证作品简介 + 方案 PPT。

---

## 三、核心设计

### 3.1 多 Agent 团队（6 个研发职能 Agent）

| Worker | 职能 | 真实研发角色 | 里程碑握手 |
|--------|------|-------------|-----------|
| aggregator 缺陷聚合员 | 多源缺陷/需求聚合去重、拆解任务规格 | 产品经理 + 缺陷管理 | TASK_SPEC_READY |
| rootcause 根因定位员 | 根因分析（RCA）+ 影响面分析 | 架构师 | ROOT_CAUSE_FOUND |
| fixer 修复工程师 | 生成并执行修复方案 | 前后端开发 | FIX_APPLIED |
| tester 测试验证员 | 质量门禁，客观 PASS/FAIL 判定 | 测试工程师 | TEST_PASSED / TEST_FAILED |
| releaser 发布确认员 | 灰度发布、审批、回滚 | 运维 / DevOps | RELEASE_OK / RELEASE_ROLLED_BACK |
| retrospector 复盘沉淀员 | 复盘 + 知识沉淀（RAG 复用） | 数据分析 + 知识沉淀 | RETROSPECT_DONE |

### 3.2 PDCA 闭环状态机（8 状态 + 6 里程碑 + 打回）

```
SPEC_INPUT → SPEC_DECOMPOSE → ROOT_CAUSE → FIX_APPLY → TEST_VERIFY → RELEASE → RELEASE_APPROVE → RETROSPECT
                                                                    │                        │
                                    TEST_FAILED / RELEASE_ROLLED_BACK └─────── 打回 FIX_APPLY（有次数上限防死循环）
```

**核心创新点（差异化卖点）：「AI 公司」式动态 Agent 团队**
> 不仅是"固定 6 个 Agent 跑流水线"，而是支持**按项目需求动态组建团队**——按需"招人"（招募新职能 Agent）、"裁员"（移除不需要的角色）、新 Agent 迅速与既有团队协作出结果。AgentTeams 原生支持无状态 Worker 声明式创建/销毁 + 技能加载，天然支撑这一机制。

### 3.3 Skill 工程体系（对齐官方 AgentTeams）

- Skill = 目录 + `SKILL.md`（frontmatter 必含 `name` + `description` + `assign_when`）+ 可选 `scripts/` / `references/` / `assets/`
- **Manager 集中管理**，Worker 通过 `Worker.spec.skills` 挂载（不能自己改 skills）
- 三层编排：`REGISTRY.md`（发现）→ `SKILL.md`（激活）→ `scripts/`（执行）
- 7 个核心工程 Skill + 管理 Skill + 3 层体系（L1 基座 / L2 领域 / L3 协同）

### 3.4 技术栈与底座

- **协同底座（比赛官方）**：AgentTeams（声明式 Worker/Team/Skill，Matrix 房间 + @mention 委派）
- **参考实现**：MAF（Microsoft Agent Framework）用于提前实证调度 loop
- **LLM**：DeepSeek（OpenAI 兼容协议，`deepseek-v4-flash`）
- **本地部署**：Docker（agentteams-controller / agentteams-manager）+ Element Web 聊天室

### 3.5 成员评价体系（贡献度 + 合格度）

> 为「动态团队」的"招人/裁员"提供客观依据，补齐此前只有"产物验证闸门"、没有"对成员本人评价"的缺口。

- **三层模型**：Layer1 合格度（确定性 KPI 优先）/ Layer2 贡献度（采纳分 + 替换基线反事实，不删 Agent）/ Layer3 治理评级（留任 / 培训 / 降级 / 裁员）
- **计分公式**：合格分 = 0.3×一次通过 + 0.25×完整 + 0.2×协议 + 0.15×时效 + 0.1×审计；贡献分 = 100×采纳×里程碑权重×打回惩罚；综合 = 0.6×合格 + 0.4×贡献
- **落地**：`design/AGENT-EVALUATION.md`（三层模型 + 六角色 KPI 表）+ `src/loop/evaluation.py`（可运行评价器）+ scorecard 落盘 + 治理命令映射 `agt update/delete worker`
- **设计原则**：合格度确定性优先（不靠 LLM 自评，延续 Ralph 反压）；贡献度不删 Agent（替换产出物做反事实，对齐 C3 / SCG 论文）

---

## 四、如何运行

### 4.1 快速演示研发团队调度 Loop（MAF 底座，秒级 mock，不调 API）

```powershell
cd software-dev-fullflow\src
..\demo\.venv\Scripts\python.exe run.py --mock "定位并修复用户列表加载慢的问题"
```

### 4.2 真实闭环（调 DeepSeek API）

```powershell
cd software-dev-fullflow\src
# 先确认 demo/.env 有有效 DEEPSEEK_API_KEY
..\demo\.venv\Scripts\python.exe run.py --stages 3 "登录接口并发下偶发 500"   # 只跑前 3 阶段
..\demo\.venv\Scripts\python.exe run.py "你的缺陷/需求描述"                    # 完整 8 阶段闭环
```

### 4.3 AgentTeams 环境（本地 Docker）

- 部署/重装脚本：`software-dev-fullflow/scripts/`（`agentteams-install-patched.ps1` / `reinstall-agentteams.ps1`）
- 落地运行手册：`software-dev-fullflow/design/AGENTTEAMS-RUNBOOK.md`
- Element Web：http://127.0.0.1:18088（admin / AgentTeams2026!）

---

## 五、评审权重对照

| 权重 | 赛道要求 | 本项目落地 |
|------|---------|-----------|
| 25% | 场景价值与行业可复制性 | 研发缺陷修复 PDCA 闭环，映射真实研发团队 6 角色，天然 B 端 |
| 25% | 多 Agent 协同与自主闭环 | 6 Agent + Manager 调度 Loop + PDCA 状态机 + 动态团队机制 |
| 25% | Skill 工程体系与生态复用 | 7 个核心 Skill + 注册表 + 分配矩阵 + 管理 Skill（官方 AgentTeams 方式） |
| 20% | 工程落地、运行验证与安全可审计 | 可运行代码 + 状态文件可审计 + 验证闸门 + 回滚 + AgentTeams 实跑 |
| 5%  | 开放/开源贡献 | 改造可贡献回 AgentTeams（优于 fork） |

---

## 六、关键文档索引

| 主题 | 文档 |
|------|------|
| 项目总计划 | `software-dev-fullflow/PLAN.md` |
| 备赛 FAQ | `software-dev-fullflow/GOAI-QA-ESSENTIALS.md` |
| 子项目 README | `software-dev-fullflow/README.md` |
| AgentTeams 迁移蓝图 | `software-dev-fullflow/src/AGENTTEAMS-MIGRATION.md` |
| Skill 管理手册 | `software-dev-fullflow/skills/README.md` |
| AgentTeams 运行手册 | `software-dev-fullflow/design/AGENTTEAMS-RUNBOOK.md` |
| 成员评价体系 | `software-dev-fullflow/design/AGENT-EVALUATION.md` |

---

## 七、重要提醒（防混淆）

- **"官方" = 比赛官方 AgentTeams（阿里开源）**，不是 Microsoft Agent Framework，也不是 IDE 的 skill 框架。
- **MAF 仅是参考实现**：用于提前实证调度 loop，参赛协同基点必须是 AgentTeams。
- `references/` 整体被 gitignore（第三方源码 + 学习笔记，不入库）。
- 当前主项目 = `software-dev-fullflow`（GOAI 赛道三）。
