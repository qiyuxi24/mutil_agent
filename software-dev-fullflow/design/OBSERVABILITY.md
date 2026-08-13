# 可观测设计（OBSERVABILITY）

> GOAI 大赛 · 赛道三「软件研发全流程协同」· 第 5 项核心产出
> 对应官方要求：**可观测（推荐）** —— 覆盖 Skill 调用、MCP 工具、RAG 检索、LLM 推理等全链路推理轨迹；支持在线监控与告警、评估与优化。
> 官方要求：至少覆盖 Trace、Log、Metrics 中的 **1-2 类**；建议遵循 OpenTelemetry GenAI 标准（`OTEL`）。
> 对应评审权重：**工程落地、运行验证与安全可审计 20%**。
> 日期：2026-08-12

---

## 0. 结论先行

> 我们覆盖 **Trace + Log + Metrics 三类全部**（高于官方 1-2 类的最低标准），采用 **OpenTelemetry 标准**（对齐官方建议与 MAF `observability.py` 的实现方式）。观测数据源来自两处：① **AgentTeams 平台**（Matrix 房间、心跳、控制器 Reconcile 日志，天然可审计）；② **我们自研的 Manager Loop 中间件**（在 `MANAGER-LOOP-DESIGN.md` §3.6 预留的钩子落点）。

---

## 一、观测目标与三类信号

### 1.1 观测目标（我们想看什么）

| 目标 | 说明 | 服务谁 |
|------|------|--------|
| **闭环跑得通** | 每个任务从 SPEC_INPUT → … → RETROSPECT_DONE 完整流转 | 开发者/评审 |
| **卡在哪** | 哪个状态停留过久、哪个 Worker 不响应 | 人工/Manager 心跳 |
| **质量是否达标** | 修复通过率、打回次数、回滚次数 | 质量门禁 |
| **是否安全可审计** | 谁改了什么、谁审批了、谁回滚了（全程留痕） | 安全/合规 |

### 1.2 三类信号定义（OpenTelemetry 语义）

| 信号 | 定义 | 粒度 | 满足官方哪条 |
|------|------|------|-------------|
| **Trace** | 跨 Agent 的**任务级链路**：一个 `task_id` 贯穿从聚合到复盘的完整调用链 | 任务/里程碑/工具调用 | 推理轨迹、全链路 |
| **Log** | 各 Agent 的**决策日志** + 里程碑交接 + 工具调用结果 + 错误 | 事件 | 决策日志、执行证据 |
| **Metrics** | **聚合指标**：闭环总时延、各状态时延、通过率、打回数、回滚数、沉淀条目数 | 数字（Counter/Histogram/Gauge） | 监控告警、评估 |

---

## 二、Trace：跨 Agent 任务链路追踪

### 2.1 设计核心：`task_id` 贯穿 + 状态 Span

**Trace 的根 = 一个任务**。从任务进入 `shared/tasks/{id}/` 开始，到 `RETROSPECT_DONE` 归档结束，生成一条**完整 trace**，其中每个里程碑/每个 Agent 动作是一个 **Span**：

```
Trace: task-{id}（研发修复闭环）
├── Span: SPEC_INPUT        （Aggregator 聚合）
├── Span: SPEC_DECOMPOSE    （Aggregator 拆解）
├── Span: ROOT_CAUSE        （RootCause 定位）
├── Span: FIX_APPLY         （Fixer 修复）
│   ├── Span: 工具调用 compile/typecheck/static-analysis
│   └── Span: 工具调用 git/PR
├── Span: TEST_VERIFY       （Tester 验证）
│   ├── Span: 工具调用 test-run
│   └── Span: TEST_FAILED 打回（若失败）
├── Span: RELEASE + RELEASE_APPROVE（Releaser 发布 + Manager 审批）
│   └── Span: RELEASE_ROLLED_BACK（若回滚）
└── Span: RETROSPECT        （Retrospector 沉淀）
```

### 2.2 关键字段（Span Attribute）

