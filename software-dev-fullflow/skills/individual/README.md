# 个体 Agent 工程纪律层（individual）

> GOAI · 赛道三「软件研发全流程协同」· Skill 工程体系 —— **个体 Agent（干活的 Worker）通用工程纪律层**
> 定位：介于 **L1 基座（工具）** 与 **L2 领域（能力）** 之间的一层，**跨角色复用**，回答「个体 Agent 怎么把一件事**做对、做好**」。
> 依据：`mattpocock/skills`（TypeScript 大佬 Matt Pocock 的工程级 skills，已拉取到仓库根 `mattpocock-skills/` 供借鉴）+ `references/theory/SINGLE-AGENT-ITERATION.md`（Ralph）+ `CONTEXT-ENGINEERING.md`。
> 更新日期：2026-08-13

---

## 一、为什么要有这一层（现状缺口分析）

现有 `skills/` 是**「流程/领域」视角**：L2 领域层 7 个 skill 按 PDCA 闭环切分，每个绑定一个具体角色（`issue-parsing`→Aggregator、`code-gen`→Fixer…）；L1 基座层 5 个是「工具类」原子 skill。它们回答了 **「个体 Agent 干什么、用什么工具」**。

**但缺一层回答「个体 Agent 怎么把活干好」的通用工程纪律** —— 这些纪律**不分技术栈、不分角色**，是任何一个干活的 Worker（Fixer / Tester / RootCause / Releaser…）都该有的素养：

| 通用纪律 | 谁都要用 | 现有体系里有没有 |
|---------|---------|----------------|
| 开工前把需求/目标想清楚（对齐） | 全员 | ❌ 只有 `issue-parsing` 归 Aggregator |
| 写代码用红绿重构（TDD） | Fixer | ❌ `test-generation` 归 Tester，是"验证"不是"写代码纪律" |
| 出问题纪律化诊断 | RootCause/Fixer | ⚠️ 只有 `root-cause-analysis`，缺"反馈环"方法论 |
| 交付前双轴评审 | 全员 | ❌ 无 |
| 深模块/接口设计 | Fixer | ❌ 无 |
| 共享领域语言（CONTEXT.md） | 全员 | ❌ 无 |
| 交接文档 | 全员 | ⚠️ 只有 @mention + 里程碑词 |
| 上下文卫生（卸载/压缩/渐进披露） | 全员 | ⚠️ 理论有，没固化成 skill |

> 这一层借鉴自 **Matt Pocock `mattpocock/skills`**（口号 "Skills For Real Engineers — not vibe coding"）。他把自己每天的工程习惯封装成可组合 skill，核心方法论：**对齐（grilling）、反馈（tdd）、架构（deep modules）**。

---

## 二、个体 Agent「能用什么」全景（资产分析结论）

一个干活的个体 Agent，其可用资产由 **6 个维度** 拼成：

```
┌──────────────────────────────────────────────────────────────┐
│ ① 身份层  agents/AGENT-IDENTITY.md                           │
│    soul(人格) + agents(工作准则) + permissions + milestones  │
│    → 我是谁、边界在哪、什么时候交棒                            │
├──────────────────────────────────────────────────────────────┤
│ ② 领域能力  skills/ L2 领域层（7 个，绑定角色）                │
│    issue-parsing / root-cause-analysis / code-gen / …         │
│    → 我这个角色「干什么」（本职能力）                           │
├──────────────────────────────────────────────────────────────┤
│ ③ 基座工具  skills/ L1 基座层（6 个，跨角色）                  │
│    git-operations / code-search / repo-context /              │
│    knowledge-rag / evidence-log                               │
│    → 「用什么工具」                                           │
├──────────────────────────────────────────────────────────────┤
│ ④ 工程纪律  skills/individual/ 本层（跨角色，新增）            │
│    对齐/构建/诊断/评审/交付/上下文 6 类 9 个 skill             │
│    → 「怎么把活干好」（通用工程素养）                          │
├──────────────────────────────────────────────────────────────┤
│ ⑤ 自我迭代  references/theory/SINGLE-AGENT-ITERATION.md      │
│    Ralph 五理念：单任务聚焦/Spec驱动/子代理/反压校验/持续调优  │
│    → 「怎么自主收敛不失控」                                   │
├──────────────────────────────────────────────────────────────┤
│ ⑥ 上下文治理 references/theory/CONTEXT-ENGINEERING.md        │
│    信息卸载/压缩/渐进披露/注意力操纵/token 预算                │
│    → 「怎么管上下文窗口」                                     │
└──────────────────────────────────────────────────────────────┘
```

**本层（④）补的是缺口**：把 ⑤⑥ 的「理论」和 Matt Pocock 的「习惯」固化成可挂载、可执行的 skill，与 ②③ 平级，供任意 Worker 组合使用。

---

## 三、分类体系（6 类 9 skill，按个体 Agent 工作时序）

按「个体工程师干一件活的时间线」分门别类：

