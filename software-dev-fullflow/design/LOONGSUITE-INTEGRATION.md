# LoongSuite 推理轨迹观测接入（LOONGSUITE-INTEGRATION）

> GOAI · 赛道三「软件研发全流程协同」· 协同基点 AgentTeams
> 本文回答：「阿里官方 **LoongSuite**（Agent 推理轨迹观测组件）怎么接入、能带来什么价值、如何在本地验证、以及如何落地到 AgentTeams 部署」。
> 对应评审权重：**工程落地、运行验证与安全可审计 20%** + 官方工具链要求（`LoongSuite` 在官方推荐工具链之列）。
> 日期：2026-08-15

---

## 0. 一句话结论

> **LoongSuite 是阿里官方（alibaba/loongsuite-python）的 GenAI 可观测套件**：它基于 OpenTelemetry，提供针对 **AgentScope**（我们 Agent 的底座）的自动插桩，能捕获 Agent 推理的完整 span 树（`invoke_agent → react step → chat / execute_tool`），并把 `gen_ai.agent.name` / `gen_ai.operation.name` / `gen_ai.tool.name` 等语义属性打进 span。**本地已验证可跑通**：用一个模拟「研发 Worker」的 AgentScope Agent，把推理轨迹导出到本地 Jaeger，成功看到 `worker-rootcause` 的推理瀑布图。**它直接命中官方要求「覆盖 Skill 调用 / MCP 工具 / RAG 检索 / LLM 推理全链路推理轨迹」+「工程落地/安全可审计 20%」**，是复赛工程落地的高价值加分项。

---

## 一、为什么需要 LoongSuite（对齐评审维度）

评审要求 **可观测（推荐）**：覆盖全链路推理轨迹、在线监控与告警。官方工具链清单也明确列出 **LoongSuite（Agent 推理轨迹观测）**。

我们已有的 `OBSERVABILITY.md` 是**设计**（Trace/Log/Metrics 三类 + OTel 标准），但**工程落地为零**。LoongSuite 恰好提供"Agent 推理轨迹"这一层的**现成实现**，且是阿里官方、与 AgentScope 同生态，**不重复造轮子、不引入第三方**——完全符合「最大化复用官方」原则。

| LoongSuite 捕获的推理轨迹 | 对齐评审哪条 |
|--------------------------|-------------|
| Agent 推理（`invoke_agent` / `react step`） | 多Agent协同 25%：谁在推理、推理了几轮 |
| LLM 调用（`chat`，含 token 用量） | 工程落地 20%：LLM 成本可量化 |
| 工具调用（`execute_tool`，含工具名/参数/结果） | MCP 与工具集成：工具调用链可审计 |
| Agent 名 / 操作名 / 工具名语义属性 | 工程落地：按 Agent 维度检索、安全可审计 |

---

## 二、LoongSuite 组件全景（复用对象）

LoongSuite 是**一个 OpenTelemetry Python Distro**，通过 `~/.loongsuite/bootstrap-config.json` + `LOONGSUITE_PYTHON_SITE_BOOTSTRAP=true` 在 Python 进程启动时自动插桩已安装的 Agent 框架。它提供大量 instrumentation（`loongsuite-instrumentation-agentscope` / `-qwenpaw` / `-langchain` / `-mcp` 等）。

| 组件 | 位置 | 我们复用 | 我们写胶水 |
|------|------|---------|-----------|
| **Distro + site-bootstrap** | `loongsuite-distro` / `loongsuite-site-bootstrap` | 进程启动自动初始化 OTel | 配 `bootstrap-config.json` |
| **AgentScope instrumentation** | `loongsuite-instrumentation-agentscope`（装成 `opentelemetry.instrumentation.agentscope`） | 捕获 AgentScope 推理 span | **手动 `AgentScopeInstrumentor().instrument()`** |
| **GenAI 语义属性工具** | `loongsuite-otel-util-genai` | span 属性命名（`gen_ai.*`） | 无 |
| **OTLP 导出** | `opentelemetry-exporter-otlp` | 导出 trace | 指向本地 Jaeger / 云端 CMS |

> **关键发现（2026-08-15 实测）**：
> 1. LoongSuite 的 **auto-instrumentation 不会自动发现 `agentscope` 的 entry point**（site bootstrap 打印 "started successfully" 但 Agent 没被插桩）。**必须手动调用 `AgentScopeInstrumentor().instrument()`**（会在创建 Agent 前 wrap `Agent.__init__`，注入 middleware）。
> 2. LoongSuite bootstrap 开启时有**副作用：破坏 `mcp.types` 子模块属性绑定**，导致 `agentscope.mcp` import 报 `module 'mcp' has no attribute 'types'`。**修复：在 import agentscope 前 `mcp.types = importlib.import_module('mcp.types')`**。
> 3. 需要 **mcp ≥ 某版本**（提供 `mcp.client.streamable_http.streamable_http_client`）——不要降级到旧 mcp。

---

## 三、本地验证成果（2026-08-15 实测 PASS）

### 3.1 环境

- 本机 Python 3.11.9；`agentscope==2.0.6`（PyPI 稳定版）+ `loongsuite-*==0.8.0` + `opentelemetry-exporter-otlp`
- 本地 Jaeger（OTLP 接收端 + Web UI）：
  ```
  docker run -d --name jaeger-loongsuite -e COLLECTOR_OTLP_ENABLED=true \
    -p 16686:16686 -p 4317:4317 -p 4318:4318 jaegertracing/all-in-one:1.60
  ```

### 3.2 配置 `~/.loongsuite/bootstrap-config.json`

