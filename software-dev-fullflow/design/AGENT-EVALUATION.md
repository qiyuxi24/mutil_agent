# Agent 成员评价体系设计（贡献度 + 合格度）

> GOAI 大赛 · 赛道三「软件研发全流程协同」· 设计产出（第 7 项配套）
> 解决的问题：**如何量化评估 LLM 团队每个成员的「贡献了多少」和「合不合格」**，为「AI 公司」动态团队的**留任 / 培训 / 降级 / 裁员**提供客观依据。
> 对应评审权重：**工程落地、运行验证与安全可审计 20%** + **多 Agent 协同 25%**（动态团队治理闭环）。
> 日期：2026-08-13

---

## 0. 结论先行

> 现有系统只有**「对产出物的验证闸门」**（`_verify` 判 PASS/FAIL），**缺「对成员本人」的评价体系**。本设计补齐这一环，提出**三层评价模型**：

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3  治理（Governance） —— 分数 → 留任/培训/降级/裁员       │
│           对接 fire_worker / retire_trigger / 动态团队机制        │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2  贡献度（Contribution） —— 这个成员"贡献了多少"         │
│           借鉴 C3（精确反事实）+ SCG/SSV（语义 Shapley）          │
│           落地：采纳贡献分（轻量）+ 替换基线法（精确，可选）       │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1  合格度（Qualification） —— 这个成员"合不合格"          │
│           借鉴 MAF evaluate_workflow 的 per-agent 评分            │
│           落地：确定性闸门 KPI（客观，零额外 LLM 成本）           │
└─────────────────────────────────────────────────────────────────┘
```

**核心设计原则**（沿用 PDCA「Ralph 反压」思想）：
1. **合格度优先客观**：能确定性判定的（编译/测试/覆盖率/字段完整）**绝不交给 LLM 自评**；
2. **贡献度不删 Agent**：不用"删掉一个成员看结果变化"（会扭曲原团队结构，见 C3 论文的批评），改用**替换产出物为基线**的精确反事实；
3. **评价闭环**：分数喂给动态团队机制 → 决定留任/培训/降级/裁员 → 再反哺组织记忆（`shared/knowledge/`）。

---

## 1. 定位与现状缺口

### 1.1 我们已有的（零散，不成体系）

| 已有资产 | 现状 | 是不是"成员评价" |
|---------|------|----------------|
| `_verify` 验证闸门（`src/loop/manager.py`） | 对**阶段产物**判 PASS/FAIL | ❌ 只评产物，不评人 |
| `TaskState.milestones[]` | 记录 `verdict` / `detail` / `by`（谁做的） | ⚠️ 有原始信号，但**未聚合利用** |
| `TaskState.iterations` | 打回次数 | ⚠️ 流程计数，未归到成员 |
| 动态团队 `retire_trigger` | "绩效不达标"触发裁员 | ⚠️ **无量化标准** |
| `OBSERVABILITY.md` Metrics | `fix.pass_rate` / `rollback.count` / `reject.count` | ❌ 流程级，非成员级 |

### 1.2 缺口结论

> 我们缺的是**「成员成绩单」**：把 `_verify` 的 verdict、`milestones.by`、`iterations`、时延等**散落的原始信号，聚合成每个成员的「合格分 + 贡献分」**，并映射到治理动作。这正是"AI 公司"动态团队缺少的"HR 绩效系统"。

---

## 2. 调研：现有开源方案与论文怎么实现

> 调研分两路：**贡献度归因**（谁贡献了多少）来自前沿论文；**合格度评估**（谁合不合格）来自成熟工程框架。两路合并即我们的双层评价。

### 2.1 贡献度归因（Contribution / Credit Assignment）

| 来源 | 核心方法 | 对我们的启示 |
|------|---------|-------------|
| **C3**（*Exact Is Easier: Credit Assignment for Cooperative LLM Agents*, arXiv:2603.06859, 2026-03） | ①交互历史是**可观察文本的确定性函数**（无隐藏状态）→ 反事实可**精确恢复**；②**固定历史 + 在决策点采样替代动作**（不删 agent）；③ **leave-one-out 基线**（无参，不训练 critic）；④ 输出**无偏 per-decision advantage**。另给 3 个审计指标：`credit fidelity` / `within-group variance` / `inter-agent influence` | **不删成员**，改"替换该决策点产出为基线"；贡献 = 替换后最终结果的**因果差异**；给"评价本身可信度"的审计指标 |
| **SCG / SSV**（*Semantic Cooperative Games for Contribution Attribution in LLM-Based Multi-Agent Systems*, arXiv:2607.18255, 2026-05） | **语义合作博弈 + 语义 Shapley 值**；把语言流转建模为**语义超图**，单轨迹算法 **SLIC** 无需重跑 agent 子集即可算贡献；成本降 **93.3%**，与 Monte Carlo Shapley 高度一致 | **流水线场景可零重跑算贡献**：用"产出物被下游采纳的语义支持关系"近似 Shapley，避免 O(2ⁿ) 重跑 |
| **Shapley-Coop**（OpenReview 2025） | Shapley 值在软件工程模拟里做信用分配 | Shapley 是贡献归因的经典公平基准 |
| **Agent That Matters**（OpenReview 2026） | 多智能体贡献归因框架 | 贡献归因是 MAS 优化的关键前提 |

> **关键学术判断**（来自 C3）：传统"**移除一个 agent 看团队表现变化**"在多 Agent LLM 系统里会**扭曲测量对象**——因为删了 agent 就改变了团队结构/交互历史，测到的不是"该 agent 在原团队的真实贡献"。我们的贡献度设计**遵循这条批评**，用"替换产出物"而非"删除成员"。

### 2.2 合格度评估（Quality / Qualification）

| 来源 | 核心方法 | 对我们的启示 |
|------|---------|-------------|
| **MAF `evaluate_workflow`**（微软官方，最贴近工程） | 评估多 Agent 工作流，**返回每个子 agent 的单独得分**（`sub_results`）；`Evaluator` 协议三件套：`LocalEvaluator`（确定性检查：`keyword_check` / `tool_called_check`）+ `FoundryEvals`（云 LLM-as-judge，内置 20+ 评估器）+ 自定义 `@evaluator`（返回 bool/0-1 float/dict） | **直接抄"per-agent 打分"范式**：确定性检查当主裁判（对齐 Ralph 反压），LLM-judge 只做语义质量兜底 |
| **LLM-as-Judge**（MT-Bench / G-Eval 传统） | 用裁判模型打分，需 **rubric + 人工抽样 + 偏差检查** | 语义质量评估用 LLM-judge，但要配 rubric 且抽样校验，不盲信 |
| **Agent Arena / AgentEval**（开源） | ELO 两两对战排名 | 适合"选优/淘汰"场景，可作治理层的排序工具 |

### 2.3 横向对比（我们选什么）

| 维度 | C3 | SCG/SSV | MAF evaluate_workflow | **我们落地** |
|------|-----|---------|----------------------|-------------|
| 回答的问题 | 贡献多少 | 贡献多少 | 合不合格 | **两者都要** |
| 是否需要重跑 | 需采样替代动作 | 单轨迹零重跑 | 需跑一次 | 轻量零重跑 / 精确可选重跑 |
| 依赖 LLM 自评 | 否（leave-one-out 无参） | 否（语义图） | 部分（LLM-judge） | **合格度确定性优先，贡献度无 LLM 自评** |
| 复杂度 | 中 | 高（超图） | 低 | **低（轻量）/ 中（精确）** |

---

## 3. 我们的评价体系：三层模型

### 3.1 总体框架

```
一次任务闭环跑完（TaskState 落盘）
        │
        ▼
