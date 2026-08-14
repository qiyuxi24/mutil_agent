# AgentTeams 交互方式深度分析与优化方案

> 基于全代码库实证分析 + 2025-2026 行业最佳实践调研
> 日期：2026-08-14

---

## 第一部分：当前 AgentTeams 交互方式详细分析

### 1.1 交互架构全景

当前系统采用**双层交互架构**：

```
┌──────────────────────────────────────────────────────────────┐
│  层 1：AgentTeams 原生平台（K8s 声明式编排）                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ Manager  │  │  Team    │  │  Worker  │  │  Human   │     │
│  │   CRD    │  │  CRD     │  │  CRD     │  │  CRD     │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
│       │             │             │             │            │
│  ┌────▼─────────────▼─────────────▼─────────────▼────┐      │
│  │          agentteams-controller (Go)                │      │
│  │    Controller Reconcile Loop + 容器生命周期管理      │      │
│  └────┬──────────────┬──────────────┬────────────────┘      │
│       │              │              │                        │
│  ┌────▼────┐   ┌─────▼──────┐  ┌───▼──────┐                │
│  │ Tuwunel │   │  Higress   │  │  MinIO   │                │
│  │ (Matrix)│   │ AI Gateway │  │  (S3)    │                │
│  └─────────┘   └────────────┘  └──────────┘                │
└──────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│  层 2：自研调度 Loop（Python MAF 实现）                          │
│                                                               │
│  TeamManagerLoop (manager.py)                                 │
│    ├── State Machine (state.py) — PDCA 8 状态 + 里程碑          │
│    ├── Agent Roles (team.py) — 6 职能 Agent 角色定义            │
│    ├── FixerLoop (fixer_loop.py) — Ralph 自我迭代引擎           │
│    ├── ContextManager (context.py) — 70/30 预算 + 三层记忆      │
│    ├── Evaluation (evaluation.py) — 三层评价 + 治理命令          │
│    └── Reverse Gateway (reverse_gateway.py) — LLM API 适配层   │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 交互流程详解

#### 1.2.1 主调度循环（Manager Loop）

交互入口在 `TeamManagerLoop.run()`，核心流程：

```
1. 初始化 ContextManager（32K token 预算，70/30 分配）
2. 读任务 spec → 进入 SPEC_INPUT 状态
3. while 未到 RETROSPECT_DONE:
   a. 查 STATE_EXECUTOR[当前状态] → 确定执行者
   b. 走 ContextManager.start_iteration() 检查 entry 条件
   c. assemble_prompt() 组装上下文 → 走 budget 控制
   d. _run_worker(executor, milestone, prompt) → 派单给 Worker
      - Fixer 特殊路径：走 FixerLoop 内部自我迭代
      - 其他 Worker：一次性 Agent 调用
   e. _verify(stage, worker_output) → 验证闸门判断 PASS/FAIL
   f. PASS → advance() 推进状态机 + 落盘产物 + 上下文卸载
   g. FAIL → 打回重试（最多 3 次）→ 仍失败则跳过
   h. finish_iteration() → 持久化记忆 + 性能报告
