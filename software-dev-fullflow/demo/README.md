# Demo：Microsoft Agent Framework（MAF）多 Agent 协同跑起来

> ⚠️ **本文档及本目录下的 `maf_*.py` / `OFFICIAL-MAF-GUIDANCE.md` 仅作「选型对比参考」，非参赛实现。**
> 参赛协同基点为阿里官方 **AgentTeams**，本项目实现全部以 AgentTeams 为主（见 `src/loop/agentteams_*.py`）。
> MAF 内容仅用于说明「为何选 AgentTeams 而非 MAF」，不作评审可运行实现的一部分。

本目录演示如何把 MAF 官方案例「改一改」就能用 **DeepSeek**（OpenAI 兼容协议）在本地跑起来，
让你直观看到多 Agent 协同的效果。

## 背景：官方案例为什么不能直接跑

MAF 官方案例 `samples/03-workflows/orchestrations/sequential_agents.py` 用的是 `FoundryChatClient`，
需要 **微软 Foundry/Azure 账号 + `az login`**，国内基本没法直接跑。

我们只改了一处：把 `FoundryChatClient` 换成 `OpenAIChatCompletionClient`（走 OpenAI 兼容的 Chat Completions 协议），
再用 DeepSeek 的 API Key + Base URL 就通了。**MAF 的编排引擎、Agent、共享上下文全部原样保留。**

## 两个脚本

| 文件 | 说明 |
|------|------|
| `maf_sequential_deepseek.py` | 官方 `sequential_agents.py` 的直译版，固定 prompt 跑一遍，适合快速验证 |
| `maf_sequential_interactive.py` | **交互版**，可不断输入主题，实时观察 writer → reviewer 两个 Agent 接力协作 |

## 环境准备（一次性）

```powershell
# 1. 创建虚拟环境并安装 MAF 三个包（core / openai / orchestrations）
cd software-dev-fullflow\demo
python -m venv .venv
.\.venv\Scripts\python -m pip install agent-framework-core agent-framework-openai agent-framework-orchestrations

# 2. 配置 DeepSeek API（.env 已在仓库中，改 key 即可）
#    DEEPSEEK_API_KEY=你的key
#    DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
#    DEEPSEEK_MODEL=deepseek-v4-flash
```

## 运行

```powershell
cd software-dev-fullflow\demo

# 固定跑一遍（快速验证）
.\.venv\Scripts\python.exe maf_sequential_deepseek.py

# 交互模式（推荐，看多 Agent 协同）
.\.venv\Scripts\python.exe maf_sequential_interactive.py
```

交互版会显示 `>` 提示符，你输入任意主题（如「为一款便宜电单车写句广告语」「给冬日的暖咖啡店想句 slogan」），
就能看到：
1. **writer** Agent 先产出营销文案；
2. **reviewer** Agent 再对 writer 的输出做评审；
3. 两个 Agent **共享同一段对话上下文**（这就是 MAF 的 `SequentialBuilder` 顺序编排）。

输入 `q` / `quit` 退出。

## 效果示例（DeepSeek deepseek-v4-flash）

```
> A tagline for a cozy coffee shop in winter.
---- 02 [writer]
Winter's warmest welcome, in every sip.
---- 03 [reviewer]
The tagline is concise and evocative, capturing both the seasonal setting
and the cozy, welcoming atmosphere... Strong and memorable.
```

## 这跟我们的参赛作品有什么关系

- 这套「顺序编排 + 共享上下文 + 多 Agent 接力」正是我们 `PLAN.md` 里 **PDCA 闭环** 的底座
  （缺陷聚合 → 根因定位 → 修复 → 测试 → 发布 → 复盘，就是多个 Agent 接力、共享同一份任务状态）。
- MAF 只是**参考实现**，官方要求以 **AgentTeams** 为协同基点。这里先让你对「多 Agent 协同」有体感，
  后续把同样的编排思路映射到 AgentTeams 的 Worker/Manager 上。

## 官方建议与可复用能力

见 **[OFFICIAL-MAF-GUIDANCE.md](./OFFICIAL-MAF-GUIDANCE.md)** —— 基于 MAF 本地官方源码调研整理：
- 官方把多 Agent 编排分三层（手工链式 / 图式 Workflow / 5 种高级 Builder），**建议优先用高级 Builder**。
- 5 种 Builder（Sequential/Concurrent/Handoff/GroupChat/Magentic）的适用场景 + 与我们研发闭环的映射。
- **MagenticBuilder = 官方版 Manager Loop**，最贴合我们创新点，建议优先研读 `_magentic.py`。
- 可直接复用的官方能力清单（工具审批/回滚、状态共享、可观测、Skills、MCP 等）。

## 常见问题

- **`ModuleNotFoundError`**：确认在 `.venv` 里安装且用 `.venv\Scripts\python.exe` 运行。
- **401 / 认证失败**：检查 `.env` 里 `DEEPSEEK_API_KEY` 是否有效。
- **404 / model not found**：确认 `DEEPSEEK_MODEL` 用官方当前模型名（如 `deepseek-v4-flash`）。
- **联网**：首次运行需能访问 `api.deepseek.com`。