┌───────────────────────────────────────────────┐
│ 信号采集层（埋点，已有数据 + 少量新增）        │
│  verdict / detail / by / iterations / elapsed  │
│  + 确定性闸门结果（编译/测试/覆盖率/字段）     │
└───────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────┐
│ Layer 1 合格度 Qualification（客观为主）      │
│  每个角色 KPI → 0-100 分，三级评级            │
└───────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────┐
│ Layer 2 贡献度 Contribution（归因）            │
│  轻量：采纳贡献分（下游是否真的用了你的产出）  │
│  精确：替换基线法（C3 简化）/ 语义 Shapley     │
└───────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────┐
│ Layer 3 治理 Governance（分数 → 动作）         │
│  综合分 → 评级 → 留任/培训/降级/裁员           │
│  → 对接 fire_worker / retire_trigger          │
└───────────────────────────────────────────────┘
```

### 3.2 Layer 1：合格度（Qualification）——「合不合格」

> **核心：确定性优先，LLM-judge 兜底。** 每个角色有专属 KPI，数据来自验证闸门与确定性工具，**零额外 LLM 调用成本**。

**通用合格指标**（所有角色共享）：

| 指标 | 来源 | 权重 | 说明 |
|------|------|------|------|
| `一次通过率` | `_verify` verdict + `iterations` | 30% | 一次 PASS 满分，每多打回一次扣分 |
| `产出完整性` | 产出物非空 + 关键字段齐全 | 25% | 空输出直接判不合格（现有 `_verify` 已兜底） |
| `协议合规` | 是否发正确里程碑词 / 注册 state.json / 不制造噪音 @mention | 20% | 防死锁纪律（对齐 COLLABORATION-DESIGN） |
| `时效` | `elapsed` vs 角色期望时延 | 15% | 慢不一定不合格，但要可见 |
| `产出可审计` | 是否留痕（产物落盘 + 证据） | 10% | 安全可审计 20% 的成员侧体现 |

**分角色确定性 KPI**（差异化，客观）：

| 角色 | 专属合格信号（确定性工具产出） |
|------|------------------------------|
| Aggregator | 去重率、spec 字段完整（标题/描述/优先级/影响面）、格式规范校验 |
| RootCause | 根因确定性标注（**不确定必须显式注明**，未注明算不合格）、影响面覆盖清单 |
| Fixer | **编译 / 类型检查 / 静态分析通过**（Ralph 反压，不过不算合格） |
| Tester | 测试金字塔覆盖（单测→集成→E2E）、覆盖率阈值、测试报告完整性 |
| Releaser | 金丝雀健康检查结果、审批记录、回滚留痕 |
| Retrospector | 知识条目结构化（问题→根因→解法→验证 四要素齐全） |

**评级映射**（三级）：

| 合格分 | 评级 | 含义 |
|--------|------|------|
| ≥ 85 | ✅ 合格（Qualified） | 正常留任 |
| 60–84 | ⚠️ 待改进（Underperforming） | 触发"培训/换模型/换提示词" |
| < 60 | ❌ 不合格（Unqualified） | 触发"降级/裁员"候选 |

### 3.3 Layer 2：贡献度（Contribution）——「贡献了多少」

> **核心：不删 Agent，替换产出物做精确反事实。** 我们场景是**流水线（PDCA 链）**，比通用并行协作更易归因：每个成员的"决策点"就是它的**产出物**，对下游的影响链清晰。

**轻量方案（默认，零重跑）——采纳贡献分（Adoption Score）**：

```
贡献分(agent) = 产出被下游采纳度 × 里程碑推进权重 × 打回惩罚因子
```

- **下游采纳度**：下游 Worker 的产出里**引用/依赖了上游产出物的程度**（字段/token 命中、是否基于该产出继续工作）。语义 Shapley 的"支持关系"的轻量近似。
- **里程碑推进权重**：该成员负责的里程碑在整个闭环的**必要度**（缺了它就闭环断链）。流水线里每个里程碑都是必要环节，权重可设不同（如 Fixer 是核心生产环节，权重高）。
- **打回惩罚因子**：被打回次数越多，贡献分折扣越大（`1/(1+打回次数)`）。

**精确方案（可选，需重跑下游）——替换基线法（C3 简化）**：

```
贡献分(agent) = 最终闭环得分(真实产出) − 最终闭环得分(该 agent 产出替换为基线)
```

- **基线**可选：空产出 / 弱模型产出 / 该角色模板产出。
- 只替换**该 agent 一个决策点的产出**，保留完整历史与团队结构，**不删成员**（对齐 C3 对 agent-removal 的批评）。
- 流水线串行，替换一个 agent 只需重跑其**下游**，成本 O(下游长度)，远低于 Shapley 的 O(2ⁿ)。
- 对齐 C3 的 leave-one-out 思想：基线无需训练，直接"留出"该成员贡献看差异。

**贡献度审计指标**（借用 C3 三个诊断指标，保证评价本身可信）：

| 审计指标 | 含义 | 我们的落地 |
|---------|------|-----------|
| credit fidelity | 贡献分是否稳定可信 | 多次运行方差 / 轻量 vs 精确方案一致性 |
| within-group variance | 同角色多实例贡献是否均匀 | 判断是否"单点依赖某个实例" |
| inter-agent influence | 成员间相互影响 | 上游产出变化对下游的敏感度 |

### 3.4 Layer 3：治理（Governance）——「分数 → 动作」

```
综合分 = 0.6 × 合格分 + 0.4 × 贡献分
```

| 综合分 | 治理动作 | 对接机制 |
|--------|---------|---------|
| ≥ 85 | ✅ 留任（Retain） | 无操作，可能升权（更多任务/更多技能） |
| 60–84 | 🔧 培训（Coach） | 换模型 / 换 SOUL 提示词 / 增挂 Skill / 增加打回反馈 |
| < 60 且连续 N 任务 | 🔻 降级 / 裁员（Demote/Fire） | 触发 `retire_trigger` → `fire_worker`，先归档记忆再删 |
| 长期闲置 | 🛌 休眠 / 召回 | `Worker.spec.state: Sleeping`，需时重建 |

> **治理闭环**：裁掉的成员先走 `knowledge_export`（记忆归档）→ 反哺组织记忆 → 新招成员可检索复用。评价数据本身也进 `shared/knowledge/`，形成"越评越准"。

---

## 4. 六个角色的评价指标总表

| 角色 | 合格信号（客观） | 贡献信号 | 治理重点 |
|------|----------------|---------|---------|
| Aggregator | 去重率、spec 字段完整 | spec 被下游 RCA 采纳度 | 聚合质量差 → 下游全偏 |
| RootCause | 根因确定性标注、影响面覆盖 | 根因被 Fixer 采纳度 | 定位错 → 修复方向错 |
| Fixer | **编译/静态分析通过**、一次通过率 | 修复被 Tester 验证通过、PR 被采纳 | 核心生产环节，权重最高 |
| Tester | 测试金字塔覆盖、覆盖率 | 打回决策被采纳、漏测率 | 闸门失守 → 不合格代码流入发布 |
| Releaser | 金丝雀健康、审批留痕、回滚记录 | 发布成功率、回滚必要性 | 安全红线，回滚留痕审计 |
| Retrospector | 知识条目四要素结构化 | 知识被后续任务检索复用率 | 组织记忆质量 |

---

## 5. 计分模型（可计算公式）

### 5.1 合格分（Qualification Score）

```
Qual(agent) = 100 × [ 0.30 × once_pass
                    + 0.25 × completeness
                    + 0.20 × protocol
                    + 0.15 × timeliness
                    + 0.10 × auditability ]

