# 团队工具链 MCP 接入方案（MCP-INTEGRATION）

> 目标：**最大化复用阿里官方 AgentTeams 的 MCP 机制**，团队只写**胶水代码**（YAML 模板 + 封装脚本 + 声明式 CR + Worker 侧 skill），不重造轮子。
> 依据：官方 `references/refs/agent-teams/` 的 `manager-guide.md`、`worker-guide.md`、`quickstart.md`、`declarative-resource-management.md`，以及官方 skill `mcp-server-management` / `mcporter`。
> 更新日期：2026-08-14

---

## 0. 一句话结论

> AgentTeams 的 MCP 是「**集中式凭据 + 网关代理 + 声明式授权**」三层模型：工具链（外部 API 或自建 REST API）统一注册到 **Higress AI 网关**，凭据集中存放，Worker 通过 `mcporter` CLI 调用、通过 Consumer 授权做动态权限控制。**我们只需写 YAML 模板 + 封装脚本，把团队工具链"塞进"这套官方机制。**

---

## 1. 官方三层 MCP 机制（复用对象）

| 层 | 官方组件 | 我们复用 | 我们写胶水 |
|----|----------|----------|-----------|
| **工具层** | 外部 API / 自建 REST API / 现有 MCP Server | 现成 API | 自定义 YAML 模板（把 API 描述成 MCP 工具） |
| **网关层** | Higress AI 网关（8080 数据面 / 8001 控制台 / 18001 控制台端口） | 官方 `setup-mcp-server.sh` / `setup-mcp-proxy.sh` | 一键封装脚本（Windows/PowerShell 调官方脚本） |
| **消费层** | Worker 用 `mcporter` 调用，Consumer 授权控制 | 官方 `mcporter` skill | Worker CR 里声明 `mcpServers` + 通知 Worker 拉取 |

### 1.1 官方两种接入脚本（二选一）

| 场景 | 用哪个官方脚本 | 说明 |
|------|---------------|------|
| **代理现有 MCP Server**（GitHub、Sentry、Notion 官方 MCP） | `setup-mcp-proxy.sh <name> <url> <transport> [--header "K: V"]` | 仅支持 `http`(StreamableHTTP) / `sse`，**不支持 stdio** |
| **把自建 REST API 包装成 MCP 工具**（团队自有工具链） | `setup-mcp-server.sh <name> <credential> --yaml-file <自定义.yaml>` | YAML 统一用 `accessToken` 作凭据 key |

### 1.2 关键安全模型（务必遵守）

- **凭据只存网关**：GitHub PAT / API key 集中放 Higress，Worker 永远看不到真实 token（官方设计）。
- **授权是 REPLACE 语义**：手动调用 consumer 授权时**必须带全**（manager + 所有 worker），不能只加新的。
- **建好必须验证再通知**：等 ~10s 授权插件激活，Manager 先 `mcporter list` / `call` 验证连通，**不推坏工具**。
- **只通知相关 Worker**：别广播给所有 Worker，只通知角色/任务需要的。
- **云模式（SAE）**：脚本不可用，改走阿里云 AI 网关控制台。

---

## 2. 团队接入工具链的标准流程（胶水步骤）

```
① 准备工具链（外部 API 或自建 REST API）
② 写 MCP YAML 模板  →  放 src/agentteams/mcp/  (见模板 mcp-<name>.yaml)
③ 跑封装脚本         →  scripts/register-mcp.ps1   (调官方 setup-mcp-server.sh / proxy)
④ 声明 Worker        →  workers.yaml 加 spec.mcpServers
⑤ Worker 拉取配置    →  mcporter list / call 使用新工具
⑥ 权限控制           →  随时撤销/恢复 Consumer 授权 → Worker 403/恢复
```

### 2.1 方案对比：外部 MCP Server vs 自建 REST API

| 团队要接的东西 | 推荐方式 | 胶水产物 |
|---------------|---------|---------|
| GitHub / GitLab / Jira / SonarQube 等**已有 MCP 服务** | `setup-mcp-proxy.sh` | 无 YAML，直接命令行 |
| 团队**自研 REST API**（CI 状态、代码扫描、评审 bot、测试平台） | `setup-mcp-server.sh` + YAML | `mcp-<name>.yaml` 模板 |
| 内部工具只有 **REST，没有 MCP** | 写 YAML 模板把它描述成 MCP 工具 | `mcp-<name>.yaml` |
| 内部工具需要**跑代码/文件操作**（不在沙箱内） | 不接 MCP，用 copaw 内置原生工具 | 复用 SECURITY-POLICY |

> 原则：**工具链能复用官方 MCP 的绝不自己写工具执行器**。只有沙箱内文件/代码操作才走 copaw 原生工具（那些官方已内置，也无需重造）。

---

## 3. 胶水产物清单

| 文件 | 用途 | 状态 |
|------|------|:---:|
| `design/MCP-INTEGRATION.md` | 本方案文档 | ✅ 本文 |
| `src/agentteams/mcp/mcp-code-scan.yaml` | 示例：把自建代码扫描 REST API 包装成 MCP 工具 | ✅ |
| `scripts/register-mcp.ps1` | 一键注册 MCP Server + 授权 Worker（封装官方脚本） | ✅ |
| `src/agentteams/workers.yaml` | 给 fixer/tester 等挂 `mcpServers` | ✅ |
| `src/agentteams/mcp/README.md` | 团队接入指南（怎么加新工具） | ✅ |

---

## 4. 参考资料索引（官方）

| 官方文档 | 位置 |
|----------|------|
| Manager 管理 MCP | `references/refs/agent-teams/docs/zh-cn/manager-guide.md`（§管理 MCP Server） |
| Worker MCP 故障排查 | `references/refs/agent-teams/docs/zh-cn/worker-guide.md`（§无法访问 MCP） |
| GitHub MCP 端到端 | `references/refs/agent-teams/docs/zh-cn/quickstart.md`（第五/七/八/九步） |
| 声明式 mcpServers 字段 | `references/refs/agent-teams/docs/zh-cn/declarative-resource-management.md` |
| 官方 MCP 管理 skill | `references/refs/agent-teams/manager/agent/skills/mcp-server-management/` |
| 官方 mcporter skill | `references/refs/agent-teams/manager/agent/skills/mcporter/` |
| GitHub YAML 模板范例 | `references/refs/agent-teams/manager/agent/skills/mcp-server-management/references/mcp-github.yaml` |

---

## 5. 下一步（待办）

- [ ] 按需为具体工具链（如 CI/CD、代码评审）写对应 `mcp-<name>.yaml`
- [ ] 在真实环境验证 `register-mcp.ps1` 端到端（建 server → 授权 → mcporter 调用）
- [ ] 把验证结果回填本文档「实测」章节