| Attribute | 值 | 用途 |
|-----------|-----|------|
| `task.id` | `task-{uuid}` | **贯穿全链路，trace 关联键** |
| `milestone` | `TASK_SPEC_READY`/`ROOT_CAUSE_FOUND`/… | 定位当前状态 |
| `agent.name` | Aggregator/RootCause/Fixer/… | 谁干的 |
| `agent.role` | worker/leader/manager | 角色层级 |
| `tool.name` | `test-run`/`compile`/`rag_search` | 工具调用追踪 |
| `model.name` | `qwen3.5-plus` | LLM 推理追踪 |
| `span.type` | `reasoning`/`acting`/`tool`/`milestone` | span 分类 |

### 2.3 落点（Manager Loop 中间件）

在 `MANAGER-LOOP-DESIGN.md` §3.6 的钩子上打 Trace：
- `on_reply`：创建根 Span（`task.id` 注入 context）
- `on_model_call`：记录 LLM 推理 Span（模型、token）
- `on_acting`：记录调度工具调用 Span（`dispatch_task`/`poll_worker`…）
- `on_reasoning`：记录推理 Span

```python
# 伪代码：对齐 MAF configure_otel_providers() + get_tracer()
configure_otel_providers()          # 读 OTEL_EXPORTER_OTLP_ENDPOINT 等
tracer = get_tracer("software_dev_loop")
with tracer.start_as_current_span(f"task-{task_id}") as root:
    with tracer.start_as_current_span("ROOT_CAUSE") as s:
        s.set_attribute("agent.name", "RootCause")
        ...
```

---

## 三、Log：决策日志 + 执行证据

### 3.1 两级日志

| 层 | 内容 | 来源 | 存储 |
|----|------|------|------|
| **平台级** | Matrix 房间全记录、Manager/Worker 容器日志、控制器 Reconcile 日志、心跳 | AgentTeams 原生 | `docker logs` + `shared/` |
| **应用级** | 每个 Agent 的决策：读了什么、产出什么、@mention 谁、发什么里程碑 | 我们注入的 Log 中间件 | OTLP 后端 + `shared/logs/` |

### 3.2 关键日志事件（结构化）

| 事件 | 内容 | 用途 |
|------|------|------|
| `milestone_sent` | agent、milestone、to、task.id | 交接轨迹 |
| `tool_call` | tool、args摘要、result状态 | 执行证据 |
| `tool_result_redacted` | 工具结果脱敏后记录 | 安全（敏感输出打码） |
| `state_transition` | from_state、to_state、task.id | 状态机审计 |
| `approval` | who、what、approve/reject、task.id | **审批审计** |
| `rollback` | reason、scope、task.id | **回滚审计** |
| `error` | error_type、stack、task.id | 故障定位 |

> **安全注意**：日志需**脱敏**——API Key / GitHub PAT / 文件敏感内容不落明文。对齐 AgentTeams 的 PII 脱敏（`AGENTTEAMS` 的 export-debug-log 会自动脱敏）。

### 3.3 落点

- **应用级 Log**：在 Manager Loop 的 `on_acting`/`on_reply` 中间件里发结构化日志（Python `logging` + OTel LoggerProvider）。
- **平台级 Log**：AgentTeams 原生 Matrix 房间即"行为日志"；`docker logs` 提供容器层日志；`shared/logs/` 落本地证据。

---

## 四、Metrics：聚合指标 + 告警

### 4.1 指标清单

| 指标 | 类型 | 含义 | 告警阈值（示例） |
|------|------|------|----------------|
| `loop.duration_seconds` | Histogram | 单个任务闭环总时延 | 超阈值告警 |
| `milestone.duration_seconds` | Histogram | 各状态时延（定位修复慢→瓶颈） | 单状态超阈值 |
| `fix.pass_rate` | Gauge | 修复通过率（TEST_PASSED/总） | 低于 80% |
| `rollback.count` | Counter | 回滚次数 | >0 即关注 |
| `reject.count` | Counter | 打回次数（TEST_FAILED/ROLLED_BACK） | 连续超阈值→人工介入 |
| `knowledge.entries` | Gauge | 知识库沉淀条目数 | — |
| `agents.active` | Gauge | 在岗 Worker 数（动态团队规模） | — |
| `workers.idle` | Gauge | 闲置 Worker 数（可用于裁员判断） | — |

