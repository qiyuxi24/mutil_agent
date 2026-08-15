# AgentTeams MCP 工具链接入指南（胶水层）

> 本目录是团队接入外部工具链的**胶水层**：复用阿里官方 AgentTeams 的 MCP 机制（Higress 网关 + mcporter + Consumer 授权），我们只提供 YAML 模板 + 封装脚本 + Worker 声明，不重造轮子。
> 官方机制详见 `design/MCP-INTEGRATION.md`。

---

## 目录结构

```
src/agentteams/mcp/
  README.md              本指南
  mcp-code-scan.yaml     示例模板：自建代码扫描 REST API → MCP 工具
  mcp-test-platform.yaml (可按需创建) 测试平台 REST API → MCP 工具
scripts/
  add-toolchains.ps1     预置常用工具链（GitHub + 网页搜索）
  register-mcp.ps1       一键注册自定义 MCP Server + 授权/通知 Worker
src/agentteams/workers.yaml  Worker 声明式 mcpServers 挂载
```

---

## 已预置工具链（`add-toolchains.ps1`）

| Server | 类型 | 接入方式 | 挂到哪些 Worker |
|--------|------|----------|-----------------|
| `github` | GitHub 官方 MCP | `setup-mcp-server.sh`（官方内置模板 + PAT） | aggregator / rootcause / fixer |
| `websearch` | 网页搜索 MCP | `setup-mcp-proxy.sh`（代理公开搜索服务） | aggregator / rootcause |

**注册命令**：

```powershell
# 接 GitHub（需 PAT，填入你的 token）
.\scripts\add-toolchains.ps1 -GithubToken "ghp_xxx"

# 接 GitHub + 网页搜索
.\scripts\add-toolchains.ps1 -GithubToken "ghp_xxx" -EnableSearch
```

> 注意：`websearch` 默认代理 `https://mcp.tavily.com/mcp`（StreamableHTTP）。若要免 key 的公共端点或换搜索服务，改 `add-toolchains.ps1` 里的 `$searchUrl`/`$searchHeader` 即可。
> GitHub 的 PAT 由官方脚本注入网关（`AGENTTEAMS_GITHUB_TOKEN` 环境变量方式），Worker 看不到真实 token。

---

## 快速开始（三步接入一个新工具链）

### 1. 准备工具链

- **已有 MCP 服务**（GitHub/Jira/SonarQube 官方 MCP）→ 走 `proxy` 模式，无需 YAML。
- **自建 REST API**（团队 CI/扫描/评审平台）→ 走 `yaml` 模式，复制 `mcp-code-scan.yaml` 改成你的 API。

### 2. 注册到 Higress（封装脚本）

```powershell
# 代理现有 MCP Server（如 GitHub）
.\scripts\register-mcp.ps1 -Name github -Mode proxy `
    -Url https://mcp.example.com/mcp -Transport http `
    -Header "Authorization: Bearer ghp_xxx"

# 自建 REST API → MCP 工具（用 YAML 模板）
.\scripts\register-mcp.ps1 -Name code-scan -Mode yaml `
    -Credential "sk-xxx" `
    -YamlFile src\agentteams\mcp\mcp-code-scan.yaml `
    -ApiDomain api.scan.example.com
```

脚本会：调官方 `setup-mcp-proxy.sh` / `setup-mcp-server.sh` → 建 Higress MCP Server → 授权 Manager + 所有 Worker → 更新各 `mcporter.json` → 等 ~10s → 触发 Worker 同步。

### 3. 声明给 Worker 用

在 `src/agentteams/workers.yaml` 对应 Worker 的 `spec.mcpServers` 加上 server 名，然后 apply：

```powershell
docker cp src/agentteams/workers.yaml agentteams-controller:/tmp/workers.yaml
docker exec agentteams-controller agt apply -f /tmp/workers.yaml
```

---

## YAML 模板语法（对齐官方 mcp-github.yaml）

| 元素 | 说明 |
|------|------|
| `server.name` | MCP Server 名（脚本会自动加 `mcp-` 前缀） |
| `server.config.accessToken` | **统一凭据 key**，脚本替换为真实值 |
| `tools[].name` | 工具名（给 Agent 看，尽量语义化） |
| `tools[].args` | 参数定义（name/type/required/description） |
| `tools[].requestTemplate` | 实际 REST 调用：`url`/`method`/`body`/`headers` |
| `{{.args.xxx}}` | 引用工具参数 |
| `{{.config.accessToken}}` | 引用网关凭据（Worker 看不到真实 key） |
| `{{.args.x | b64enc}}` | base64 编码（上传文件类） |
| `{{.args.x | default "val"}}` | 缺省值 |

---

## 注意事项

- **必须在 controller 容器内执行**：Higress 控制台 8001 映射在 `agentteams-controller` 容器内（非 manager）。脚本已自动在 controller 容器内先登录再跑官方脚本。
- **先登录 Higress**：脚本会自动调 `gateway_ensure_session()` 用 admin 凭据登录拿 cookie，无需手动。
- **凭据只存网关**：YAML 里 `accessToken: ""`，真实 key 由脚本注入，**别写进 YAML 提交**。
- **授权是 REPLACE**：官方脚本会带全 manager + 所有 worker，安全。
- **先验证再通知**：脚本已内置等待 10s + mcporter list；若工具没出现，手动 `docker exec <worker> mcporter list <server> --schema` 排查。
- **只通知相关 Worker**：默认全部分发；如只要部分，用 `-Workers fixer,tester`。
- **stdio 不支持**：现有 MCP 只能用 `http`/`sse` 代理。
- **云模式（SAE）**：`register-mcp.ps1` / `add-toolchains.ps1` 不可用，改走阿里云 AI 网关控制台。
- **环境为 k8s 模式**：`AGENTTEAMS_RUNTIME=k8s`，与 docker 模式的控制台地址不同（已按 controller 内 8001 处理）。