once_pass   = 1 / (1 + reject_count)          # reject_count = 该成员被 _verify 打回次数
completeness= 1 if 产出非空且关键字段齐全 else 0
protocol    = 1 if 发对里程碑词 + 注册 state.json + 无噪音 else 按项扣分
timeliness  = max(0, 1 − (elapsed − expected)/expected)
auditability= 1 if 产物落盘 + 证据留痕 else 0
```

### 5.2 贡献分（Contribution Score）

```
# 轻量：采纳贡献分（默认）
Contrib(agent) = 100 × adoption × milestone_weight × reject_penalty

adoption        = 下游产出引用该 agent 产出的程度（语义支持关系的轻量近似）
milestone_weight= 该 agent 里程碑在闭环的必要度（默认聚合器0.8/定位0.9/修复1.0/测试0.95/发布0.9/复盘0.7）
reject_penalty  = 1 / (1 + reject_count)

# 精确：替换基线法（可选，需重跑下游）
Contrib(agent) = final_score(真实) − final_score(该 agent 产出替换为基线)
```

### 5.3 综合分（Overall Score）

```
Overall(agent) = 0.6 × Qual(agent) + 0.4 × Contrib(agent)
```

---

## 6. 与现有代码的接入（埋点位置）

现有 `src/loop/manager.py` 的 `run()` 已经在采集关键信号，**只需少量埋点 + 新增一个评价器**：

| 现有代码位置 | 已有信号 | 新增埋点 |
|-------------|---------|---------|
| `_verify()` 返回 `(verdict, detail)` | verdict / detail | 记录 `by`（执行者）+ reject_count |
| `run()` 内 `local_retry` | 打回次数 | 归到当前执行者 `by` |
| `run()` 内 `elapsed` | 阶段时延 | 归到执行者时效分 |
| `state.advance(..., by=executor)` | 谁推进的 | 已有 `by`，直接复用 |

**新增模块**：`src/loop/evaluation.py`（纯 Python，只依赖 `state.py`，不依赖 `agent_framework`，可独立单测）。

```
evaluation.py
├── AgentScorecard        # 单个成员的成绩单（合格分/贡献分/综合分/评级）
├── QualificationEvaluator # Layer 1：吃 verdict/reject/时延 → 合格分
├── ContributionScorer     # Layer 2：吃采纳度/里程碑权重/打回 → 贡献分
├── TeamEvaluation         # 聚合一次任务所有成员的成绩单
└── score_team(task_state) # 入口：TaskState → 团队评价报告
```

---

## 7. 与 AgentTeams 平台的落地映射

| 评价层 | AgentTeams 落地机制 |
|--------|-------------------|
| 信号采集 | 复用可观测（OBSERVABILITY.md）的 OTel Metrics + `shared/tasks/{id}/state.json` |
| 成员成绩单 | 落 `shared/agents/{name}/scorecard.json`（对齐 RAG-MEMORY.md 的 Agent 记忆目录） |
| 治理：培训 | `agt update worker --model/--soul-file/--skills`（换模型/提示词/技能） |
| 治理：裁员 | `agt delete worker` / `Worker.spec.state: Stopped`（先 `knowledge_export`） |
| 治理：召回 | `agt create worker` 挂载原配置（无状态 Worker 可重建） |
| 评价反哺 | 评价结论写 `shared/knowledge/`，供 RAG 检索（"越评越准"） |

---

## 8. 评审亮点（供 PPT/简介引用）

- **补齐动态团队的最后一块拼图**：从"能招人/裁员"升级为"**有依据地招人/裁员**"——用可量化的贡献分+合格分做治理决策，而非拍脑袋。
- **学术严谨**：贡献度设计遵循 **C3**（arXiv:2603.06859）"不删 agent、精确反事实"的批评与 **SCG/SSV**（arXiv:2607.18255）"零重跑语义 Shapley"；合格度对齐 **MAF `evaluate_workflow` 的 per-agent 评分**范式。
- **客观优先**：合格度以**确定性闸门**为主裁判（编译/测试/覆盖率），LLM-judge 只兜底语义质量，不依赖 Agent 自评（延续 Ralph 反压思想）。
- **可落地**：零额外 LLM 成本的轻量方案可直接跑；精确方案（替换基线法）作为可选项，成本 O(下游长度) 远低于 Shapley O(2ⁿ)。
- **闭环可量化**：评价数据进入 `shared/knowledge/` + OTel Metrics，让"团队是否健康"有数据证据，命中"工程落地 20% + 多Agent协同 25%"。

---

## 9. 相关文档索引

- **企业绩效管理体系对标（华为 PBC / IBM Check-in / Google OKR+GRAD / BSC）**：`KPI-BENCHMARK.md`（本文档的权威背书 + 增量增强）
- 总体计划：`../PLAN.md`
- PDCA 闭环（验证闸门/回滚）：`PDCA-CLOSED-LOOP.md`
- Manager Loop（`_verify` 裁判 + 调度工具）：`MANAGER-LOOP-DESIGN.md`
- 动态团队（招聘/裁员机制）：`../agents/AGENT-IDENTITY.md` + `../references/theory/DYNAMIC-AGENT-TEAM.md`
- 可观测（Metrics 采集源）：`OBSERVABILITY.md`
- RAG/记忆（成员成绩单落点）：`RAG-MEMORY.md`
- 代码骨架：`../src/loop/evaluation.py`
- 论文原文：C3 `arXiv:2603.06859`、SCG/SSV `arXiv:2607.18255`、Shapley-Coop（OpenReview）、Agent That Matters（OpenReview）
- MAF 评估：`https://learn.microsoft.com/en-us/agent-framework/agents/evaluation`
