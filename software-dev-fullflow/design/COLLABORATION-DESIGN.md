# 协同流程设计（COLLABORATION-DESIGN）

> GOAI 大赛 · 赛道三「软件研发全流程协同」· 第 4 项核心产出
> 对应官方要求：**多 Agent 协同**（角色编排 / 任务拆解 / 上下文传递 / 状态追踪），多 Agent 协同 25% 权重。
> 本文件回答三个问题：**研发团队怎么组织（Team 结构）？谁能跟谁说话（通信契约）？任务上下文怎么传递（上下文机制）？**
> 与前几项衔接：①Agent Identity（谁）→ ②PDCA 闭环（流程到哪）→ ③Skill（怎么做）→ **④本文件（怎么组织/通信/传上下文）**。
> 日期：2026-08-12

---

## 0. 一句话定位

> 把「第 1 项的 6 个 Agent + 第 2 项的 PDCA 闭环」组织成一个**可运营的研发团队**：定清楚**层级结构**、**谁能 @mention 谁**、**任务与状态在哪些共享文件里流转**，并用**防死锁规则**保证闭环不卡住。

---

## 一、Team 结构：两级编排，三层角色

借鉴 AgentTeams 的「Manager → Team Leader → Workers」委派边界（详见 `AGENTTEAMS-INTERNALS.md` §2.2），我们的研发团队采用**两级编排**：

```
┌────────────────────────────────────────────────────────────┐
│  编排层（1 个 Manager = AI 管家，不干具体活）                   │
│  Manager ── 全局调度：招/裁 Worker、派单、催进度、审批、复盘归档   │
└───────────────────────────┬────────────────────────────────┘
                            │ 只对接 Leader（委派边界，防瓶颈）
┌───────────────────────────▼────────────────────────────────┐
│  团队层（1 个 Team Leader = 项目经理，管一组 Worker）            │
│  TeamLeader ── 任务拆解、里程碑判断、把子任务派给对应 Worker      │
└───────────────────────────┬────────────────────────────────┘
        ┌───────────┬───────┼────────┬───────────┐
        ▼           ▼       ▼        ▼           ▼
┌────────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────────┐
│ Aggregator │ │RootCause│ │ Fixer  │ │ Tester │ │  Releaser  │
│ 缺陷聚合(P) │ │根因定位(D)│ │修复(D)  │ │验证(C)  │ │  发布(A)   │
└────────────┘ └────────┘ └────────┘ └────────┘ └────────────┘
        └──────────┬──────────────────────────┘
                   ▼
            ┌────────────┐
            │Retrospector│ 复盘沉淀(A) —— 贯穿各阶段，最终收尾
            └────────────┘
```

### 1.1 三层角色职责

| 层 | 角色 | 职责 | 是否干具体活 | 对应真实团队 |
|----|------|------|-----------|-------------|
| **编排层** | Manager | 全局调度：招/裁 Worker、派单、催进度、审批、归档 | 否（只调度） | 研发总监 / 项目经理之上 |
| **团队层** | Team Leader | 任务拆解、里程碑判断、把子任务派给 Worker | 否（只拆解派活） | 项目经理 |
| **执行层** | Aggregator/RootCause/Fixer/Tester/Releaser/Retrospector | 干 PDCA 闭环的具体活 | 是 | 产品/架构/开发/测试/运维/复盘 |

> **关键设计（防瓶颈）**：Manager 不直接管理 6 个 Worker，**只对接 Team Leader**。团队内部的分工、派活、催进度由 Leader 负责。这样 Manager 不会被 6 路 Worker 的消息淹没，对应 AgentTeams 的「Manager 不穿透 Team」设计。

### 1.2 动态团队下的 Team 结构（创新点落地）

