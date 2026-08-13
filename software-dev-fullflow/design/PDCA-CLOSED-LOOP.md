# PDCA 闭环状态机设计（研发团队调度闭环）

> GOAI 大赛 · 赛道三「软件研发全流程协同」· 第 2 项核心产出
> 对应官方要求：**多 Agent 协同闭环**（任务输入→拆解→上下文传递→工具调用→结果验证→证据沉淀→审批回滚→经验沉淀），多 Agent 协同 25% 权重。
> 理论总纲：**PDCA 闭环**（主框架）+ 三条子原理（自动化质量门禁 / 最小影响可回滚 / 组织记忆复用）。
> 日期：2026-08-06

---

## 0. 定位说明（与角色非重点呼应）

> 本状态机描述的是**闭环本身**（流程/状态/闸门/回滚），是作品的重点之一。
> 状态机中的"执行者"可以是 6 个默认角色，也可以是**动态招募的任意 Worker**（参考 `agents/AGENT-IDENTITY.md` 的动态团队机制）。
> 因此本状态机**与具体角色解耦**：它定义"流程走到哪个状态、由谁触发、怎么验证、怎么回滚"，具体角色只是默认执行者。

---

## 1. 官方闭环 8 环节 → PDCA 状态机映射

官方要求的闭环 8 环节，映射到 PDCA 四象限 + 状态机 8 个主状态：

| # | 官方 8 环节 | PDCA | 状态 | 默认执行者 | 关键产物 |
|---|------------|------|------|-----------|---------|
| 1 | 任务输入 | P | `SPEC_INPUT` | Aggregator | 多源缺陷/需求 |
| 2 | 任务拆解 | P | `SPEC_DECOMPOSE` | Aggregator | `spec.md`（拆解为可执行子任务） |
| 3 | 上下文传递 | D | `ROOT_CAUSE` | RootCause | `root-cause.md` + 影响面 |
| 4 | 工具调用（修复执行） | D | `FIX_APPLY` | Fixer | `fix/` 代码改动 |
| 5 | 结果验证 | C | `TEST_VERIFY` | Tester | `test-report.md` |
| 6 | 执行证据沉淀 | A | `RELEASE` | Releaser | `release-report.md`（证据留痕） |
| 7 | 审批与回滚 | A | `RELEASE_APPROVE` | Releaser/Manager | 审批记录 / 回滚证据 |
| 8 | 经验沉淀 | A | `RETROSPECT` | Retrospector | `shared/knowledge/{id}.md` |

---

## 2. 状态机总图（文本版）

```
                    ┌──────────────────────────────────────────────────────┐
                    │                    P 计划 (Plan)                     │
                    └──────────────────────────────────────────────────────┘

[任务输入] → SPEC_INPUT ──聚合去重──▶ SPEC_DECOMPOSE ──拆解成子任务──▶ TASK_SPEC_READY(里程碑)
                 ▲                                                          │
                 │                                                          ▼
                    ┌──────────────────────────────────────────────────────┐
                    │                    D 执行 (Do)                       │
                    └──────────────────────────────────────────────────────┘
                TASK_SPEC_READY ─▶ ROOT_CAUSE ──RCA+影响面──▶ ROOT_CAUSE_FOUND(里程碑)
                                                                      │
                    ┌──────────◀────────── TEST_FAILED(打回) ◀──────────┐
                    ▼                                                    │
                FIX_APPLY ──编码+编译+静态分析──▶ FIX_APPLIED(里程碑) ──▶│
                                                                        ▼
                    ┌──────────────────────────────────────────────────────┐
                    │                     C 检查 (Check)                  │
                    └──────────────────────────────────────────────────────┘
                FIX_APPLIED ─▶ TEST_VERIFY ──测试金字塔──▶ TEST_PASSED(里程碑)
                                                               │ (通过)
                    ┌──────────◀────── RELEASE_ROLLED_BACK(回滚打回) ◀──────┐
                    ▼                                                       │
                    ┌──────────────────────────────────────────────────────┐
                    │                     A 处置 (Act)                    │
                    └──────────────────────────────────────────────────────┘
                TEST_PASSED ─▶ RELEASE ──灰度+金丝雀──▶ RELEASE_APPROVE ──审批──▶ RELEASE_OK(里程碑)
                                                                │ (审批拒绝/失败)
                                                                ▼
                                                           RELEASE_ROLLED_BACK
                                                                │
                                                                ▼
                RELEASE_OK ─▶ RETROSPECT ──复盘+沉淀──▶ RETROSPECT_DONE(里程碑) → 任务归档/闭环完成
```

---

## 3. 状态定义表（每个主状态的输入/执行者/产出/验证闸门/回滚点）

| 状态 | 输入 | 执行者 | 产出 | 验证闸门（确定性裁判） | 回滚点 |
|------|------|--------|------|----------------------|--------|
| `SPEC_INPUT` | 多源缺陷/需求 | Aggregator | 归一化条目 | 去重率/规范校验 | 无（可重新聚合） |
| `SPEC_DECOMPOSE` | 归一化条目 | Aggregator | `spec.md` + 子任务清单 | 规范格式校验（字段齐全） | 打回重拆 |
| `ROOT_CAUSE` | `spec.md` | RootCause | `root-cause.md` + 影响面 | 确定性根因标注（不确定须注明） | 重定位 |
| `FIX_APPLY` | `root-cause.md` | Fixer | `fix/` 改动 + `plan.md` | **编译/类型检查/静态分析**（Ralph 反压） | 打回自修正 |
| `TEST_VERIFY` | `fix/` + 既有测试 | Tester | `test-report.md` | **测试金字塔**（单测→集成→E2E）+ 覆盖率 | TEST_FAILED → 打回 FIX_APPLY |
| `RELEASE` | `test-report.md`(通过) | Releaser | 灰度/金丝雀验证结果 | 金丝雀健康检查 | 失败 → 回滚 |
| `RELEASE_APPROVE` | 灰度结果 | Releaser/Manager | 审批记录 + 发布证据 | **人工/Leader 审批**（Saga 补偿） | RELEASE_ROLLED_BACK → 打回 FIX_APPLY |
| `RETROSPECT` | 全流程产物 | Retrospector | `shared/knowledge/{id}.md` | 结构化沉淀校验 | 无需回滚（只读沉淀） |