4. 输出团队评价报告 + 治理命令
```

#### 1.2.2 Worker 调用方式

**普通 Worker**（`manager.py:_run_worker`）：

```python
# 构造 prompt → 创建 Agent → 一次性调用 → 提取 assistant 回复
worker = Agent(client=self.client, instructions=role.soul, name=role_name)
result = await worker.run(prompt)
```

**Fixer Worker**（特殊路径）：

```python
# 走 FixerLoop 三层循环：生成计划 → 逐步执行(写-验-修-再验) → 最终审查
fixer = FixerLoop(client=self.client, workdir=self.tasks_dir)
return await fixer.run(context=context, milestone=milestone)
```

#### 1.2.3 验证闸门

```
- 确定性兜底：产出为空 → FAIL
- 独立裁判 Agent：tester/releaser 做客观质量判断
- 输出 PASS/FAIL 判定
```

### 1.3 接口调用方法

| 接口层 | 技术 | 调用方式 | 位置 |
|--------|------|---------|------|
| LLM 调用 | OpenAI 兼容 API | `AsyncOpenAI` + `httpx.AsyncClient(trust_env=False)` | `manager.py:69-78` |
| Agent 框架 | MAF (Microsoft Agent Framework) | `Agent(client, instructions, name)` + `agent.run(prompt)` | `manager.py:115-119` |
| 逆向 API 适配 | FastAPI 网关 | `/v1/chat/completions` → `/v2/chat/completions` + SSE 透传 | `reverse_gateway.py` |
| 状态持久化 | JSON 文件 | `TaskState.save()/load()` → `shared/tasks/{id}/state.json` | `state.py:131-137` |
| 记忆持久化 | JSON + Markdown | `ShortTermMemory`/`MediumTermMemory`/`LongTermMemory` | `context.py:286-621` |
| AgentTeams 平台 | `agt` CLI + CRD YAML | `docker exec agentteams-controller agt apply/create/delete/get` | `workers.yaml` |

### 1.4 数据传输格式

| 数据类型 | 格式 | 示例 |
|---------|------|------|
| Agent 角色定义 | Python dataclass (`AgentRole`) | `team.py:20-31` |
| 任务状态 | JSON (`TaskState`) | `state.py:89-100` |
| 里程碑 | Enum + string | `TASK_SPEC_READY` → `ROOT_CAUSE_FOUND` → ... → `RETROSPECT_DONE` |
| Worker 配置 | YAML CRD (`apiVersion: agentteams.io/v1beta1`) | `workers.yaml` |
| Agent 行为准则 | Markdown 文件 (`SOUL.md`/`AGENTS.md`/`HEARTBEAT.md`/`SKILL.md`) | `src/agentteams/workers/*/SOUL.md` |
| LLM 请求/响应 | OpenAI 兼容 JSON + SSE stream | `{"model","messages","stream":true}` |
| 评价报告 | Python dataclass (`AgentScorecard`/`TeamEvaluation`) | `evaluation.py:66-86` |

### 1.5 现有功能限制

| 限制类别 | 具体问题 | 影响 |
|---------|---------|------|
| **通信方式单一** | Worker 之间无直接通信，全程通过 Manager 中转 | 无法实现 Agent 间直接协作（如 Tester 直接向 Fixer 反馈） |
| **无事件驱动** | 纯顺序轮询模式，Manager 调用 Worker 是同步阻塞的 | 无法并行派发多个 Worker，无法异步等待结果 |
| **无 AgentTeams 平台深度集成** | 自研 Loop 与 AgentTeams 平台之间是"平行"关系，走的是 Python MAF 而非 AgentTeams 的 Matrix 房间 | 无法利用 AgentTeams 的 Matrix 可审计房间、Human 介入、CRD 生命周期管理 |
| **Fixer 与其他 Worker 不对称** | Fixer 有 Ralph 自我迭代，其他 Worker 只是一次性调用 | 其他 Worker（如 rootcause、tester）也需要自我修正能力 |
| **上下文管理粗粒度** | 70/30 预算分配是静态的，不适应不同阶段的需求变化 | 某些阶段可能需要更多上下文，另一些阶段可能浪费 |
| **错误处理不完善** | 打回上限后直接跳过，无人工介入升级机制 | 可能导致关键阶段被跳过，闭环不完整 |
| **无正式接口契约** | Worker 调用是 Python 函数调用，无 API 定义 | 无法独立测试、无法替换实现、无法跨进程 |
| **记忆检索简单** | 长期记忆检索是子串匹配，无语义搜索 | 知识复用效率低 |
| **可观测性有限** | 只有 print 输出和性能报告，无结构化日志/Trace | 难以调试、难以审计 |

---

## 第二部分：业内主流交互模式与最佳实践

### 2.1 行业共识：三大编排模式

根据 2025-2026 年行业共识（Anthropic、OpenAI、Microsoft、Cognition 等），多 Agent 系统已收敛到以下模式：

#### 模式一：Orchestrator + 隔离 Subagent（行业主流）

```
Orchestrator（持有全部上下文）
  ├── spawn Subagent A（干净上下文 + 专用 prompt）→ 返回摘要
  ├── spawn Subagent B（干净上下文 + 专用 prompt）→ 返回摘要
  └── 合成结果
```

**代表**：Anthropic Claude Code `Task` tool、OpenAI Agents SDK、Cognition Managed Devins、LangChain Supervisor

**优势**：O(1) 通信复杂度、无上下文污染、可并行

#### 模式二：Supervisor/Worker 层级调度

```
Supervisor → 任务分解 → 路由到 Specialist Worker
  Worker 之间不直接通信，Supervisor 是唯一协调点
```

**代表**：Microsoft AutoGen（已合并到 Agent Framework）、Swarms、CrewAI

**优势**：中心化控制、调试简单、责任明确

#### 模式三：Peer-to-Peer 协作（正在退潮）

```
Agent A ↔ Agent B ↔ Agent C（共享 bus 通信）
```

**劣势**：O(n²) 通信复杂度、上下文膨胀、死锁风险高

**行业趋势**：Anthropic 明确从 peer 转向"脑/手"分离架构，OpenAI 将 nested handoff history 改为 opt-in（减少上下文泄漏），AutoGen 已放弃 GroupChat 为旗舰模式。

### 2.2 A2A 协议（Agent-to-Agent）

2025 年 12 月，OpenAI、Anthropic、Google、Microsoft、AWS 等联合发起 **A2A 协议**（Linux Foundation AI & Agents Foundation），目标是：

- 定义 Agent 间通信、任务移交、分布式工作流编排的开放标准
- 支持跨框架、跨供应商的 Agent 互操作
- 与 MCP（Model Context Protocol）互补：MCP 管 Agent-工具通信，A2A 管 Agent-Agent 通信

### 2.3 对抗式 Agent Team（Adversarial Pattern）

最新趋势（2026 年中），引入 **Leader-Worker-Verifier** 三角对抗：

```
Leader（规划） → Worker（执行） → Verifier（独立校验）
                     ↑                 │
                     └── FAIL 打回 ────┘
```

**核心理念**：用制度化的内部竞争换取产出质量，Verifier 与 Worker 是强对抗关系，不是配合关系。

### 2.4 六大最佳实践总结

| 实践 | 说明 | 来源 |
|------|------|------|
| **Single Response Principle** | 只有主 Agent 对用户说话，Subagent 只做研究不响应 | Microsoft Copilot Studio |
| **Ownership > Job Titles** | 按"责任边界"而非"职称"划分 Agent，每个 Agent 有一个明确的不可合并的责任 | OpenAI Codex 社区 |
| **Model Routing by Responsibility** | 不同 Agent 按实际工作负载配不同模型，不搞一刀切 | OpenAI Codex 社区 |
| **Context Isolation** | 每个 Subagent 干净上下文，只返回摘要，防止上下文污染 | Anthropic |
| **Deterministic Gate Check** | 质量把关不靠 Agent 自评，用编译/测试/静态分析等确定性闸门 | 对抗式 Agent Team |
| **Skill-Value Match** | Skill 只为"当前责任/产出/下一步"增加价值时才加载，不装饰性添加 | OpenAI Codex 社区 |

---

## 第三部分：优化方案

### 3.1 方案总览

基于以上分析，提出**三层优化方案**：

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: AgentTeams 平台深度集成                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Matrix 房间通信 + CRD 生命周期 + Human 介入 + 可审计日志    │  │
│  └───────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: 标准化 Agent 接口层 (AgentInterface)                     │
│  ┌───────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │
│  │ AgentA2A  │  │ AgentBus │  │  EventBus │  │  MetricsBus  │  │
│  │ Protocol  │  │ (pub/sub)│  │ (async)  │  │ (OTel)       │  │
│  └───────────┘  └──────────┘  └──────────┘  └──────────────┘  │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: 升级调度 Loop 核心                                       │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ 异步派单  │  │ 动态预算  │  │ 语义记忆  │  │ 全 Worker     │  │
│  │ 并行执行  │  │ 自适应分配 │  │ 向量检索  │  │ Ralph 迭代    │  │
│  └──────────┘  └───────────┘  └──────────┘  └───────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Layer 1：调度 Loop 核心升级

#### 3.2.1 异步并行派单（替代同步顺序调用）

**现状**：`_run_worker()` 是同步 await，Worker 串行执行。

**优化**：引入 `asyncio.gather` 实现并行派单。

```python
# 新：并行派单接口
async def _dispatch_parallel(self, tasks: list[WorkerTask]) -> list[WorkerResult]:
    """并行派发多个 Worker 任务，等待全部完成。"""
    return await asyncio.gather(
        *[self._run_worker(t.role, t.milestone, t.context) for t in tasks],
        return_exceptions=True
    )
```

**适用场景**：
- RootCause 和 Fixer 可以并行（Fixer 先做 plan，RootCause 做分析）
- 多个 Fixer 实例并行修复不同模块
- 测试和发布准备可以并行

#### 3.2.2 全 Worker Ralph 迭代（替代仅 Fixer 特殊处理）

**现状**：只有 Fixer 走 FixerLoop，其他 Worker 是一次性调用。

**优化**：将 Ralph 迭代抽象为通用 `IterativeWorker` 基类。

```python
class IterativeWorker:
    """通用 Ralph 式自我迭代 Worker 基类。

    每个 Worker 都有：生成计划 → 执行步骤 → 自我校验 → 修正 → 最终审查
    """
    def __init__(self, client, workdir, max_steps=3, max_retries=3):
        self.client = client
        self.workdir = workdir
        self.max_steps = max_steps
        self.max_retries = max_retries

    async def run(self, context: str, milestone: str) -> str:
        plan = await self._generate_plan(context)
        for step in plan.steps:
            result = await self._execute_with_retry(step, plan, context)
        return await self._final_review(plan, all_outputs, context)
```

每个 Worker 覆写 `_validate_step()` 实现角色特定的校验逻辑：
- RootCause：校验根因是否有证据支撑、是否标注不确定性
- Tester：校验测试是否覆盖边界/异常/回归
- Releaser：校验回滚预案是否完整

#### 3.2.3 动态上下文预算分配

**现状**：70/30 比例是静态的。

**优化**：按阶段自适应调整。

```python
STAGE_BUDGET_PROFILE = {
    State.SPEC_INPUT:      {"critical": 0.50, "support": 0.50},  # 聚合需要大量背景
    State.ROOT_CAUSE:      {"critical": 0.75, "support": 0.25},  # 定位需要精确上下文
    State.FIX_APPLY:       {"critical": 0.80, "support": 0.20},  # 编码需要精确规格
    State.TEST_VERIFY:     {"critical": 0.60, "support": 0.40},  # 测试需要广泛覆盖
    State.RELEASE:         {"critical": 0.70, "support": 0.30},
    State.RETROSPECT:      {"critical": 0.40, "support": 0.60},  # 复盘需要全量回顾
}
```

#### 3.2.4 语义记忆检索

**现状**：长期记忆是子串匹配。

**优化**：引入向量嵌入（可选，轻量时用 TF-IDF）。

```python
class SemanticMemory(LongTermMemory):
    """语义记忆检索（基于 embedding 或 TF-IDF）。"""
    def semantic_search(self, query: str, category: str, top_k: int = 5):
        # 优先用 embedding API（如 DeepSeek），降级为 TF-IDF
        if self._embedding_client:
            return self._embedding_search(query, category, top_k)
        return self._tfidf_search(query, category, top_k)
```

### 3.3 Layer 2：标准化 Agent 接口层

#### 3.3.1 AgentInterface 抽象

定义统一的 Worker 接口契约：

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class WorkerContext:
    """Worker 输入上下文。"""
    task_id: str
    spec: str
    milestone: str
    upstream_artifacts: dict[str, str]  # 上游产物路径
    constraints: list[str]

@dataclass
class WorkerResult:
    """Worker 输出结果。"""
    task_id: str
    milestone: str
    status: str           # "PASS" | "FAIL" | "PARTIAL"
    artifact_path: str    # 产物文件路径
    summary: str          # 摘要（用于上下文传递）
    evidence: list[str]   # 证据链
    handoff_to: str       # 交接目标
    metrics: dict         # 性能指标

class AgentInterface(ABC):
    """所有 Worker 必须实现的统一接口。"""

    @abstractmethod
    async def execute(self, ctx: WorkerContext) -> WorkerResult:
        """执行任务，返回结构化结果。"""
        ...

    @abstractmethod
    def get_capabilities(self) -> list[str]:
        """返回该 Agent 的能力列表。"""
        ...

    @abstractmethod
    def get_input_schema(self) -> dict:
        """返回输入 schema（JSON Schema 格式）。"""
        ...

    @abstractmethod
    def get_output_schema(self) -> dict:
        """返回输出 schema（JSON Schema 格式）。"""
        ...
```

#### 3.3.2 AgentBus 消息总线

支持 Worker 间直接通信（受控）：

```python
class AgentBus:
    """Agent 间消息总线（publish/subscribe 模式）。

    与 AgentTeams 的 channelPolicy 对齐：
    - 只有授权的 peer 之间可以通信
    - 消息类型：TASK_HANDOFF / FEEDBACK / QUERY / ALERT
    """

    def __init__(self, channel_policy: dict):
        self._policy = channel_policy  # {agent: {send: [...], receive: [...]}}
        self._subscribers: dict[str, list[callable]] = {}

    async def publish(self, sender: str, receiver: str, msg: AgentMessage):
        """发送消息（受 channelPolicy 约束）。"""
        if not self._can_send(sender, receiver):
            raise PermissionError(f"{sender} cannot send to {receiver}")
        for handler in self._subscribers.get(receiver, []):
            await handler(msg)

    async def subscribe(self, agent: str, handler: callable):
        """订阅消息。"""
        self._subscribers.setdefault(agent, []).append(handler)
```

#### 3.3.3 EventBus 事件驱动

替代当前同步轮询模式：

```python
class EventBus:
    """事件驱动总线。

    事件类型：
    - WORKER_STARTED / WORKER_COMPLETED / WORKER_FAILED
    - MILESTONE_REACHED / MILESTONE_FAILED
    - HUMAN_INTERVENTION_REQUIRED
    - CONTEXT_OVERFLOW_WARNING
    """

    async def emit(self, event: AgentEvent):
        """发射事件。"""
        for handler in self._handlers.get(event.type, []):
            await handler(event)

    def on(self, event_type: str, handler: callable):
        """注册事件处理器。"""
        self._handlers.setdefault(event_type, []).append(handler)
```

### 3.4 Layer 3：AgentTeams 平台深度集成

#### 3.4.1 集成架构

```
自研调度 Loop (Python)          AgentTeams 平台 (Go + Matrix)
┌──────────────────────┐        ┌──────────────────────────────┐
│  TeamManagerLoop     │  agt   │  agentteams-controller       │
│  ├── AgentInterface  │──CLI──▶│  ├── Worker CRD (声明式)      │
│  ├── AgentBus        │        │  ├── Team CRD (房间拓扑)      │
│  └── EventBus        │ Matrix │  └── Human CRD (审计介入)     │
│                      │◀─API──│                              │
│  Worker 容器         │        │  Matrix 房间                  │
│  (QwenPaw/OpenClaw)  │◀─IM──▶│  ├── Leader Room              │
│                      │        │  ├── Team Room                │
│                      │        │  └── Worker DM                │
└──────────────────────┘        └──────────────────────────────┘
```

#### 3.4.2 集成方式

**方式 1：CLI 集成**（当前可用）
```python
class AgentTeamsCLI:
    """通过 agt CLI 与 AgentTeams 平台交互。"""

    async def create_worker(self, name: str, spec: WorkerSpec) -> str:
        cmd = f"docker exec agentteams-controller agt apply -f -"
        yaml_content = spec.to_yaml()
        # 通过 stdin 传入 YAML
        ...

    async def get_worker_status(self, name: str) -> dict:
        cmd = f"docker exec agentteams-controller agt get worker {name} -o json"
        ...

    async def delete_worker(self, name: str) -> None:
        cmd = f"docker exec agentteams-controller agt delete worker {name}"
        ...
```

**方式 2：Matrix API 集成**（推荐）
```python
class MatrixClient:
    """通过 Matrix 协议与 AgentTeams 房间通信。"""

    async def send_message(self, room_id: str, content: str, mention: str = None):
        """向 Matrix 房间发消息（可选 @mention）。"""
        ...

    async def wait_for_response(self, room_id: str, from_user: str, timeout: float = 300):
        """等待指定用户在房间内的回复。"""
        ...

    async def observe_room(self, room_id: str):
        """监听房间消息（用于 Human 介入）。"""
        ...
```

#### 3.4.3 可审计日志

```python
class AuditLogger:
    """结构化审计日志。

    每条日志包含：
    - timestamp / trace_id / span_id
    - agent_id / room_id
    - event_type / action / result
    - human_intervention_flag
    """

    def log_decision(self, agent: str, decision: str, justification: str):
        """记录关键决策。"""
        ...

    def log_handoff(self, from_agent: str, to_agent: str, artifact: str):
        """记录交接。"""
        ...

    def log_human_intervention(self, agent: str, action: str, reason: str):
        """记录人类介入。"""
        ...
```

### 3.5 技术选型

| 组件 | 当前 | 优化后 | 理由 |
|------|------|--------|------|
| Agent 运行时 | MAF (Microsoft Agent Framework) | MAF + AgentScope 双重支持 | MAF 已验证可用，AgentScope 提供更丰富的状态机和中件间 |
| LLM 调用 | `AsyncOpenAI` + `httpx` | 同上 + 增加重试/限流/fallback | 生产可用性 |
| 状态存储 | JSON 文件 | JSON + SQLite（可选） | 文件足够轻量，SQLite 支持并发查询 |
| 记忆检索 | 子串匹配 | TF-IDF + 可选 embedding | 渐进式升级，不引入重依赖 |
| 消息通信 | 无（函数调用） | AgentBus + EventBus | 支撑 Worker 间直接通信 |
| 平台集成 | 无（平行运行） | agt CLI + Matrix SDK | 打通 AgentTeams 生态 |
| 可观测性 | print 语句 | structlog + OTel（可选） | 结构化日志 + 分布式追踪 |
| 配置管理 | 环境变量 | YAML + env | 声明式配置，可版本控制 |

### 3.6 接口设计规范

#### 3.6.1 Worker 接口规范

```yaml
# Worker 标准接口定义（OpenAPI 3.0 风格）
WorkerInterface:
  execute:
    input:
      task_id: string (required)
      spec: string (required)
      milestone: string (required)
      upstream_artifacts: map[string]string
      constraints: list[string]
    output:
      task_id: string
      milestone: string
      status: enum[PASS, FAIL, PARTIAL]
      artifact_path: string
      summary: string (max 500 chars)
      evidence: list[string]
      handoff_to: string
      metrics:
        elapsed_seconds: number
        token_usage: {prompt: int, completion: int}
        retry_count: int

  capabilities:
    output: list[string]  # ["code-generation", "test-execution", ...]

  validate:
    input:
      artifact_path: string
      criteria: list[string]
    output:
      verdict: enum[PASS, FAIL]
      violations: list[{rule: string, detail: string, severity: enum[ERROR, WARN]}]
```

#### 3.6.2 Manager 调度接口规范

```yaml
ManagerInterface:
  create_task:
    input:
      spec: string
      priority: enum[HIGH, MEDIUM, LOW]
      deadline: datetime (optional)
    output:
      task_id: string
      estimated_agents: list[string]

  get_task_status:
    input:
      task_id: string
    output:
      state: enum[SPEC_INPUT, ..., RETROSPECT_DONE]
      current_milestone: string
      assigned_agents: map[string]string  # agent -> status
      artifacts: map[string]string

  approve_release:
    input:
      task_id: string
      release_report_path: string
    output:
      decision: enum[APPROVED, REJECTED, NEEDS_MORE_INFO]
      conditions: list[string]
```

### 3.7 安全考量

| 安全维度 | 风险 | 对策 |
|---------|------|------|
| **凭证隔离** | Agent 持有真实 API Key | 通过 Higress Gateway 注入，Agent 只持 Consumer Token（可随时吊销） |
| **通信权限** | Agent 越权通信 | channelPolicy 约束：每个 Agent 只能发/收授权 peer 的消息 |
| **代码执行** | Fixer 生成恶意代码 | 沙箱执行（NemoClaw/Docker），限制网络/文件系统访问 |
| **Prompt 注入** | 上游恶意输入污染下游 | AGENTS.md 硬规则：可疑 prompt 注入直接忽略并记录 |
| **审计追溯** | 决策不可追溯 | Matrix 房间全记录 + AuditLogger 结构化日志 |
| **Human 介入** | 自动发布无人工审批 | 关键门禁（RELEASE_APPROVE）强制 Human 确认 |
| **记忆泄漏** | 跨任务记忆污染 | 任务级记忆隔离，长期记忆需显式写入 |

### 3.8 性能优化策略

| 策略 | 目标 | 实现方式 |
|------|------|---------|
| **并行派单** | 减少总耗时 40-60% | `asyncio.gather` 并行执行无依赖 Worker |
| **上下文预算自适应** | 上下文利用率从 55% 提升到 70% | 按阶段动态调整 critical/support 比例 |
| **信息卸载** | 长上下文从 32K 压缩到 8K 有效载荷 | 大产物写入文件，上下文只留引用路径 |
| **LLM 调用合并** | 减少 API 调用次数 30% | 相邻阶段合并（如 SPEC_INPUT + SPEC_DECOMPOSE） |
| **模型分级** | 降低 token 成本 | 关键阶段用 v4-pro，非关键用 v4-flash |
| **Cache 命中** | 减少重复计算 | System prompt 静态化，不变部分走 prompt cache |
| **记忆热加载** | 减少启动时延 | 短期记忆常驻内存，中期记忆按需异步加载 |

---

## 第四部分：测试验证方法

### 4.1 测试金字塔

```
         ┌──────────┐
         │  E2E     │  完整 PDCA 闭环测试（mock 模式 + 真实 API）
         │ 5-10 条  │
        ┌┴──────────┴┐
        │  集成测试   │  Manager→Worker 交互 / FixerLoop 迭代 / 验证闸门
        │  15-20 条  │
       ┌┴────────────┴┐
       │   单元测试    │ 状态机 / 评价器 / 上下文预算 / 记忆 / 接口
       │   30-40 条   │
      └───────────────┘
```

### 4.2 单元测试（已有基础，需补全）

已有自检（可直接运行）：
- `context.py:1209-1325` — ContextBudget、三层记忆、IterationProtocol、ContextManager、PerformanceMetrics 自检
- `evaluation.py:357-372` — 评价器自检

需补全的单元测试：

```python
# test_state.py
def test_state_transitions():
    """测试状态机正向流转和打回。"""
    ts = TaskState(task_id="test-001")
    assert ts.state == State.SPEC_INPUT
    ts.advance(Milestone.TASK_SPEC_READY, verdict="PASS", by="aggregator")
    assert ts.state == State.SPEC_DECOMPOSE
    # 测试打回
    ts.advance(Milestone.TEST_FAILED, verdict="FAIL", by="tester")
    assert ts.state == State.FIX_APPLY

# test_agent_interface.py
def test_worker_context_serialization():
    """测试 WorkerContext 的序列化/反序列化。"""
    ctx = WorkerContext(task_id="t1", spec="fix login", milestone="FIX_APPLIED")
    d = ctx.to_dict()
    ctx2 = WorkerContext.from_dict(d)
    assert ctx2.task_id == "t1"

# test_agent_bus.py
def test_channel_policy_enforcement():
    """测试通信权限约束。"""
    bus = AgentBus({"fixer": {"send": ["tester"], "receive": ["tester", "rootcause"]}})
    assert bus._can_send("fixer", "tester") is True
    assert bus._can_send("fixer", "aggregator") is False  # 未授权
```

### 4.3 集成测试

```python
# test_fixer_loop_integration.py
async def test_fixer_three_step_iteration():
    """测试 Fixer 的 Plan→Execute→Validate→Retry 完整流程。"""
    fixer = FixerLoop(client=mock_client, workdir=tmpdir, mock=True)
    result = await fixer.run(context="login bug: null pointer", milestone="FIX_APPLIED")
    assert "FIX_APPLIED" in result
    assert "STEP_1_DONE" in result

# test_manager_worker_interaction.py
async def test_manager_dispatches_to_aggregator():
    """测试 Manager 派单给 Aggregator 的完整链路。"""
    mgr = TeamManagerLoop(task_id="t1", spec="login bug", workdir=tmpdir, mock=True)
    result = await mgr._run_worker("aggregator", "TASK_SPEC_READY", "test context")
    assert "TASK_SPEC_READY" in result or "缺陷聚合员" in result

# test_verification_gate.py
async def test_verify_rejects_empty_output():
    """测试验证闸门拒绝空输出。"""
    mgr = TeamManagerLoop(task_id="t1", spec="test", workdir=tmpdir, mock=False)
    verdict, detail = await mgr._verify(State.FIX_APPLY, "")
    assert verdict == "FAIL"
```

### 4.4 E2E 测试（Mock 模式）

```python
# test_e2e_pdca_closure.py
async def test_full_pdca_closure_mock():
    """Mock 模式完整 PDCA 闭环，秒级跑完。"""
    mgr = TeamManagerLoop(task_id="e2e-001", spec="修复登录页面空指针异常", workdir=tmpdir, mock=True)
    result = await mgr.run(max_stages=8, max_iter_per_stage=3)
    assert result.state == State.RETROSPECT
    assert Milestone.RETROSPECT_DONE.value in result.milestones

# test_e2e_dynamic_hiring.py
async def test_dynamic_worker_hiring():
    """测试动态招人场景。"""
    mgr = TeamManagerLoop(task_id="e2e-002", spec="security audit", workdir=tmpdir, mock=True)
    # 动态添加安全审查 Agent
    mgr.state.executors[State.FIX_APPLY] = "security_auditor"
    result = await mgr.run()
    assert "security_auditor" in str(result.artifacts)
```

### 4.5 质量评估标准

#### 4.5.1 功能正确性指标

| 指标 | 目标值 | 测量方法 |
|------|--------|---------|
| 闭环完成率 | ≥ 95% | `(完成的闭环任务数 / 总任务数) × 100%` |
| 里程碑推进准确率 | ≥ 90% | `(正确推进的里程碑 / 总里程碑) × 100%` |
| 打回有效率 | ≥ 70% | `(打回后确实改进的 / 总打回次数) × 100%` |
| 验证闸门准确率 | ≥ 85% | `(正确判定 PASS/FAIL / 总判定) × 100%` |

#### 4.5.2 性能指标

| 指标 | 当前基线 | 目标值 |
|------|---------|--------|
| 单任务平均耗时 | ~15-20 min | ≤ 10 min（并行优化后） |
| 上下文利用率 | ~55% | 65-75% |
| 记忆留存率 | ~30% | ≥ 50% |
| API 调用次数/任务 | ~12-15 次 | ≤ 10 次（合并优化后） |
| Token 消耗/任务 | ~50K | ≤ 40K |

#### 4.5.3 可观测性指标

| 指标 | 目标值 |
|------|--------|
| 结构化日志覆盖率 | 100%（所有关键决策点） |
| Trace 完整性 | 100%（task_id 贯穿全链路） |
| 审计日志留存 | 90 天以上 |

#### 4.5.4 代码质量指标

| 指标 | 目标值 |
|------|--------|
| 单元测试覆盖率 | ≥ 80% |
| 接口契约覆盖率 | 100%（所有 Worker 实现 AgentInterface） |
| 类型注解覆盖率 | ≥ 90% |

---

## 第五部分：实施路线图

### Phase 1：核心升级（1-2 周）

1. 定义 `AgentInterface` 抽象基类
2. 将 6 个 Worker 改造为实现 `AgentInterface`
3. 实现 `AgentBus` 消息总线
4. 将 `_run_worker` 升级为异步并行派单
5. 将 Ralph 迭代推广到所有 Worker
6. 补全单元测试

### Phase 2：集成增强（1-2 周）

1. 实现 `AgentTeamsCLI` 集成适配器
2. 实现 `MatrixClient` 房间通信
3. 实现 `AuditLogger` 结构化审计
4. 实现动态上下文预算分配
5. 引入语义记忆检索（TF-IDF）
6. 补全集成测试 + E2E 测试

### Phase 3：生产加固（1 周）

1. 错误处理完善（升级机制、降级策略）
2. 性能压测与调优
3. 安全审计
4. 文档与运行手册

---
## 第六部分：交互优化实施记录（2026-08-14）

> 基于以上分析，已完成的交互层实现。遵循"复用现有组件、最小改动、渐进增强"原则。

### 6.1 实施总览

```
用户 ──┬── CLI (run.py) ──┬── Rich Dashboard (终端) ─┐
      │                  │                          │
      │                  ├── Web Dashboard (SSE) ────┤
      │                  │                          │
      │                  ├── InteractiveShell ───────┤
      │                  │                          │
      │                  └── AgentTeamsLoop ─────────┤
      │                       │                     │
      │                  EventBus ◄──────────────────┘
      │                       │
      └── Matrix 群聊 ── AgentTeams 平台 ── 6 个 Worker
```

### 6.2 新增文件

| 文件 | 功能 | 复用的已有组件 |
|------|------|-------------|
| `src/loop/dashboard.py` | **Rich 终端仪表盘** — 实时 PDCA 流水线 + Worker 状态面板 + 事件流 + 上下文预算仪表盘。自动检测 Rich 库可用性，不可用时降级为 ANSI 纯文本模式。 | EventBus、TaskState、ContextManager |
| `src/loop/web_dashboard.py` | **Web SSE 仪表盘** — 浏览器实时看板（SSE 事件推送），含 PDCA 进度、Worker 卡片、事件流、人工审批按钮。零额外依赖自动降级。 | EventBus、TaskState、ContextManager |

### 6.3 修改文件

| 文件 | 改动内容 |
|------|---------|
| `src/run.py` | **交互式 CLI 增强** — 新增 `--dashboard` / `--web` / `--interactive` 参数；`InteractiveShell` 命令系统（status/workers/events/pause/resume）；自动接入仪表盘 |
| `src/loop/agentteams_loop.py` | **EventBus 事件发射** — orchestrated 和 mock 模式均在关键节点发射事件（WORKER_STARTED/COMPLETED/FAILED、MILESTONE_REACHED/FAILED） |
| `src/loop/agent_bus.py` | **便捷方法补充** — 新增 `milestone_failed`、`worker_failed`、`task_started`、`task_completed` 便捷方法 |

### 6.4 使用方式

```powershell
# 1. 纯命令行（原有方式不变）
python run.py "修复登录页面空指针异常"

# 2. Rich 终端仪表盘（实时 PDCA 进度 + Worker 面板）
python run.py --dashboard "你的任务"

# 3. Web 浏览器仪表盘（SSE 实时推送 + 审批按钮）
python run.py --web "你的任务"
# 浏览器打开 http://127.0.0.1:8080

# 4. 交互式命令模式（status / workers / events / pause）
python run.py --interactive

# 5. 仪表盘 + 交互命令
python run.py --dashboard --interactive

# 6. Mock 演示（秒级跑完完整闭环）
python run.py --mock --dashboard "演示任务"
```

### 6.5 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 仪表盘实现方式 | Rich 终端 + Web SSE 双模 | 终端零依赖（开发时最方便），Web 可远程监控（生产中需要） |
| 事件驱动方式 | 扩展现有 EventBus | 已有完整事件类型定义和 pub/sub 机制，不重复造轮子 |
| Rich 依赖处理 | 可选依赖 + 自动降级 | `PlainDashboard` 提供 ANSI 纯文本模式，不强制安装 Rich |
| Web 依赖处理 | 可选依赖 + 自动降级 | uvicorn/starlette 不存在时打印提示，不影响核心功能 |
| 仪表盘生命周期 | 独立 start/stop | 与 AgentTeamsLoop 解耦，可独立开关 |
| 事件发射位置 | AgentTeamsLoop 内部 | 就近原则，不额外抽象，事件语义清晰 |

### 6.6 待办事项

- [ ] **Rich 仪表盘 Live 模式** — 当前 mock 模式下 RichDashboard 的 Live screen 渲染被 mock 输出覆盖，需在真实 AgentTeams 环境验证全屏刷新效果
- [ ] **Web 仪表盘真实集成测试** — 需安装 uvicorn/starlette 后在 mock 模式验证完整浏览器交互
- [ ] **Matrix 房间消息同步到仪表盘** — 当前仪表盘事件来自 EventBus，AgentTeams 平台侧 Matrix 房间消息尚未接入事件流
- [ ] **桌面通知** — Worker 完成/失败时触发系统通知（`plyer` 或 `win10toast`）
- [ ] **实时上下文预算仪表盘** — 当前 ContextManager 的 snapshot 数据不够实时，需增加推送机制
- [ ] **暂停/恢复功能落地** — InteractiveShell 的 pause/resume 命令当前仅提示，需对接 AgentTeams 平台的 `agt update worker --state` 能力

| 文件 | 作用 |
|------|------|
| `src/loop/manager.py` | Manager 调度 Loop 主入口 |
| `src/loop/state.py` | PDCA 闭环状态机（8 状态 + 里程碑 + 打回） |
| `src/loop/team.py` | 6 个研发 Agent 角色定义 |
| `src/loop/fixer_loop.py` | Fixer Ralph 自我迭代引擎 |
| `src/loop/context.py` | 上下文工程（70/30 预算 + 三层记忆 + 迭代协议） |
| `src/loop/evaluation.py` | Agent 成员评价器（三层评价模型） |
| `src/loop/reverse_gateway.py` | 逆向 API 适配层（OpenAI 兼容网关） |
| `src/agentteams/workers.yaml` | AgentTeams Worker CRD 声明 |
| `src/agentteams/workers/*/SOUL.md` | 各 Worker 的人格/行为准则 |
| `design/AGENTTEAMS-INTERNALS.md` | AgentTeams 内部机制详解 |
| `design/AGENTTEAMS-RUNBOOK.md` | AgentTeams 落地运行手册 |
| `design/COLLABORATION-DESIGN.md` | 协同流程设计（Team 结构 + 通信契约） |
| `design/MANAGER-LOOP-DESIGN.md` | Manager Loop 设计方案 |