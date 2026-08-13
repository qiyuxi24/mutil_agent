# 研发团队调度 Manager Loop 设计（基于 AgentScope · 方案 B）

> 目标：深入 AgentScope 的 `Agent.reply` 主循环，设计我们自己的"研发团队调度 Manager loop"。
> 原则：**文档先行，代码后置**——本文件是先出设计，再写代码。当前只做源码层设计，不部署。
> 基础：方案 B = 基于 AgentScope(Python) 写自己的 Manager loop + 用 QwenPaw 运行时接入 AgentTeams（详见 `OPENCLAW-VS-QWENPAW.md`）。
> 日期：2026-08-06

---

## 一、为什么选择"扩展 AgentScope 状态机"而不是自写 loop

在 `OPENCLAW-VS-QWENPAW.md` 已论证：不需要从零重写 Agent loop。AgentScope 的 `Agent.reply` 主循环是一个**显式 ReAct 状态机**（`Acting` / `Reasoning` / `Exit`），结构清晰、模块化、易扩展。

我们要做的不是重写它，而是**在它的循环体内插入"团队调度"这一层动作**——让 Manager 的一次 `reply()` 不再只是"个人思考+调用本地工具"，而是"拆解任务 → 招/派 Worker → 收集结果 → 验证 → 决定下一个里程碑"。

---

## 二、AgentScope `Agent.reply` 主循环源码剖析（实证）

### 2.1 整体调用链

```
reply() / reply_stream()            # 公共入口（消费/流式事件）
  └─ _reply()                       # 中间件包装入口（on_reply 钩子链）
      └─ _reply_impl()              # 核心主循环（Step1→Step2→Step3）
          ├─ _next_action()         # 决策：下一步是 Reasoning / Acting / Exit
          ├─ _reasoning()           # 调模型（Reasoning 分支）
          │   └─ _reasoning_impl()  # 真正调 _call_model + 事件流 + 存上下文
          ├─ _batch_tool_calls()    # 工具分批（sequential / concurrent）
          ├─ _execute_sequential_tool_calls()
          ├─ _execute_concurrent_tool_calls()
          └─ cur_iter += 1          # 每轮 Reasoning-Acting 计数
```

### 2.2 `_reply_impl()` 主循环（核心）

源码位置：`agentscope/agent/_agent.py` 的 `_reply_impl`（约 758 行起）。

```
try:
    # Step 1: 检查输入事件类型（是否在等待 HITL 恢复）
    event / msgs 分流（UserConfirmResultEvent / UserInterruptEvent / ExternalExecutionResultEvent / Msg）

    # Step 2: 处理输入
    _handle_incoming_messages(msgs)  +  重置 reply_context（新 reply_id, cur_iter=0）
    yield ReplyStartEvent

    # Step 3: 核心循环 —— 直到 Exit 或超 max_iters
    while True:
        next_action = self._next_action(final_msg)   # ← 决策点（我们要扩展的地方）

        match next_action:
            case Exit(...):        yield exit_msg; return
            case Reasoning(...):   compress_context() → _inject_runtime_state() → _reasoning()
            case Acting(tool_calls): _batch_tool_calls() → 分批执行工具
                                    （遇 RequireUserConfirmEvent / RequireExternalExecutionEvent 暂停等 HITL）

        self.state.cur_iter += 1
```

### 2.3 `_next_action()` 决策逻辑（扩展关键）

源码位置：`_next_action`（约 3019 行起）。这是**单 Agent 的决策器**，返回三种动作之一：

```
1. 有可执行的 tool_call（ALLOWED / PENDING 且无等待）→ Acting(tool_calls)
2. 有等待中的 tool_call（权限/外部执行未回）→ Exit（挂起，等 HITL 事件恢复）
3. 有结构化输出要求且已满足 → Exit(带 structured_output)
4. 有结构化输出要求但未满足 → Reasoning（强制走结构化输出工具）
5. 否则 → Reasoning（正常再调模型）
6. 若 cur_iter >= max_iters → Exit（超限）
```

> **对 Manager 的启示**：这个决策器是"个人 ReAct"。我们要扩展的是——当 Manager 要"派任务给 Worker"时，这个"工具调用"应该是一个**调度工具**（如 `dispatch_task` / `hire_worker` / `wait_worker`），其"执行"动作走 AgentTeams 的编排通道，而不是本地函数。见第三节。

### 2.4 `_reasoning_impl()` 模型调用

源码位置：`_reasoning_impl`（约 1316 行起）。

```
yield ModelCallStartEvent
kwargs = await self._prepare_model_input()   # 组装 messages + tools
res = await self._call_model(tool_choice, **kwargs)   # 调 LLM
# 处理流式/非流式 → 转成事件块
# thinking-only 响应 → 继续循环（不视为最终答案）
# 若无 tool_call → 生成最终消息
self._save_to_context(content, usage)        # 存上下文
```