- **固定骨架**：Team Leader + Aggregator + Tester + Releaser + Retrospector（闭环主链路，始终在岗）。
- **弹性弹性**：RootCause、Fixer 按技术栈/模块动态招多个实例（多个 Fixer 并行修不同缺陷）。
- **临时角色**：跨领域任务临时招「安全/性能/策划」Agent，任务结束即裁（经验沉淀进知识库后召回可重建）。
- **Team 结构与动态**：见 `agents/AGENT-IDENTITY.md` §2（招聘/裁员/注册机制）——本文件的 Team 结构是「默认模板」，动态团队在此基础上增删 Worker。

---

## 二、通信契约：谁能 @mention 谁（映射 channelPolicy）

> 通信契约定义「消息路由边界」，对应 AgentTeams 的 `channelPolicy` / peer-mentions 机制。它决定**谁能唤醒谁**，避免越权指挥、避免信息泛滥。

### 2.1 消息方向矩阵

| 发信者 \ 收信者 | Manager | TeamLeader | Aggregator | RootCause | Fixer | Tester | Releaser | Retrospector |
|---|---|---|---|---|---|---|---|---|
| **Manager** | — | ✅ 派单/催/审批 | — | — | — | — | ✅ 发布审批 | — |
| **TeamLeader** | ✅ 汇报 | — | ✅ 派 P 阶段 | ✅ 派 D 阶段 | ✅ 派 D 阶段 | ✅ 派 C 阶段 | ✅ 派 A 阶段 | ✅ 派复盘 |
| **Aggregator** | — | ✅ 完成汇报 | — | ✅ 交接 spec | — | — | — | — |
| **RootCause** | — | ✅ 完成汇报 | — | — | ✅ 交接根因 | — | — | — |
| **Fixer** | — | ✅ 完成汇报 | — | — | — | ✅ 交接修复 | — | — |
| **Tester** | — | ✅ 完成/打回汇报 | — | — | ✅ TEST_FAILED 打回 | — | ✅ TEST_PASSED 交接 | — |
| **Releaser** | — | ✅ 完成/回滚汇报 | — | — | ✅ 回滚打回 | — | — | ✅ RELEASE_OK 交接 |
| **Retrospector** | ✅ 复盘归档 | ✅ 完成汇报 | — | — | — | — | — | — |

### 2.2 核心路由规则

1. **纵向汇报**：执行层 Worker 完成本职后，**只向 TeamLeader 汇报**（不是 Manager）——防止 6 路 Worker 直接轰炸 Manager。
2. **横向交接**：执行层 Worker 之间**只在"有里程碑交接"时 @mention 下一个 Worker**（spec→根因→修复→测试→发布→复盘），这是 PDCA 闭环的推进动力。
3. **打回专用边**：`TEST_FAILED`（Tester→Fixer）、`RELEASE_ROLLED_BACK`（Releaser→Fixer）是**跨层横向打回**，是闭环允许的"回流边"。
4. **审批专用边**：只有 Manager 能触发**发布审批**（`RELEASE_APPROVE`），保证发布权集中。
5. **Manager 不与执行层 Worker 直接通信**（除审批 Releaser 外）——保持委派边界。

### 2.3 在 AgentTeams 的落地（channelPolicy / peer-mentions）

- **Team 级**：Leader Room（Manager+Leader）、Team Room（Leader+所有 Worker）、Worker Room（Leader+单个 Worker）——用 AgentTeams 的 Team CRD 自动生成。
- **Worker 级**：`Worker.spec.channelPolicy.peerMentions` 限制"能唤醒谁"：
  ```yaml
  # 例：Fixer 只被 Leader / Tester / Releaser 唤醒，也只主动找它们
  channelPolicy:
    peerMentions:
      receive: [team-leader, tester, releaser]
      send:    [team-leader, tester]
  ```
- **权限隔离**：Worker 只能在自己的房间 + 授权的 peer 之间通信，不能越权指挥别的 Worker 的专属任务。

---

## 三、上下文传递机制：共享文件 + 里程碑

