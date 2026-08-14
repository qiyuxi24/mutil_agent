# AgentTeams 迁移 TODO

> 基于 design/AGENTTEAMS-INTERACTION-ANALYSIS.md 三层架构
> 迁移完成日期：2026-08-14
> 当前状态：Layer 1/2/3 核心功能已实现

---

## 迁移完成摘要

### 已完成（Phase 1-3 核心）

| 阶段 | 模块 | 状态 | 说明 |
|------|------|------|------|
| 1.1 | `iterative_worker.py` | ✅ 已完成 | 通用 IterativeWorker 基类 + 3 个预置子类（RootCause/Tester/Releaser） |
| 1.2 | `agentteams_loop.py` | ✅ 已完成 | `_dispatch_parallel()` 异步并行派单 + `_run_iterative_worker()` 集成 |
| 1.3 | `context.py` | ✅ 已完成 | DynamicBudgetAllocator 按阶段自适应预算（8 阶段配置） |
| 1.4 | `context.py` | ✅ 已完成 | SemanticMemorySearch 语义记忆检索（TF-IDF + embedding 降级） |
| 2.1 | `agent_interface.py` | ✅ 已完成 | AgentInterface ABC + WorkerContext/WorkerResult + 6 个 Worker 实现 |
| 2.2 | `agent_bus.py` | ✅ 已完成 | AgentBus pub/sub 消息总线（channelPolicy 权限约束） |
| 2.3 | `agent_bus.py` | ✅ 已完成 | EventBus 事件驱动（12 种事件类型 + 同步/异步回调） |
| 3.3 | `agentteams_client.py` | ✅ 已完成 | Human 介入接口（approve_release/request_human_intervention/send_human_feedback/override_worker_state/get_human_tasks） |

### 保留的已有功能（全部保留）

| 模块 | 功能 | 说明 |
|------|------|------|
| `state.py` | PDCA 8 状态机 + 里程碑握手 | 确定性协议层，完整保留 |
| `team.py` | 6 个 Agent 角色定义 | soul + 准则 + 里程碑，完整保留 |
| `context.py` | ContextBudget 70/30 预算 + 三层记忆 + IterationProtocol + PerformanceMetrics | 完整保留，新增动态预算 + 语义搜索 |
| `evaluation.py` | 三层评价模型（合格度/贡献度/治理） | 完整保留 |
| `agentteams_client.py` | AgtCLI + Matrix 协议 + Worker 管理 + 任务派发 + 里程碑追踪 | 完整保留，新增 Human 介入 |
| `agentteams_loop.py` | delegated/orchestrated 双模式 + 验证闸门 + 确定性脚本 | 完整保留，新增并行派单 + IterativeWorker |
| `fixer_loop.py` | Fixer Ralph 自我迭代（已归档） | 保留作参考，功能由 iterative_worker 继承 |
| `manager.py` | TeamManagerLoop（已归档） | 保留作参考，功能由 agentteams_loop 继承 |

---

## Phase 1: 调度 Loop 核心升级（Layer 1）

### 1.1 全 Worker Ralph 迭代
- [x] 将 `fixer_loop.py` 的 Ralph 自我迭代机制抽象为通用 `IterativeWorker` 基类
- [x] 每个 Worker 都支持：生成计划 → 执行步骤 → 自我校验 → 修正 → 最终审查
- [x] 每个 Worker 覆写 `_validate_step()` 实现角色特定校验：
  - RootCause: 校验根因是否有证据支撑、是否标注不确定性
  - Tester: 校验测试是否覆盖边界/异常/回归
  - Releaser: 校验回滚预案是否完整
- [x] 文件：`src/loop/iterative_worker.py`

### 1.2 异步并行派单
- [x] `_dispatch_parallel()` 用 `asyncio.gather` 并行派发无依赖 Worker
- [x] 适用场景：RootCause + Fixer 并行、多 Fixer 并行修复不同模块、测试和发布准备并行
- [x] 更新：`src/loop/agentteams_loop.py`