> **对 Manager 的启示**：`_prepare_model_input` 是注入 system_prompt + tools + context 的地方。Manager 的 system prompt 需要包含"团队状态、Worker 清单、里程碑协议"；tools 需要注册调度工具集。

### 2.5 工具分批执行（并行/串行）

源码位置：`_batch_tool_calls`（约 1682 行）、`_execute_sequential/concurrent_tool_calls`（约 1722/1772 行）。

- 按工具属性 `is_concurrency_safe` / `is_read_only` 自动分批：并发安全的一起跑，否则串行。
- 执行中若产生 `RequireUserConfirmEvent` / `RequireExternalExecutionEvent` → 暂停，等外部事件恢复。
- **对 Manager 的启示**：Manager 派多个 Worker 时天然是"并发"语义（不同 Worker 各自跑），可通过注册 `is_concurrency_safe=True` 的调度工具实现并行派单。

### 2.6 中间件钩子（可观测 + 扩展落点）

AgentScope 提供中间件钩子，用于不改源码地插入逻辑：

```
on_reply / on_reasoning / on_acting / on_model_call
on_system_prompt / on_compress_context / on_check_permission / on_check_context
```

> **对 Manager 的启示**：我们可以在 `on_model_call` 打 Trace（跨 Agent 任务链路），在 `on_acting` 打 Metrics（派单次数/时延），在 `on_reasoning` 打 Log —— 满足官方"可观测"要求，且不动核心 loop。

---

## 三、我们的"研发团队调度 Manager Loop"设计

### 3.1 核心思想：把"单 Agent ReAct"升级为"调度 ReAct"

Manager 本质上也是一个 Agent，但它**不做具体编码/测试**，它做的是**调度**：
`醒来 → 读任务 → 决定招谁/派谁 → 派单 → 等结果 → 验证 → 决定下一个里程碑 → 循环`。

我们用 AgentScope 的状态机，但把"工具调用"这一环替换成**调度工具集**，把"工具执行"这一环对接 **AgentTeams 编排层**（Worker CRD + Matrix 通信 + MinIO shared state）。

```
Manager.reply(task_spec)
   │
   ▼  (Step3 主循环)
   Reasoning(模型思考：下一个该做什么)
      │  注入：团队状态 + Worker 清单 + 里程碑协议 + 当前任务 context
      ▼
   Acting(调度工具调用)  ← 关键：这里的 tool 是调度工具，不是本地函数
      │  例如：
      │    hire_worker(role, skills)         → 招人（AgentTeams 创建 Worker）
      │    dispatch_task(worker_id, milestone, spec) → 派单
      │    poll_worker(worker_id)            → 等结果（读 shared state）
      │    approve_release(milestone)        → 审批/回滚决策
      │    log_milestone(milestone, verdict) → 里程碑记录
      ▼
   Exit / 循环
```

### 3.2 决策状态机的扩展：`_next_action` → Manager 版

我们在 `_next_action` 的"Reasoning"和"Acting"之间，增加一个**团队上下文感知**层：

```
Manager._next_action(final_msg):
    1. 先查是否有等待中的调度结果（worker 还在跑）：
       若在等某个 worker → Exit(挂起) 或 轮询 → 见 3.4
    2. 查当前里程碑是否可推进（验证闸门是否通过）：
       若验证通过 → 决定推进到下一个里程碑 → Reasoning(带 hint)
    3. 若无待办 → 视为当前里程碑任务已完成 → 判断整任务是否完成 → Exit
    4. 否则 → Reasoning(继续调度思考)
```

> 设计要点：**Manager 不自己执行工具的结果**，它只"看结果、做判断、下派单"。具体执行（写代码、跑测试）由 Worker 完成，结果通过 shared state 回流。

### 3.3 Manager 的调度工具集（注册进 Toolkit）

| 工具名 | 作用 | is_concurrency_safe | 对应 AgentTeams |
|--------|------|--------------------|-----------------|
| `list_workers` | 列出当前团队 Worker | 是 | 查 Worker CRD |
| `hire_worker` | 按需招 Worker（角色+技能） | 是 | 创建 Worker CRD |
| `fire_worker` | 任务结束/角色不需要时移除 | 否 | 删除 Worker CRD |
| `dispatch_task` | 派单给指定 Worker（含里程碑+spec） | 是 | 写 `shared/tasks/{id}/spec` + Matrix 通知 |
| `poll_worker` | 读 Worker 结果（shared state） | 是 | 读 `shared/tasks/{id}/result` |
| `read_milestone` | 读当前里程碑状态 | 是 | 读 `shared/tasks/{id}/state.json` |
| `write_milestone` | 推进/打回里程碑 | 否 | 写 `shared/tasks/{id}/state.json` |
| `approve_release` | 发布审批（决策回滚） | 否 | 触发 Releaser/回滚 |
| `record_retrospective` | 复盘沉淀到知识库 | 是 | 写 `shared/knowledge/` |

> 这一工具集把 Manager 的"调度意图"显式化，每个工具都映射到 AgentTeams 的声明式资源。这也让"AI 公司式动态团队"落地：`hire_worker`/`fire_worker` 对应"招人/裁员"。

