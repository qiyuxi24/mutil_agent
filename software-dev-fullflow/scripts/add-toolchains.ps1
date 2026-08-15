# ============================================================
# add-toolchains.ps1
# 预置团队常用 MCP 工具链（GitHub + 网页搜索），一键注册到 Higress
# 并授权给相关 Worker。完全复用官方 setup-mcp-server.sh / setup-mcp-proxy.sh。
#
# 关键：必须在 agentteams-controller 容器内执行（Higress 控制台 8001 映射在
# controller 容器内），且先 source gateway-api.sh 的 gateway_ensure_session()
# 登录拿 cookie（HIGRESS_COOKIE_FILE）再跑官方脚本。
#
# 用法（在 software-dev-fullflow 目录执行）：
#   # 只接 GitHub（需 PAT）
#   .\scripts\add-toolchains.ps1 -GithubToken "ghp_xxx"
#
#   # 接 GitHub + 网页搜索
#   .\scripts\add-toolchains.ps1 -GithubToken "ghp_xxx" -EnableSearch
#
#   # 只接网页搜索
#   .\scripts\add-toolchains.ps1 -EnableSearch
#
# 依赖：docker 已运行，AgentTeams 已部署（agentteams-controller 容器在跑）
# ============================================================

param(
    [string]$GithubToken = "",   # GitHub PAT，空则跳过 GitHub
    [switch]$EnableSearch,       # 是否接网页搜索 MCP（代理公开搜索服务）
    [string]$ControllerContainer = "agentteams-controller"
)

$ErrorActionPreference = "Stop"

if (-not (docker ps --format "{{.Names}}" | Where-Object { $_ -eq $ControllerContainer })) {
    Write-Error "未发现 $ControllerContainer 容器。AgentTeams 未运行？"
    exit 1
}

# 容器内引导：登录 Higress 拿 cookie
$bootstrap = "source /opt/agentteams/scripts/lib/agentteams-env.sh; source /opt/agentteams/scripts/lib/gateway-api.sh; gateway_ensure_session && echo SESSION_OK"

Write-Host "==> 登录 Higress 控制台拿 cookie ..." -ForegroundColor Cyan
$sess = docker exec $ControllerContainer bash -c $bootstrap 2>&1
if ($sess -notmatch "SESSION_OK") {
    Write-Error "Higress 登录失败：$sess"
    exit 1
}
Write-Host "    Higress 会话就绪。" -ForegroundColor Green

# 容器内跑官方脚本的公共函数（先 source 环境 + gateway-api，保证 cookie 已 export）
$env_init = "source /opt/agentteams/scripts/lib/agentteams-env.sh; source /opt/agentteams/scripts/lib/gateway-api.sh; gateway_ensure_session"

# ---- GitHub：官方内置模板，走 setup-mcp-server.sh ----
if ($GithubToken) {
    Write-Host "`n=== 注册 GitHub MCP（官方内置模板 mcp-github.yaml）===" -ForegroundColor Cyan
    $gh = docker exec $ControllerContainer bash -c "$env_init; setup-mcp-server.sh github '$GithubToken'" 2>&1
    Write-Host $gh
    Write-Host "  GitHub MCP 注册完成。等待授权插件激活..." -ForegroundColor Green
    Start-Sleep -Seconds 10
}

# ---- 网页搜索：代理公开搜索 MCP ----
if ($EnableSearch) {
    Write-Host "`n=== 注册网页搜索 MCP（代理模式）===" -ForegroundColor Cyan
    $searchUrl = "https://mcp.tavily.com/mcp"
    $searchTransport = "http"
    $searchHeader = ""
    if ($env:TAVILY_API_KEY) {
        $searchHeader = "--header `"Authorization: Bearer $env:TAVILY_API_KEY`""
    }
    $ws = docker exec $ControllerContainer bash -c "$env_init; setup-mcp-proxy.sh websearch '$searchUrl' $searchTransport $searchHeader" 2>&1
    Write-Host $ws
    Write-Host "  网页搜索 MCP 注册完成。等待授权插件激活..." -ForegroundColor Green
    Start-Sleep -Seconds 10
}

# ---- 触发相关 Worker 拉取配置 + 验证 ----
$targets = @("aggregator","rootcause","fixer")
Write-Host "`n=== 触发相关 Worker 拉取 mcporter 配置 ===" -ForegroundColor Cyan
foreach ($wname in $targets) {
    $c = "agentteams-worker-$wname"
    if (docker ps --format "{{.Names}}" | Where-Object { $_ -eq $c }) {
        Write-Host "==> $c 同步 + 列工具" -ForegroundColor Cyan
        docker exec $c agentteams-sync 2>$null
        docker exec $c mcporter list 2>$null | Select-Object -First 8
    } else {
        Write-Host "  $c 未运行（可稍后 apply workers.yaml 创建）。" -ForegroundColor Yellow
    }
}

Write-Host "`n完成。接下来确认 src\agentteams\workers.yaml 的 mcpServers 已挂 github/websearch，并 agt apply。" -ForegroundColor Green
