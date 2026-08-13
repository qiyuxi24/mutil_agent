# 调研结论：OpenClaw vs QwenPaw/AgentScope —— 我们该用哪个做 Manager loop？

> 目的：回答用户核心问题——"听说 OpenClaw 代码不优秀、有大量浪费，是否属实？需不需要自己重新写一个 Agent？"
> 方法：基于源码实证 + 多篇 OpenClaw 深度源码解读文章交叉验证，非道听途说。
> 结论先行：**"OpenClaw 代码烂/大量浪费"这个说法被夸大了。OpenClaw 架构设计优秀，但确实有"定位不匹配 + 复杂度偏高"的问题。不必从零重写，但推荐走 Python 路线（QwenPaw/AgentScope）避开它。**
> 日期：2026-08-06

---

## 0. 关键背景（先纠正一个前提）

**AgentTeams 的 Manager 有两条运行时路线，不是只有 OpenClaw：**

| 运行时 | 语言 | 内存 | AgentTeams 角色 |
|--------|------|------|----------------|
| **OpenClaw** | Node.js | ~500MB | Manager / Worker 均可（默认） |
| **QwenPaw（CoPaw）** | **Python** | ~150MB | Manager / Worker 均可（轻量，AgentTeams 推荐） |

> 且 AgentTeams 用的 OpenClaw 是 **`higress-group/openclaw` 的 fork**（固定 commit `2f35b6f`），不是社区版 `openclaw/openclaw` 的完整功能。这进一步说明：OpenClaw 对 AgentTeams 只是"一个可选运行时"，不是绑死的基础设施。

---

## 一、OpenClaw 的真实代码质量（实证）

### 1.1 架构：三层嵌套循环（优秀）

OpenClaw 的 agent loop 是**三层嵌套**，职责分层清晰：
```
外循环 run.ts (1502行)    —— 整个任务兜底：重试/failover/auth轮转/队列管理
├─ 中循环 attempt.ts (2096行) —— 单次 API 调用：加载session/构建prompt/工具集/发请求
│  └─ 内循环 subscribe —— 流式事件：文本分块/工具执行/消息去重
```

**亮点**（来自多篇源码解读的一致评价）：
- **双层队列**：优雅解决"session 内串行 + session 间并行"的矛盾
- **六种错误恢复策略**：rate limit/auth/context overflow/overloaded/billing/thinking 各有明确恢复路径
- **渐进式 context overflow 恢复**：先截断→再 compaction→再重试（低成本到高成本）
- **弹性容错**：认证轮换、模型回退、指数退避重试、空闲超时断路器

### 1.2 是否"有大量浪费"？—— 部分属实，但被夸大

| 真实短板 | 说明 |
|---------|------|
| **单文件过大** | attempt.ts 2096行、run.ts 1502行，超合理复杂度 |
| **测试覆盖率偏低** | 核心模块仅 40-50%（爆发式增长导致，长期隐患） |
| **状态管理器偏多** | run-loop.ts 有 7 个状态管理器（usage/recovery/retry/timeout/compaction/failover），部分可合并 |
| **定位不匹配** | 它是"个人 AI 助手"，带大量你用不到的 Channel（WhatsApp/Telegram/飞书）适配、UI、个人助理功能 |
| **安全层技术债** | 应用层沙箱（非 OS 级），有 CVE 沙箱逃逸 |

**但合理的地方**：
- run-loop.ts 核心 loop 仅 **669 行**，属于"中等规模，不算臃肿"
- 复杂度是**生产级 Agent 的刚需**（LLM 调用天然不可靠，必须有容错），不是无意义的浪费
- 状态管理器虽多但职责单一（符合 SRP）

### 1.3 综合判断（来自源码解读的结论）

> "架构设计优秀，实现细节有优化空间。三层抽象正确且成熟，但单文件行数过多暴露重构需求。"
> "代码不算臃肿，但确实复杂。复杂度是生产环境的必然产物。在可维护性与精简度之间，OpenClaw 选择了前者，取舍合理。"

**一句话**：**OpenClaw 不是烂代码，是"重而全"的代码。** 它的核心 loop 设计是优秀的，主要问题是你用不上它的"全"（个人助手功能），以及测试覆盖率偏低。

---

## 二、QwenPaw/AgentScope 的真实情况（Python 路线）

### 2.1 AgentScope：模块化清晰，agent loop 是显式状态机

AgentScope（阿里通义）的 Agent 核心类（`_agent.py` 3382行）采用**显式 ReAct 状态机**：

```python
# _utils.py 中定义的"下一步动作"状态
class Acting(BaseModel):   # 下一步：执行工具调用
    tool_calls: list[ToolCallBlock]
class Reasoning(BaseModel): # 下一步：再次调用模型
    hint: HintBlock | None = None
    tool_choice: ToolChoice | None = None
class Exit(BaseModel):     # 下一步：结束回复
    exit_msg: Msg
```

**agent loop = 一个 while 循环，不断判断"下一步是 Acting / Reasoning / Exit"** —— 这是非常清晰、可读、易改的循环结构。