> 上下文传递是闭环的「记忆载体」。借鉴 AgentTeams 的 MinIO `shared/` 共享文件系统（见 `AGENTTEAMS-INTERNALS.md` §6），任务上下文**不在 IM 消息里长篇传递**（防上下文膨胀），而是**落在共享文件，Agent 之间只传"文件引用 + 里程碑词"**。

### 3.1 共享文件目录约定

```
shared/
├── inbox/                    # 多源缺陷/需求入口（Aggregator 读）
├── tasks/{task-id}/          # ★ 单个任务全生命周期（闭环核心）
│   ├── spec.md               # 任务规格（Aggregator 写，只读给下游）
│   ├── base/                 # 参考文件（只读）
│   ├── root-cause.md         # 根因定位报告（RootCause 写）
│   ├── plan.md               # 修复计划（Fixer 写）
│   ├── fix/                  # 代码改动（Fixer 写）
│   ├── test-report.md        # 测试报告（Tester 写）
│   ├── release-report.md     # 发布报告（Releaser 写）
│   ├── state.json            # ★ 状态机：当前状态 + 里程碑进度（谁推进谁写）
│   └── result.md             # 最终结果汇总
├── knowledge/                # 共享知识库（Retrospector 写，RAG 检索）
│   └── {entry-id}.md         # 结构化经验：问题→根因→解法→验证
└── meta.json                 # 任务元数据（状态/房间/负责人）
```

### 3.2 上下文传递的三条铁律（对齐 CONTEXT-ENGINEERING「信息卸载」）

1. **产物落文件，消息传引用**：Worker 完成产出后，把**完整内容写进 `shared/tasks/{id}/xxx.md`**，IM 消息里只 @mention 下一个 Agent 并附**文件路径 + 里程碑词**，不贴全文。
2. **状态存 `state.json`，靠里程碑推进**：当前进度由 `state.json` 记录（谁推进谁写），Manager/Leader 读它判断"该派谁/催谁"，不靠聊天记录推断。
3. **复盘沉淀到 `shared/knowledge/`**：闭环完成后经验入库，供 RAG 检索（对接第 6 项 RAG/记忆方案）。

### 3.3 一个任务的完整上下文流转示例

```
1. 缺陷进 inbox/ → Aggregator 聚合去重 → 写 tasks/{id}/spec.md → @Leader 发 TASK_SPEC_READY
2. Leader 读 state.json 判断 → 派 RootCause → 写 state.json(ROOT_CAUSE)
3. RootCause 读 spec.md → 写 root-cause.md → @Leader 发 ROOT_CAUSE_FOUND
4. Leader 派 Fixer → Fixer 读 root-cause.md → 写 fix/ + plan.md → @Leader 发 FIX_APPLIED
5. Leader 派 Tester → Tester 读 fix/ → 写 test-report.md → @Leader 发 TEST_PASSED（或打回 Fixer）
6. Leader 派 Releaser → Releaser 读 test-report.md → 写 release-report.md → @Manager 发 RELEASE_OK（审批）
7. Manager 审批通过 → Leader 派 Retrospector → 读全流程 → 写 knowledge/{id}.md → 发 RETROSPECT_DONE → 归档
```

> **每条边的产物都是"上一个 Agent 写文件 → 下一个 Agent 读文件 → 推进 state.json"**，上下文在共享文件里逐级累积，IM 只承载"交接信号"。

---

## 四、防死锁规则（借鉴 AgentTeams AGENTS.md）

> 多 Agent 协同最容易卡死，以下硬规则保证闭环收敛。前 3 条来自 AgentTeams `AGENTS.md` 实战经验（见 `AGENTTEAMS-INTERNALS.md` §A.3），后 2 条是我们针对研发闭环补充的。

### 4.1 通信类（防死循环）
1. **@mention 必须用完整 Matrix ID**（带域名），否则 Worker 收不到唤醒。
2. **不做事就发 `NO_REPLY`**（独立完整响应，不能追加在正文后，否则正文被丢弃）。
3. **禁止噪音 @mention**：消息不需要对方做任何事时，别发"收到/谢谢/再见"——会触发镜像死循环。
4. **阶段交接必须立即 @mention**：不能只描述"下一步 bob 会做"，必须实际 @mention，否则流程永久卡住。