### 1.3 动态上下文预算分配
- [x] 按阶段自适应调整 critical/support 比例（替代静态 70/30）
- [x] 各阶段预算配置：
  - SPEC_INPUT: 50/50（聚合需要大量背景）
  - ROOT_CAUSE: 75/25（定位需要精确上下文）
  - FIX_APPLY: 80/20（编码需要精确规格）
  - TEST_VERIFY: 60/40（测试需要广泛覆盖）
  - RELEASE: 70/30
  - RETROSPECT: 40/60（复盘需要全量回顾）
- [x] 更新：`src/loop/context.py`（新增 DynamicBudgetAllocator 类）

### 1.4 语义记忆检索
- [x] 长期记忆检索从子串匹配升级为语义搜索
- [x] 优先用 embedding API（DeepSeek），降级为 TF-IDF
- [x] 更新：`src/loop/context.py`（新增 SemanticMemorySearch 类）

---

## Phase 2: 标准化 Agent 接口层（Layer 2）

### 2.1 AgentInterface 抽象
- [x] 定义 `WorkerContext` / `WorkerResult` 数据类（统一 I/O 契约）
- [x] 定义 `AgentInterface` ABC（execute / get_capabilities / get_input_schema / get_output_schema）
- [x] 6 个 Worker 实现 AgentInterface（AggregatorAgent / RootCauseAgent / FixerAgent / TesterAgent / ReleaserAgent / RetrospectorAgent）
- [x] 文件：`src/loop/agent_interface.py`

### 2.2 AgentBus 消息总线
- [x] publish/subscribe 模式，支持 Worker 间直接通信
- [x] channelPolicy 约束：只有授权 peer 之间可通信（PDCA 上下游默认授权）
- [x] 消息类型：TASK_HANDOFF / FEEDBACK / QUERY / ALERT
- [x] 文件：`src/loop/agent_bus.py`

### 2.3 EventBus 事件驱动
- [x] 替代同步轮询，支持事件驱动
- [x] 事件类型：WORKER_STARTED / WORKER_COMPLETED / MILESTONE_REACHED / HUMAN_INTERVENTION_REQUIRED / ERROR_OCCURRED 等 12 种
- [x] 文件：`src/loop/agent_bus.py`（与 AgentBus 同文件）

---

## Phase 3: AgentTeams 平台深度集成（Layer 3）

### 3.1 MatrixClient 房间通信
- [ ] 通过 Matrix 协议直接与 AgentTeams 房间通信（替代 agt CLI 的间接方式）
- [ ] send_message / wait_for_response / observe_room
- [ ] 使用 `matrix-nio` 或 `matrix_client` 库
- [ ] 文件：待创建 `src/loop/matrix_client.py`
- **说明**：当前 `agentteams_client.py` 已通过 Matrix HTTP API 实现了房间通信，此任务为可选优化

### 3.2 AuditLogger 结构化审计
- [ ] 结构化日志：timestamp / trace_id / agent_id / room_id / event_type / action / result
- [ ] log_decision / log_handoff / log_human_intervention
- [ ] 使用 `structlog` 库
- [ ] 文件：待创建 `src/loop/audit_logger.py`
- **说明**：当前 `agent_bus.py` 的 EventBus 已提供事件历史记录，此任务为可选增强

### 3.3 AgentTeamsCLI 集成（已完成）
- [x] `AgentTeamsClient` 封装 agt CLI（create/update/delete/get worker/team）
- [x] 任务派发与里程碑追踪
- [x] 治理命令执行
- [x] Human 介入接口（approve_release / request_human_intervention / send_human_feedback / override_worker_state / get_human_tasks）

---

## Phase 4: 测试验证

### 4.1 单元测试
- [ ] `test_state.py` — 状态机正向流转 + 打回
- [ ] `test_agent_interface.py` — WorkerContext 序列化/反序列化
- [ ] `test_agent_bus.py` — channelPolicy 权限约束
- [ ] `test_iterative_worker.py` — 通用 Ralph 迭代

### 4.2 集成测试
- [ ] `test_fixer_loop_integration.py` — Fixer 完整迭代流程
- [ ] `test_manager_worker_interaction.py` — Manager→Worker 派单链路
- [ ] `test_verification_gate.py` — 验证闸门判断