---

## 4. 里程碑握手协议（跨 Agent 交接点）

每个状态流转到"完成"时，产出**里程碑触发词**，由执行者 @mention 下一个执行者（借鉴 AgentTeams AGENTS.md @mention 机制，防死锁）：

```
TASK_SPEC_READY      ← Aggregator 完成，@RootCause
ROOT_CAUSE_FOUND     ← RootCause 完成，@Fixer
FIX_APPLIED          ← Fixer 完成，@Tester
TEST_PASSED          ← Tester 通过，@Releaser      （TEST_FAILED 打回 @Fixer）
RELEASE_OK           ← Releaser 审批通过，@Retrospector（RELEASE_ROLLED_BACK 打回 @Fixer）
RETROSPECT_DONE      ← Retrospector 完成，闭环结束，归档任务
```

> **交接规则**：
> - 每个 Agent 完成本职产出后，必须用**完整 Matrix ID** @mention 下一个 Agent 并发送里程碑词。
> - 不做事则发 `NO_REPLY`（独立响应，不阻塞）。
> - **噪音 @mention 会死循环，禁止**（只发里程碑词/结果，不发"收到/谢谢"）。
> - 每个里程碑在 `shared/tasks/{id}/state.json` 注册，Manager 据此知道当前处于哪个状态。

---

## 5. 验证闸门与回滚（三条子原理落地）

### 5.1 自动化质量门禁（C 阶段，Ralph 反压）
- 测试验证员用**确定性工具**当裁判（测试套件/编译检查/静态分析），**不依赖 Agent 自评**。
- `TEST_FAILED` 附明确失败原因，打回 Fixer；Fixer 修正后重新进入 `FIX_APPLY`。
- 质量门禁确保"不合格代码不进入发布"，是闭环收敛的关键。

### 5.2 最小影响发布 + 可回滚（A 阶段）
- Releaser 做**灰度/金丝雀**，逐步放量，失败按 **Saga 补偿**回滚，保证系统一致。
- `RELEASE_ROLLED_BACK` 打回 Fixer，附回滚原因与影响面。
- 发布全程留痕（审批记录 + 发布证据），满足"安全可审计 20%"。

### 5.3 组织记忆复用（A 阶段）
- Retrospector 复盘后把经验沉淀到 `shared/knowledge/`（结构化：问题→根因→解法→验证）。
- 沉淀后可供 RAG 检索，实现"越跑越懂项目"，下一个类似缺陷直接复用。

---

## 6. 与 Manager Loop 的衔接（第 2 项 × Manager 调度）

本状态机是被 **Manager Loop**（`design/MANAGER-LOOP-DESIGN.md`）驱动的"流程蓝图"：

| Manager Loop 调度工具 | 驱动的状态流转 |
|----------------------|--------------|
| `dispatch_task(worker, milestone, spec)` | 把任务派到当前状态对应的执行者 |
| `poll_worker(worker)` | 等执行者产出，检查是否发里程碑词 |
| `read_milestone()` | 读 `state.json`，判断当前状态 |
| `write_milestone(milestone, verdict)` | 状态推进（通过）或打回（失败） |
| `approve_release()` | 触发 `RELEASE_APPROVE` 审批/回滚 |
| `record_retrospective()` | 触发 `RETROSPECT` 沉淀 |

> **状态机 = Manager 的"下一步决策依据"**：Manager 的 `_next_action` 通过 `read_milestone()` 知道当前状态，再决定派谁、下一步做什么。闭环的收敛不靠 Manager 自律，靠**验证闸门**（5.1）做客观裁判。

---

## 7. 状态机的可观测性（对接可观测设计，第 5 项）

每个状态流转都产生可观测信号：
- **Trace**：任务 id 贯穿全流程（`shared/tasks/{id}/`），跨 Agent 链路可追踪。
- **Log**：每个里程碑 @mention + 状态切换记录到 Matrix 房间。
- **Metrics**：闭环总时延、各状态时延、修复通过率、回滚次数、沉淀条目数。

> 这些在 Manager Loop 的中间件（`on_model_call`/`on_acting`）落点已预留，见 `MANAGER-LOOP-DESIGN.md` 3.6。

---

## 8. 状态机实现落点（暂不部署，代码在第 7 项）

- `shared/tasks/{id}/state.json`：存储当前状态 + 里程碑进度 + 各阶段产物路径。
- Manager 的 `read_milestone`/`write_milestone` 工具读写这个文件。
- 状态机本身是**确定性状态图**（可用 enum + 转移表实现），Manager 只负责"根据状态派活"，不负责"记住状态"（状态在 shared 文件，可审计）。

---

## 9. 相关文档索引
- 总体计划：`../PLAN.md`
- Agent Identity + 里程碑协议：`../agents/AGENT-IDENTITY.md`
- Manager Loop 设计：`MANAGER-LOOP-DESIGN.md`
- AgentTeams 内部机制：`AGENTTEAMS-INTERNALS.md`
- Ralph 单 Agent 方法论（反压）：`../references/theory/SINGLE-AGENT-ITERATION.md`
- 动态 Agent 团队：`../references/theory/DYNAMIC-AGENT-TEAM.md`
