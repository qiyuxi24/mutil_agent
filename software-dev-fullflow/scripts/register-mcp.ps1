# ============================================================
# register-mcp.ps1
# 一键把工具链注册到 Higress AI 网关并授权 Worker（复用官方脚本的胶水封装）。
#
# 三种模式：
#   proxy  代理现有 MCP Server（GitHub/Jira/SonarQube 官方 MCP）→ 官方 setup-mcp-proxy.sh
#   yaml   把自建 REST API 包装成 MCP 工具（用 mcp-<name>.yaml 模板）→ 官方 setup-mcp-server.sh
#   auth   仅重新授权/通知已有 MCP 的 Worker（不重建 server）
#
# 用法（在 software-dev-fullflow 目录执行）：
#   .\scripts\register-mcp.ps1 -Name code-scan -Mode yaml -Credential "sk-xxx" -YamlFile src\agentteams\mcp\mcp-code-scan.yaml -ApiDomain api.scan.example.com
#   .\scripts\register-mcp.ps1 -Name github -Mode proxy -Url https://mcp.example.com/mcp -Transport http -Header "Authorization: Bearer ghp_xxx"
#   .\scripts\register-mcp.ps1 -Name github -Mode auth
#
# 依赖：docker 已运行，AgentTeams 已部署，官方脚本在 manager 容器内可用
# ============================================================

param(
    [Parameter(Mandatory)][string]$Name,        # server 名（不带 mcp- 前缀）
    [ValidateSet("proxy","yaml","auth")][string]$Mode = "yaml",
    [string]$Credential = "",                   # yaml 模式的凭据值（accessToken）
    [string]$YamlFile = "",                     # yaml 模式的模板路径
    [string]$ApiDomain = "",                    # yaml 模式显式 API 域名
    [string]$Url = "",                          # proxy 模式的 MCP server URL
    [ValidateSet("http","sse")][string]$Transport = "http",
    [string]$Header = "",                       # proxy 模式的后端认证头，如 "Authorization: Bearer x"
    [string]$Workers = "",                      # 逗号分隔要通知的 worker；空 = 自动发现全部
    [string]$ControllerContainer = "agentteams-controller"
)

$ErrorActionPreference = "Stop"

# ---- 校验容器存在 ----
if (-not (docker ps --format "{{.Names}}" | Where-Object { $_ -eq $ControllerContainer })) {
    Write-Error "未发现 $ControllerContainer 容器。AgentTeams 未运行？"
    exit 1
}

function Invoke-OfficialScript {
    param([string]$ScriptName, [string]$ArgsLine)
    # 官方脚本在 manager 容器内 /opt/agentteams/...，这里经 controller 转发；若无则直接提示
    $probe = "sh -c 'command -v $ScriptName || ls /opt/agentteams/agent/skills/mcp-server-management/scripts/$ScriptName 2>/dev/null'"
    $found = docker exec $ControllerContainer sh -c $probe 2>$null
    if (-not $found) {
        Write-Error "官方脚本 $ScriptName 在 $ControllerContainer 内不可用。请确认 AgentTeams 镜像完整。"
        exit 1
    }
    Write-Host "==> 调官方脚本 $ScriptName $ArgsLine" -ForegroundColor Cyan
    docker exec -i $ControllerContainer bash -c "$ScriptName $ArgsLine"
}

# ---- 模式分发 ----
switch ($Mode) {
    "proxy" {
        if (-not $Url) { Write-Error "proxy 模式需 -Url"; exit 1 }
        $h = ""
        if ($Header) { $h = "--header `"$Header`"" }
        Invoke-OfficialScript "setup-mcp-proxy.sh" "$Name $Url $Transport $h"
    }
    "yaml" {
        if (-not $Credential) { Write-Error "yaml 模式需 -Credential"; exit 1 }
        if (-not $YamlFile)   { Write-Error "yaml 模式需 -YamlFile"; exit 1 }
        if (-not (Test-Path $YamlFile)) { Write-Error "找不到 $YamlFile"; exit 1 }
        $tmp = "/tmp/mcp-$Name.yaml"
        docker cp $YamlFile "${ControllerContainer}:${tmp}" | Out-Null
        $domain = ""
        if ($ApiDomain) { $domain = "--api-domain $ApiDomain" }
        Invoke-OfficialScript "setup-mcp-server.sh" "$Name $Credential --yaml-file $tmp $domain"
    }
    "auth" {
        # 仅通知 worker 拉取配置（重新授权已在官方脚本内做，这里主要触发同步）
        Write-Host "==> auth 模式：触发 Worker 拉取 mcporter 配置" -ForegroundColor Cyan
    }
}

# ---- 等待授权插件激活 ----
Write-Host "==> 等待授权插件激活（~10s）..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# ---- 通知相关 Worker 拉取配置 ----
$containers = @(docker ps --format "{{.Names}}" | Where-Object { $_ -match '^agentteams-worker-' })
if ($Workers) {
    $names = @($Workers -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $containers = @($containers | Where-Object { $n = $_ -replace '^agentteams-worker-', ''; $names -contains $n })
}
if ($containers.Count -eq 0) {
    Write-Host "无 Worker 容器可通知。MCP server 已注册，可后续在 workers.yaml 声明 mcpServers。" -ForegroundColor Yellow
} else {
    foreach ($c in $containers) {
        Write-Host "==> 触发 $c 拉取配置 (agentteams-sync) + 验证 mcporter" -ForegroundColor Cyan
        docker exec $c agentteams-sync 2>$null
        docker exec $c mcporter list 2>$null | Select-Object -First 5
    }
}

Write-Host "`n完成。验证：docker exec <worker容器> mcporter list <server> --schema" -ForegroundColor Green
Write-Host "建议把该工具写进对应 Worker 的 skills（参考 mcp-server-management / mcporter 官方 skill）。" -ForegroundColor Green