模块划分高度清晰：
```
agentscope/
├── agent/       # Agent 核心（_agent.py, _config.py）
├── model/       # LLM 抽象（多 provider）
├── message/     # 消息/内容块
├── tool/        # Toolkit 工具
├── memory/      # 记忆
├── permission/  # 权限引擎（PermissionEngine/Rule）
├── middleware/  # 中间件
├── workspace/   # 工作区
├── rag/         # 知识库检索
├── skill/       # 技能
├── event/       # 事件（流式）
└── state/       # 状态
```

### 2.2 QwenPaw/CoPaw：worker daemon 清晰

QwenPaw worker（`worker.py`）是一个清晰的 daemon：
- 生命周期管理（start/stop/run）
- MinIO 文件同步（mirror/sync_loop/push_loop）
- openclaw.json → 运行时配置的 bridge
- Matrix 通道安装
- 健康检查（liveness/readiness）

### 2.3 Python 路线的优势

- **Agent loop 可读、可改**：显式状态机（Acting/Reasoning/Exit），比 OpenClaw 的三层嵌套 + 7状态管理器更易理解
- **内存低**（150MB vs 500MB）
- **Python 生态**：后续写 Skill/工具/集成更顺
- **模块化**：model/tool/memory/permission/rag 等可独立替换扩展

---

## 三、直接对比：哪个更适合"做我们的研发 Manager loop"

| 维度 | OpenClaw (Node) | QwenPaw/AgentScope (Python) |
|------|----------------|----------------------------|
| agent loop 结构 | 三层嵌套 + 7状态管理器，复杂 | 显式状态机（Acting/Reasoning/Exit），清晰 |
| 可改性 | 中（逻辑复杂，改需谨慎） | 高（状态机易扩展） |
| 定位匹配度 | 低（个人AI助手，带多余Channel） | **高**（Agent 开发框架，正是要写 Agent loop） |
| 测试覆盖率 | 40-50%（偏低） | 更好（AgentScope 有较全测试） |
| 内存 | ~500MB | ~150MB |
| 语言生态 | Node.js | **Python**（Skill/工具更好写） |
| AgentTeams 支持 | 支持 | **支持（推荐运行时）** |
| 冗余浪费 | 有（个人助手功能） | 少 |

---

## 四、结论与路线建议

### 结论：需不需要自己重写 Agent？

**不需要从零重写，但应该选 Python 路线（QwenPaw/AgentScope），避开 OpenClaw。**

- OpenClaw **不是烂代码**，是"重而全"，它的 agent loop 设计优秀，但定位不匹配我们的需求，且复杂度偏高、测试偏低。
- **完全重写一个 Agent 成本极高**（要自己处理 LLM 容错、上下文、工具、记忆、Matrix 通信等大量细节），没必要。
- **最优解：基于 AgentScope（Python）写我们自己的 Manager loop**——AgentScope 提供清晰的 Agent 核心 + 状态机 + 工具/记忆/权限模块，我们只需扩展"研发团队调度"逻辑，不继承 OpenClaw 的重。

### 三条路线（按推荐排序）

**方案 B（推荐）：基于 AgentScope 写 Manager loop，用 QwenPaw 运行时接入 AgentTeams**
- 用 AgentScope 的 `Agent` 类 + 显式状态机，写我们自己的 Manager 主循环（醒来→读任务→决策招谁→分派→等结果→验证→沉淀）
- 借助 AgentTeams 的**编排层**（Worker/Team CRD、Matrix 通信、Higress 安全、MinIO 共享状态）
- Python 生态，loop 完全可控，不继承 OpenClaw 重

**方案 A：用 OpenClaw，只做配置层**
- 不写核心代码，用 `soul/agents/HEARTBEAT.md` + skills 定义 Manager 行为
- 最快，但受 OpenClaw 能力边界限制，且继承它的重

**方案 C：完全自写 Agent loop（不依赖 OpenClaw/QwenPaw）**
- 基于 AgentScope 或纯 Python 自写主循环
- 最干净最可控，但工作量大（要处理 LLM 容错/上下文/工具/记忆/MCP 等）

### 建议下一步
基于 **方案 B**，深入 AgentScope 的 agent loop（`Agent.reply` 主循环），设计我们自己的"研发团队调度 Manager loop"，先出设计，再写代码（当前暂不部署，只做源码层实现）。

---

## 五、相关文档索引
- AgentTeams 内部机制（含运行时）：`AGENTTEAMS-INTERNALS.md`
- Agent Identity 清单（6 个 Agent 定义）：`../../agents/AGENT-IDENTITY.md`
- 动态 Agent 团队研究：`../references/theory/DYNAMIC-AGENT-TEAM.md`
- 参考源码：`../references/refs/agent-teams/`（OpenClaw fork / QwenPaw / CoPaw）、`../references/refs/agentscope/`

---

## 附：本次调研的实证来源
- OpenClaw agent runtime 循环（`openclaw-book/chapters/10-agent-runtime.md`）
- OpenClaw 源码解读（12）LLM↔Tool 核心循环 run-loop.ts（CSDN，2026-08）
- OpenClaw 架构深度剖析（博客园，2026-03）
- AgentTeams openclaw-base/Dockerfile（确认 fork 自 higress-group/openclaw）
- AgentScope `_agent.py` / `_utils.py`（源码实证，ReAct 状态机）
- CoPaw/QwenPaw `worker.py`（源码实证）