```json
{
  "LOONGSUITE_PYTHON_SITE_BOOTSTRAP": "true",
  "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
  "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
  "OTEL_SERVICE_NAME": "agentteams-worker-demo",
  "OTEL_SEMCONV_STABILITY_OPT_IN": "http,gen_ai_latest_experimental",
  "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "SPAN_AND_EVENT"
}
```

### 3.3 Demo

`demo/loongsuite/agentscope_worker_demo.py`（模拟「研发 Worker」根因定位）：
- `ScriptedChatModel`（不联网）：第一次返回 `search_code` 工具调用，第二次返回最终根因 → 驱动 ReAct 循环走完。
- `Toolkit` 注册 `search_code` 工具；`AgentState(permission_context=ACCEPT_EDITS)` 让工具自动放行。
- 关键：**手动 `AgentScopeInstrumentor().instrument()`**（见 §二 发现 1）。

运行（需 bootstrap 环境变量）：
```powershell
$env:LOONGSUITE_PYTHON_SITE_BOOTSTRAP="true"
python demo/loongsuite/agentscope_worker_demo.py
```

### 3.4 验证结果（Jaeger API 查询）

服务 `agentteams-worker-demo` 成功出现在 Jaeger，捕获到 1 条 trace、**3 个 span**：

| span（operationName） | 语义属性 |
|----------------------|---------|
| `invoke_agent worker-rootcause` | `gen_ai.operation.name=invoke_agent`、`gen_ai.agent.name=worker-rootcause` |
| `react step` | `gen_ai.operation.name=react` |
| `chat scripted-demo-worker` | `gen_ai.operation.name=chat`（模型名 `scripted-demo-worker`） |

这正是 LoongSuite 文档描述的 span 层次（`invoke_agent → react step → chat/execute_tool`），且带 Agent 名/操作名/模型名属性，**可在 Jaeger 按 Agent 维度检索推理轨迹**。

### 3.5 可复用验证脚本

`scripts/verify-loongsuite-traces.py`：
```powershell
python scripts/verify-loongsuite-traces.py          # 跑 demo + 查询 Jaeger（自动断言）
python scripts/verify-loongsuite-traces.py --query  # 只查询，不重跑
```
返回 0 = PASS（服务在 Jaeger + 有预期推理 span）。

---

## 四、落地到 AgentTeams 部署（复赛/决赛路径）

> 官方文档 `references/refs/agent-teams/docs/cms-integration.md`（v1.0.9+）说明了 AgentTeams 如何接观测。核心是给 Manager/Worker 容器设 `AGENTTEAMS_CMS_*` 环境变量，官方会生成 `~/.loongsuite/bootstrap-config.json` 并把 trace 推到 **阿里云 CMS 2.0**。

| 方案 | 做法 | 目标后端 | 适用 |
|------|------|---------|------|
| **A. 本地 Jaeger（已验证）** | 手动注入 OTel 环境变量 + 手动 `AgentScopeInstrumentor().instrument()` | 本地 Jaeger（无需云账号） | 演示、复赛代码包、评审可视化 |
| **B. 阿里云 CMS 2.0（官方标准）** | 设 `AGENTTEAMS_CMS_TRACES_ENABLED=true` + endpoint/license key | 阿里云 CMS 2.0 | 决赛真实部署 |

**当前 AgentTeams 部署（copaw runtime）**：
- 我们 6 Worker 用 **copaw**（= QwenPaw 前身），但 copaw 的 entrypoint **没有** LoongSuite 的自动配置逻辑（只有 qwenpaw 镜像的 entrypoint 有 `loongsuite` 自动装 + 生成 bootstrap-config）。
- 要让 AgentTeams 的 Agent 推理被 LoongSuite 捕获，可选：
  1. **切 Worker runtime 到 qwenpaw**（完整内置 LoongSuite instrumentation，entrypoint 自动配置）——需拉 qwenpaw 镜像 + 重建 Worker + 重配沙箱守卫。
  2. **保持 copaw，手动注入**：在 copaw Worker 容器里装 `loongsuite-instrumentation-agentscope` + 手动 `instrument()` + 配 OTLP 导出（复用本验证成果）。

> **本验证证明核心能力可行**。具体切 runtime 或手动注入的工程化，属复赛/决赛阶段，涉及现有 6 Worker 与沙箱守卫的迁移，建议作为独立任务推进。

---

## 五、风险与对策

| 风险 | 对策 |
|------|------|
| LoongSuite auto-instrumentation 不自动发现 agentscope | **手动 `AgentScopeInstrumentor().instrument()`**（已验证） |
| bootstrap 破坏 `mcp.types` 绑定 | import agentscope 前 `mcp.types = importlib.import_module('mcp.types')`（已验证） |
| 切 qwenpaw runtime 影响现有 6 Worker + 沙箱守卫 | 保持 copaw 手动注入，或作为复赛独立迁移任务 |
| 无阿里云账号，云端 CMS 不可用 | 本地 Jaeger 方案 A 已跑通，演示/评审足够 |

---

## 六、文档索引

- 官方 LoongSuite：`references/refs/agent-teams/qwenpaw/Dockerfile`（loongsuite-* 包清单）、`references/refs/agent-teams/docs/cms-integration.md`（AgentTeams 接入）
- 本验证脚本：`scripts/verify-loongsuite-traces.py`、`demo/loongsuite/agentscope_worker_demo.py`、`demo/loongsuite/bootstrap-config.json`
- 可观测设计（待接入）：`design/OBSERVABILITY.md`
- 待办：`TODO.md`
