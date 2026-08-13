# 官方是怎么建议的：MAF 多 Agent 协同指南 & 可复用能力清单

> 本文基于 MAF（Microsoft Agent Framework）**本地官方源码与文档**调研整理。
> 源码位置：`references/agent-framework/python/`（只读，不修改）。
> 目的：回答「官方对多 Agent 协同怎么建议」「有哪些现成能力可以直接复用」，并映射到我们的参赛作品（软件研发多 Agent 闭环）。

---

## 一、官方推荐的「多 Agent 协同」分三个层次

MAF 官方把多 Agent 编排从简单到高级分为**三层**（见 `python/README.md` + `python/packages/orchestrations/README.md`）：

### 层次 1：手工链式编排（入门，最易上手）
`python/README.md` §5 "Multi-Agent Orchestration" 推荐的入门写法是**直接顺序 await**：
```python
writer_result  = await writer.run(task)              # 1. Writer 产出
reviewer_fb    = await reviewer.run(writer_result)   # 2. Reviewer 评审
final          = await writer.run(refine_request)    # 3. Writer 按反馈迭代
```
- 优点：零学习成本，逻辑完全可控，适合验证多 Agent 协作的概念。
- 缺点：上下文传递、并发、路由都要手写。

### 层次 2：图式 Workflow（底层，完全控制）
`python/packages/core/agent_framework/_workflows/`：
- `Workflow` + `WorkflowBuilder`（节点+边）、`Executor`/`AgentExecutor`、`Edge`/`FanOutEdgeGroup`/`SwitchCaseEdgeGroup`（条件路由）。
- `State`（superstep 语义共享状态）、`WorkflowEvent`、`CheckpointStorage`（暂停/恢复）。
- 官方定位：需要**完全控制力 + 条件路由**时用这层。

### 层次 3：高级编排 Builder（一键搭建 5 种模式，**官方推荐优先用**）
`agent-framework-orchestrations` 包提供 5 个高级 Builder（`python/packages/orchestrations/README.md`）：

| Builder | 定位 | 适用场景 | 对应我们研发闭环 |
|--------|------|----------|------------------|
| **SequentialBuilder** | 顺序链，传递共享会话上下文 | 流水线步骤依次执行 | 缺陷聚合→根因→修复→测试→发布 |
| **ConcurrentBuilder** | 并行扇出 + 汇聚 | 多个独立分析并行 | 多源缺陷聚合 / 多技术栈并行修复 |
| **HandoffBuilder** | 去中心化路由，Agent 自主决定交接 | 客服/分流式 | 问题按类型转派不同 Agent |
| **GroupChatBuilder** | 编排器导向的多 Agent 对话 | 评审/头脑风暴/多方协商 | 方案评审、影响面多方讨论 |
| **MagenticBuilder** | Magentic-One 规划式 | 复杂任务由 Manager 规划 + Worker 执行 | **研发团队 Manager Loop（调度）** |

**官方建议的取舍**：能用高级 Builder 就优先用（`SequentialBuilder` 一行搭好），需要精细控制再降到图式 Workflow，概念验证用手工链式。

---

## 二、官方 5 种模式：我们该先复用哪个？

结合我们的参赛核心（**研发团队调度 Manager Loop + PDCA 闭环 + 动态团队**），官方能力映射：

- **MagenticBuilder** 最贴合我们的 **Manager Loop** 创新点——它就是「一个 Manager 规划任务 + 分派多个 Worker」的现成实现（`MagenticManagerBase` / `StandardMagenticManager` / `MagenticOrchestrator` / `MagenticProgressLedger`）。**这是最值得优先复用/研读的官方能力。**
- **SequentialBuilder** 对应研发流水线的顺序闭环，也基本能直接复用。
- **ConcurrentBuilder** 对应多源并行分析 / 多 Worker 并行。
- **GroupChatBuilder** 对应评审环节。

> 注意：官方 Builder 默认都用 `FoundryChatClient`（需微软账号）。我们已确认可无缝换成 `OpenAIChatCompletionClient`（DeepSeek）——**已在本目录 demo 验证 SequentialBuilder 跑通**。其余 4 种 Builder 同理可换。

---

## 三、可直接复用的官方能力清单（不只编排）

调研 `python/packages/core/agent_framework/` 确认以下现成能力，全部免重写：