### 4.2 任务流转类（防空转/防状态丢失）
5. **每个任务必须注册进 `state.json`**：否则 Worker 会被空闲超时自动停掉。
6. **先写文件再通知**：Worker 需要先 file-sync 才能看到任务，所以**先推送产物到 `shared/`，再 @mention 通知**。
7. **里程碑是唯一推进信号**：`TASK_SPEC_READY → ROOT_CAUSE_FOUND → FIX_APPLIED → TEST_PASSED → RELEASE_OK → RETROSPECT_DONE` 逐级推进，Leader 只认 `state.json` 里的里程碑，不靠聊天推断。

### 4.3 研发闭环专属（防质量失控 / 防无限迭代）
8. **验证闸门当裁判，不靠 Agent 自评**：测试/编译/静态分析是客观闸门（见 `PDCA-CLOSED-LOOP.md` §5.1），不合格代码打回，收敛不靠自律。
9. **打回有上限、有原因**：`TEST_FAILED`/`RELEASE_ROLLED_BACK` 必须附明确失败原因；连续打回超过阈值（如 3 次）则**升级到 Manager/人工介入**，防止 Fixer 无限自修正。
10. **裁员前先归档**：任何 Worker 动态裁员前，先把 `shared/` 产出 + 记忆归档（`knowledge_export`），无状态重建可召回，不丢组织记忆。

---

## 五、与已有设计的衔接

| 已有产出 | 本文件补充的维度 |
|---------|----------------|
| `agents/AGENT-IDENTITY.md`（谁） | 定义了 6 个 Agent 的身份/里程碑，本文件定义它们**怎么组织（Team）、怎么通信（契约）** |
| `design/PDCA-CLOSED-LOOP.md`（流程到哪） | 定义了状态机，本文件定义**状态靠什么流转（shared 文件 + 里程碑 @mention）** |
| `design/MANAGER-LOOP-DESIGN.md`（调度） | Manager 调度工具读 `state.json`，本文件给出 `state.json` 所在路径与推进规则 |
| `skills/SKILL-LIST.md`（怎么做） | Skill 是执行层的"能力包"，本文件定义执行层 Worker 之间怎么交接 Skill 产出 |
| `design/AGENTTEAMS-INTERNALS.md`（机制） | 本文件的 Team 结构/信道/共享文件均映射 AgentTeams 的 CRD/Matrix/MinIO 机制 |

---

## 六、落成 AgentTeams 资源（第 7 项前置）

本设计将转成 `src/` 下的声明式资源：
- **Team CRD**：`team-leader`(Leader) + 6 个职能 Worker + 动态成员。
- **Worker CRD 的 `channelPolicy`**：落地 §2.3 的 peerMentions 矩阵。
- **共享状态**：`shared/tasks/{id}/`、`shared/knowledge/` 的目录契约（落地 MinIO）。
- **防死锁规则**：写进每个 Worker 的 `AGENTS.md`（`spec.agents`）。

---

## 七、相关文档索引

- 总体计划：`../PLAN.md`
- Agent Identity + 动态团队：`../agents/AGENT-IDENTITY.md`
- PDCA 闭环状态机：`PDCA-CLOSED-LOOP.md`
- Manager Loop 设计：`MANAGER-LOOP-DESIGN.md`
- AgentTeams 内部机制（Team 结构/channelPolicy/MinIO shared）：`AGENTTEAMS-INTERNALS.md`
- AgentTeams 落地运行：`AGENTTEAMS-RUNBOOK.md`
- Skill 清单：`../skills/SKILL-LIST.md`
- 上下文工程（信息卸载）：`../references/theory/CONTEXT-ENGINEERING.md`