### 3.4 同步/异步派单语义（关键设计决策）

Manager 派单给 Worker 是**长耗时、跨进程**的操作，不能像本地工具那样同步返回。AgentScope 已内置两种 HITL 事件，正好复用：

- **异步轮询（推荐）**：`dispatch_task` 工具返回"已派单，任务 id"，然后 Manager `poll_worker` 轮询 shared state。用 AgentScope 的**挂起/恢复**机制——当 Manager 没有可做的调度动作时，返回 `Exit(挂起)`，等待"外部 worker 完成"事件恢复。

- **事件驱动**：worker 完成时通过 Matrix 发消息 → Manager 的 `observe()` 收到 → 触发新的 `reply()` 继续。

> 落地：我们给 Manager 注册一个"外部执行结果"通道（对接 `ExternalExecutionResultEvent` 或 Matrix 消息），让 Manager 能在"等 worker"时不空转。这比硬编码同步等待更优雅，也契合 AgentScope 原生的 HITL 设计。

### 3.5 Manager 的上下文预算（对齐 Context Engineering 研究）

参考 `references/theory/CONTEXT-ENGINEERING.md`：Manager 只用 32K-64K 紧凑窗口，只保留调度信号，深度探索派 Worker 子代理。

```
Manager system_prompt（约 10-15%）：
  - 团队结构（6 个研发 Agent 的职责/接口）
  - 里程碑握手协议（TASK_SPEC_READY→ROOT_CAUSE_FOUND→FIX_APPLIED→TEST_PASSED→RELEASE_OK→RETROSPECT_DONE）
  - 调度准则（何时招人、何时打回、何时回滚）
  - 防死锁规则（AGENTS.md 借鉴：完整 @mention、任务须注册 state.json）
工作记忆（约 35%）：当前任务 spec + 里程碑进度 + 各 worker 最近结果
检索（约 25%）：从 RAG 拉相关经验/已修复缺陷
调度工具 + 当前派单（约 20%）
缓冲（约 15%）
```

### 3.6 中间件落点（可观测 + 安全审计）

| 钩子 | 我们的用途 |
|------|-----------|
| `on_reply` | 记录整个 Manager 会话的 Trace 起点（任务 id 贯穿） |
| `on_model_call` | Trace：每次决策的输入/输出 token、模型 |
| `on_acting` | Metrics：派单次数、各 milestone 时延 |
| `on_check_permission` | 安全审计：只有授权的调度工具可调（审批/回滚敏感） |
| `on_system_prompt` | 注入团队状态/Worker 清单（随动态团队变化刷新） |

---

## 四、与现有设计的关系

| 现有产出 | 对接点 |
|---------|--------|
| `agents/AGENT-IDENTITY.md`（6 个研发 Agent） | Manager 派单的目标 = 这些 Worker 角色 |
| `design/AGENTTEAMS-INTERNALS.md`（Manager-Worker 架构） | 本 loop 是 Manager 侧的行为逻辑，编排通道复用 AgentTeams |
| 里程碑握手协议（第 1 项产出） | 本 loop 的 `write_milestone` / 验证闸门 = 推进握手协议 |
| 动态 Agent 团队研究（DYNAMIC-AGENT-TEAM.md） | `hire_worker`/`fire_worker` 落地"招人/裁员"创新点 |
| 计划第 4 项（协同流程设计 COLLABORATION-DESIGN.md） | 本设计是 Manager 侧的循环实现，第 4 项补充 Team 结构/通信契约 |

---

## 五、落地路径（暂不部署，先源码层实现）

1. **定义一个 `TeamManagerAgent(Agent)` 子类**：继承 AgentScope 的 `Agent`，覆写 `_next_action` 增加团队上下文感知。
2. **注册调度工具集**：用 `Toolkit.add_tool()` 注册 3.3 的 8-9 个调度工具。
3. **中间件**：实现 Trace / Metrics / 权限审计中间件。
4. **接入 AgentTeams**：调度工具内部调 AgentTeams 的 API/CRD（QwenPaw 运行时对接），读 `shared/tasks/{id}/`。
5. **事件驱动**：接 Matrix 消息 → `observe()` 恢复 Manager。

> 当前阶段产出到此（设计文档）。具体写代码放在**计划第 7 项（AgentTeams 代码包）** 统一落地，届时复用本设计。

---

## 六、相关文档索引
- AgentScope 主循环源码：`../references/refs/agentscope/src/agentscope/agent/_agent.py`
- 方案 B 调研：`OPENCLAW-VS-QWENPAW.md`
- AgentTeams 内部机制：`AGENTTEAMS-INTERNALS.md`
- Agent Identity（6 Agent + 里程碑协议）：`../../agents/AGENT-IDENTITY.md`
- 动态 Agent 团队：`../references/theory/DYNAMIC-AGENT-TEAM.md`
- 上下文工程：`../references/theory/CONTEXT-ENGINEERING.md`