### 4.3 E2E 测试
- [ ] `test_e2e_pdca_closure.py` — Mock 模式完整 PDCA 闭环
- [ ] `test_e2e_dynamic_hiring.py` — 动态招人场景

---

## 文件清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `src/loop/agentteams_client.py` | ✅ 已完成 | AgentTeams 平台客户端（agt CLI 封装 + Matrix 协议 + Human 介入） |
| `src/loop/agentteams_loop.py` | ✅ 已完成 | AgentTeams 原生调度循环（delegated/orchestrated + 并行派单 + IterativeWorker） |
| `src/loop/agentteams/manager/SOUL.md` | ✅ 已完成 | PDCA Manager 编排指令 |
| `src/loop/__init__.py` | ✅ 已完成 | 懒加载 + 导出所有新模块 |
| `src/loop/state.py` | ✅ 已完成 | PDCA 闭环确定性状态机（无变更） |
| `src/loop/team.py` | ✅ 已完成 | 6 个研发 Agent 角色定义（无变更） |
| `src/loop/context.py` | ✅ 已完成 | 上下文工程（新增 DynamicBudgetAllocator + SemanticMemorySearch） |
| `src/loop/evaluation.py` | ✅ 已完成 | Agent 成员评价器（无变更） |
| `src/loop/iterative_worker.py` | ✅ 新创建 | 通用 IterativeWorker 基类 + RootCause/Tester/Releaser 预置子类 |
| `src/loop/agent_interface.py` | ✅ 新创建 | AgentInterface + WorkerContext/WorkerResult + 6 个 Worker 实现 |
| `src/loop/agent_bus.py` | ✅ 新创建 | AgentBus + EventBus |
| `src/loop/matrix_client.py` | ⬜ 可选 | Matrix 协议房间通信（独立客户端，当前功能已由 agentteams_client 覆盖） |
| `src/loop/audit_logger.py` | ⬜ 可选 | 结构化审计日志（当前功能已由 EventBus 事件历史覆盖） |
| `src/loop/manager.py` | 📦 已归档 | 旧 TeamManagerLoop（MAF 底座，保留作参考） |
| `src/loop/fixer_loop.py` | 📦 已归档 | 旧 FixerLoop（MAF 底座，功能由 iterative_worker 继承） |
| `tests/` | ⬜ 待创建 | 测试目录 |

---

## 架构总览（迁移后）

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 3: AgentTeams 平台深度集成                              │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ agentteams_client │  │ Matrix 协议   │  │ Human 介入   │   │
│  │ (agt CLI + API)  │  │ (房间通信)    │  │ (审批/反馈)  │   │
│  └────────┬─────────┘  └──────┬───────┘  └──────┬───────┘   │
│           │                   │                  │           │
├───────────┼───────────────────┼──────────────────┼───────────┤
│  Layer 2: 标准化 Agent 接口层  │                  │           │
│  ┌────────▼───────────────────▼──────────────────▼───────┐   │
│  │                 AgentTeamsLoop (调度引擎)              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │   │
│  │  │ AgentInterface│  │  AgentBus    │  │  EventBus  │  │   │
│  │  │ (6 Worker)   │  │  (pub/sub)   │  │  (事件驱动) │  │   │
│  │  └──────────────┘  └──────────────┘  └────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  Layer 1: 调度 Loop 核心升级                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ┌────────────────┐  ┌──────────────┐  ┌──────────┐ │   │
│  │  │ IterativeWorker │  │ 动态预算分配  │  │ 语义记忆  │ │   │
│  │  │ (Ralph 迭代)   │  │ (按阶段自适应) │  │ (TF-IDF)  │ │   │
│  │  └────────────────┘  └──────────────┘  └──────────┘ │   │
│  │  ┌────────────────┐  ┌──────────────┐               │   │
│  │  │ 异步并行派单    │  │ 三层记忆架构  │               │   │
│  │  │ (asyncio)      │  │ (短/中/长期)  │               │   │
│  │  └────────────────┘  └──────────────┘               │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  共享协议层（不变）                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ state.py │  │ team.py  │  │ eval.py  │  │ context  │   │
│  │ (状态机)  │  │ (角色)   │  │ (评价)   │  │ (工程)   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└──────────────────────────────────────────────────────────────┘
```