### 4.2 关键 Metrics 与闭环的关系

- **打回/回滚 Metrics** 直接对应质量门禁与最小影响发布（`PDCA-CLOSED-LOOP.md` §5）——指标是门禁是否生效的量化证据。
- **状态时延 Metrics** 帮助发现闭环瓶颈（如 ROOT_CAUSE 总超时→该状态优化）。
- **闲置 Worker Metrics** 支撑「AI 公司」动态团队的**裁员决策**（`AGENT-IDENTITY.md` §2.2）。

### 4.3 落点

- Manager Loop 的 `on_acting`/`on_model_call` 钩子打 Counter/Histogram。
- OTel MetricProvider + OTLP 导出（对齐 `observability.py`）。

---

## 五、后端存储与检索（第 6 项衔接）

| 数据 | 后端 | 检索方式 |
|------|------|---------|
| Trace/Log | OTLP 兼容后端（Jaeger/OTel Collector + 时序库） | 按 task.id 检索完整链路 |
| Metrics | 时序库（Prometheus 兼容） | 告警规则 + Grafana 面板 |
| 执行证据/审计 | `shared/logs/` + `shared/tasks/{id}/`（MinIO） | 文件系统检索，**离线可审** |

> 观测数据与共享状态分离：**观测**走 OTel（Trace/Log/Metrics），**执行证据**落 MinIO（`shared/`）。两者通过 `task.id` 关联。

---

## 六、评估与优化（官方"建议支持实时或离线评估"）

- **离线评估**：用 Metrics（通过率/回滚数）+ 日志证据，对每个任务做质量复盘（`RETROSPECT` 阶段自然承担）。
- **在线监控**：Metrics 告警 → 人工/Manager 介入（对接 `PDCA-CLOSED-LOOP.md` §5 的"连续打回升级人工"）。
- **评估闭环**：复盘沉淀（`shared/knowledge/`）→ 反哺 Skill/根因分析 → 下一个任务更准（对接第 6 项 RAG）。

---

## 七、与 AgentTeams 平台的可观测能力对接

AgentTeams 平台已内置部分观测，我们**复用而非重建**：

| AgentTeams 原生能力 | 我们怎么用 |
|--------------------|-----------|
| Matrix 房间全记录 | 天然的"对话级行为日志"（Trace 的原始素材） |
| Manager 心跳（HEARTBEAT.md） | 进程级健康 + 任务进度巡检（对应 Log 里的活跃信号） |
| 控制器 Reconcile 日志 | 资源层状态（Worker 增删/生命周期） |
| `export-debug-log.py` | 出问题时导出 Matrix + 会话日志（PII 脱敏） |

> 我们的 OTel（Trace/Log/Metrics）与 AgentTeams 平台观测**互补**：平台给"资源/通信层"，我们给"任务/质量层"，用 `task.id` 关联打通。

---

## 八、评审亮点（供 PPT/简介引用）

- **高于官方最低标准**：Trace + Log + Metrics 三类全覆盖（官方仅需 1-2 类）。
- **标准对齐**：采用 OpenTelemetry，符合官方"建议遵循 OTel GenAI 标准"，并与 MAF `observability.py` 实现方式一致。
- **安全可审计**：审批/回滚全程 Log 留痕 + `shared/` 证据落地（命中"安全可审计 20%"）。
- **闭环可量化**：通过率/回滚数/状态时延 Metrics 让"闭环收敛"有数据证据，不靠口头自评。

---

## 九、相关文档索引

- 总体计划：`../PLAN.md`
- 官方可观测要求：`../references/docs/OFFICIAL-REQUIREMENTS.md` §五
- Manager Loop 中间件落点：`MANAGER-LOOP-DESIGN.md` §3.6
- PDCA 闭环（质量门禁/回滚）：`PDCA-CLOSED-LOOP.md`
- 协同流程（日志事件来自里程碑交接）：`COLLABORATION-DESIGN.md`
- MAF OTel 实现参考：`../references/agent-framework/python/packages/core/agent_framework/observability.py`
- RAG/记忆方案（第 6 项，知识沉淀反哺）：`RAG-MEMORY.md`