| 类 | 目录 | 回答 | Skill |
|----|------|------|-------|
| **align 对齐** | `align/` | 开工前把需求想清楚 | `grill-me`、`domain-modeling` |
| **build 构建** | `build/` | 写代码时的纪律 | `tdd`、`codebase-design` |
| **diagnose 诊断** | `diagnose/` | 出问题怎么查 | `diagnosing-bugs` |
| **review 评审** | `review/` | 交付前把关 | `code-review` |
| **deliver 交付** | `deliver/` | 跨 agent 交接 | `handoff`、`writing-for-agents` |
| **context 上下文** | `context/` | 长期不失控 | `context-hygiene` |

```
align ──▶ build ──▶ diagnose ──▶ review ──▶ deliver ──▶ context
(想清楚)  (写对)     (查出来)     (把关)      (交接)       (沉淀/卫生)
   ▲                                                        │
   └────────────────────────────────────────────────────────┘
        context-hygiene 的经验回流到下一轮 align/domain-modeling
```

> 每个 skill 都是**独立可组合**的：一个 Worker 可以只挂 `tdd`+`code-review`（Fixer），或只挂 `diagnosing-bugs`（RootCause），或只挂 `handoff`（全员）。

---

## 四、与现有 L1/L2/L3 的关系（不重复、不冲突）

| 层 | 定位 | 本层关系 |
|----|------|---------|
| L0 工程层 `manage-skill` | Manager 编排 skill 生命周期 | 本层 skill 同样被其管理 |
| L1 基座层（工具） | 「用什么」 | 本层 skill **依赖** L1（如 `tdd` 用 `code-search` 定位 seam） |
| **本层（工程纪律）** | 「怎么干好」 | ← 新增，跨角色复用 |
| L2 领域层（能力） | 「干什么」 | 本层被 L2 **引用**（如 `code-gen` 内嵌 `tdd` 纪律） |
| L3 协同层 `collaboration-loop` | Manager 调度闭环 | 本层只管个体，不碰调度 |

**一句话**：L1 给工具，L2 给本职，**individual 给素养**，L3 给调度。四层叠加，个体 Agent 才从「能干活」变成「会干活」。

---

## 五、Skill 格式（对齐比赛官方 AgentTeams）

每个 skill 一个目录 + `SKILL.md`，frontmatter **必须**三字段（官方 Worker 版规范）：

```yaml
---
name: tdd                      # ^[a-z0-9][a-z0-9-]*$
description: <一句话 + 触发词>   # 路由依据
assign_when: <什么样的 Worker 应拥有>  # Manager 自动分配依据
---
```

正文用命令式（动词开头）写 SOP + Gotchas。与 Matt Pocock 版（只有 `name`+`description`）的差异：**我们补 `assign_when` 才能挂到 AgentTeams Worker**。

---

## 六、挂载方式（复用官方脚本）

```bash
# 给任意 Worker 追加个体纪律 skill
bash skills/scripts/push-worker-skills.sh --worker fixer-go --add-skill tdd
bash skills/scripts/push-worker-skills.sh --worker fixer-go --add-skill code-review

# 全员必备的两条（交接 + 上下文卫生）
bash skills/scripts/push-worker-skills.sh --skill handoff
bash skills/scripts/push-worker-skills.sh --skill context-hygiene
```

> 分配建议见 `skills/ASSIGNMENT-MATRIX.md` 的「个体工程纪律层」追加节。

---

## 七、Matt Pocock 理念 → 本层映射

| Matt Pocock skill | 核心理念 | 本层落点 |
|------------------|---------|---------|
| `grill-me` / `grilling` | 开工前拷问需求，消除对齐偏差 | `align/grill-me` |
| `domain-modeling` | 建 `CONTEXT.md` 共享领域语言，压缩冗余 | `align/domain-modeling` |
| `tdd` | 红绿重构、只测公共 seam、反同义反复 | `build/tdd` |
| `codebase-design` | 深模块（大行为藏小接口）、seam/leverage/locality | `build/codebase-design` |
| `diagnosing-bugs` | 先建"会变红的反馈环"再谈假设，分 6 阶段 | `diagnose/diagnosing-bugs` |
| `code-review` | 双轴评审（Standards/Spec）并行子代理 | `review/code-review` |
| `handoff` | 把会话压缩成交接文档 | `deliver/handoff` |
| `writing-for-agents` | 渐进披露、context pointer、leading word | `deliver/writing-for-agents` |
| （隐含）上下文卸载/压缩 | 信息卸载 + 按需检索 | `context/context-hygiene` |

> 理念提炼已同步进 `references/theory/INDIVIDUAL-ENGINEERING-DISCIPLINES.md`。

---

## 八、文档索引

- 本层各 skill：`align/` `build/` `diagnose/` `review/` `deliver/` `context/` 下各 `SKILL.md`
- 理念提炼：`references/theory/INDIVIDUAL-ENGINEERING-DISCIPLINES.md`
- 自我迭代理论：`references/theory/SINGLE-AGENT-ITERATION.md`
- 上下文工程：`references/theory/CONTEXT-ENGINEERING.md`
- 现有 Skill 体系：`../SKILL-LIST.md`、`../REGISTRY.md`、`../ASSIGNMENT-MATRIX.md`
- 借鉴原仓库：`mattpocock-skills/`（仓库根，git 未跟踪，仅参考）