| 能力 | 位置 | 对我们参赛的价值 |
|------|------|------------------|
| **Tools**（`@tool` 装饰器 / `FunctionTool` / 审批配置） | `_tools.py` | 封装 issue-parsing / root-cause / code-gen 等 Skill 为可调用工具 |
| **官方 Shell 工具**（LocalShellTool / DockerShellTool，含审批+审计） | `packages/tools/` | 代码执行、命令运行的**安全执行 + 审计**，对应闭环"工具调用/执行证据" |
| **Skills**（`Skill`/`FileSkill`/`MCPSkill`/`FileSkillsSource` 等 20+ 原语） | `_skills.py` | 我们的 Skill 工程可直接用官方 Skill 原语承载 |
| **MCP 集成**（`MCPStdioTool`/`MCPStreamableHTTPTool`/`MCPWebsocketTool`） | `_mcp.py` | 官方要求的 MCP 工具集成，现成 |
| **工具审批 / 回滚**（`@tool(approval_mode="always_require")` + `_harness/_tool_approval.py`） | `_harness/_tool_approval.py` | **审批闸门 + 回滚**，对应闭环"审批回滚"环节 |
| **状态管理**（`State` superstep + `ctx.set_state/get_state`） | `_workflows/_state.py` | 跨 Agent 共享任务状态，对应闭环"上下文传递/共享状态" |
| **可观测**（OpenTelemetry：`configure_otel_providers()`/`get_tracer()`） | `observability.py` | 官方要求的 Trace/Log/Metrics 可观测，现成 |
| **检查点 / 恢复**（`FileCheckpointStorage`） | `_workflows/_checkpoint.py` | 流程中断恢复，对应审批暂停/回滚续跑 |
| **会话持久化**（`AgentSession`/`SessionStore`） | `_sessions.py` | 跨任务保留对话历史 |
| **上下文压缩**（`CompactionStrategy`：摘要/滑窗） | `_compaction.py` | 长任务上下文管理（对齐我们的 32K-64K 预算） |
| **评估**（`evaluate_agent`/`evaluate_workflow`） | `_evaluation.py` | 确定性验证 / 质量门禁 |
| **Harness**（文件访问/记忆/TODO/后台 Agent） | `_harness/` | 落地成研发工作区 |
| **声明式 Workflow**（YAML 声明 Agent/编排） | `packages/declarative/` | 用配置声明 Agent 团队，贴合"动态团队" |

---

## 四、官方对「上下文传递 / 共享状态」的建议

官方提供两种机制（`packages/orchestrations` + `samples/03-workflows/state-management/`）：

1. **Workflow 内置 State**：`ctx.set_state(key, value)` / `ctx.get_state(key)`，**superstep 语义**（同一步骤内所有执行器看到相同 committed 状态）。官方示例 `state_with_agents.py` 用它传大对象（Email），只传 key 引用，避免上下文膨胀——**这正对齐我们 CONTEXT-ENGINEERING 的"信息卸载"策略**。
2. **Workflow kwargs**：`workflow_kwargs_global.py`（全局上下文传给所有工具）/ `workflow_kwargs_per_agent.py`（单 Agent 上下文）。
3. **会话持久化**：`workflow_as_agent_with_session.py` 用 `AgentSession` 跨调用保留历史。

> 与我们方案的衔接：状态存 `shared/tasks/{id}/state.json`（可审计）→ 对应官方 `State`；验证闸门当确定性裁判 → 对应官方 `evaluate_*` + tool_approval。

---

## 五、结论：我们该怎么"复用官方东西"

**优先级排序（建议）**：

1. **【最高】优先研读 + 复用 MagenticBuilder 源码**——它是我们「Manager Loop 调度」创新点的官方现成范本。读 `packages/orchestrations/agent_framework_orchestrations/_magentic.py` 的 `MagenticManagerBase`/`StandardMagenticManager`/`MagenticOrchestrator`，学习官方怎么实现「Manager 规划 + Worker 执行 + ProgressLedger 任务账本」。
2. **【高】编排层直接复用 5 种 Builder**（已用 DeepSeek 验证 SequentialBuilder，其余同理）。我们的 PDCA 闭环 = Sequential（主链）+ Concurrent（并行）+ GroupChat（评审）+ Magentic（Manager）。
3. **【中】能力层复用官方内置**：tool_approval（审批回滚）、State（共享状态）、observability（可观测）、_tools/@tool（Skill 承载）、MCP。
4. **【低】换框架**：仅当 AgentTeams 部署不通、确需纯 MAF 落地时才考虑把 MAF 作为主要实现（官方要求以 AgentTeams 为基点，MAF 只能作参考实现/备选）。

---

## 六、关键文件索引（方便直接打开研读）

- 官方多 Agent 入门示例：`python/README.md` §5
- 5 种 Builder 文档：`python/packages/orchestrations/README.md`
- Magentic Builder 源码：`python/packages/orchestrations/agent_framework_orchestrations/_magentic.py`
- 编排示例全部：`python/samples/03-workflows/orchestrations/`
- Magentic 示例：`orchestrations/magentic.py`、`magentic_checkpoint.py`、`magentic_human_plan_review.py`
- 状态共享示例：`samples/03-workflows/state-management/`
- 审批/回滚：`samples/03-workflows/tool-approval/`
- 工具审批源码：`packages/core/agent_framework/_harness/_tool_approval.py`
