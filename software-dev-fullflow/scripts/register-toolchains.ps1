# ============================================================
# register-toolchains.ps1
# 一键把「团队自建工具链」注册到 Higress AI 网关并授权全部 Worker。
#
# 两个工具链后端均为阿里 AgentScope 实现，已跑在宿主机：
#   code-scan        src/agentteams/toolchains/code_scan_service.py    宿主机 :9100
#   test-platform    src/agentteams/toolchains/test_platform_service.py 宿主机 :9200
#
# 复用官方 setup-mcp-server.sh（在 controller 容器内）完成：
#   1. DNS service source 注册（host.docker.internal:9100/9200）
#   2. MCP Server 创建（YAML 模板替换凭据）
#   3. Manager + 全部 Worker 的 consumer 授权 + mcporter.json 更新 + 推 MinIO
#
# 前置条件：
#   - docker 已运行，AgentTeams 已部署（agentteams-controller 在跑）
#   - 两个工具链服务已启动（scripts/start-toolchains.ps1）
#
# 用法（在 software-dev-fullflow 目录执行）：
#   .\scripts\register-toolchains.ps1                # 注册 code-scan + test-platform
#   .\scripts\register-toolchains.ps1 -Only scan     # 只注册 code-scan
#   .\scripts\register-toolchains.ps1 -Only test     # 只注册 test-platform
# ============================================================

param(
    [ValidateSet("all","scan","test")][string]$Only = "all",
    [string]$Credential = "toolchain-demo-key",   # 网关凭据（演示用固定值；Worker 看不到真实 key）
    [string]$ControllerContainer = "agentteams-controller",
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $ProjectRoot) { $ProjectRoot = Split-Path $PSScriptRoot -Parent }

if (-not (docker ps --format "{{.Names}}" | Where-Object { $_ -eq $ControllerContainer })) {
    Write-Error "未发现 $ControllerContainer 容器。AgentTeams 未运行？"
    exit 1
}

# ---- 登录 Higress 拿 cookie ----
$env_init = "source /opt/agentteams/scripts/lib/agentteams-env.sh; source /opt/agentteams/scripts/lib/gateway-api.sh; gateway_ensure_session"
Write-Host "==> 登录 Higress 控制台拿 cookie ..." -ForegroundColor Cyan
$bootstrap = "$env_init && echo SESSION_OK"
$sess = docker exec $ControllerContainer bash -c $bootstrap 2>&1
if ($sess -notmatch "SESSION_OK") {
    Write-Error "Higress 登录失败：$sess"
    exit 1
}
Write-Host "    Higress 会话就绪。" -ForegroundColor Green

# ---- 注册 code-scan ----
if ($Only -in @("all","scan")) {
    $yaml = "$ProjectRoot\src\agentteams\mcp\mcp-code-scan.yaml"
    if (-not (Test-Path $yaml)) { Write-Error "找不到 $yaml"; exit 1 }
    $tmp = "/tmp/mcp-code-scan.yaml"
    docker cp $yaml "${ControllerContainer}:${tmp}" | Out-Null
    Write-Host "`n=== 注册 code-scan MCP（AgentScope 工具链，:9100）===" -ForegroundColor Cyan
    docker exec $ControllerContainer bash -c "$env_init; bash /opt/agentteams/agent/skills/mcp-server-management/scripts/setup-mcp-server.sh code-scan '$Credential' --yaml-file $tmp --api-domain host.docker.internal:9100" 2>&1
    Write-Host "  code-scan 注册完成。" -ForegroundColor Green
}

# ---- 注册 test-platform ----
if ($Only -in @("all","test")) {
    $yaml = "$ProjectRoot\src\agentteams\mcp\mcp-test-platform.yaml"
    if (-not (Test-Path $yaml)) { Write-Error "找不到 $yaml"; exit 1 }
    $tmp = "/tmp/mcp-test-platform.yaml"
    docker cp $yaml "${ControllerContainer}:${tmp}" | Out-Null
    Write-Host "`n=== 注册 test-platform MCP（AgentScope 工具链，:9200）===" -ForegroundColor Cyan
    docker exec $ControllerContainer bash -c "$env_init; bash /opt/agentteams/agent/skills/mcp-server-management/scripts/setup-mcp-server.sh test-platform '$Credential' --yaml-file $tmp --api-domain host.docker.internal:9200" 2>&1
    Write-Host "  test-platform 注册完成。" -ForegroundColor Green
}

# ---- 等待授权插件激活 + 触发相关 Worker 拉取 ----
Write-Host "`n==> 等待授权插件激活（~10s）..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

$targets = @("fixer","tester")   # fixer→code-scan，tester→test-platform
Write-Host "=== 触发相关 Worker 拉取 mcporter 配置 ===" -ForegroundColor Cyan
foreach ($wname in $targets) {
    $c = "agentteams-worker-$wname"
    if (docker ps --format "{{.Names}}" | Where-Object { $_ -eq $c }) {
        Write-Host "==> $c 同步 + 列工具" -ForegroundColor Cyan
        docker exec $c agentteams-sync 2>$null
        if ($wname -eq "fixer") {
            docker exec $c mcporter list code-scan 2>&1 | Select-Object -First 10
        } else {
            docker exec $c mcporter list test-platform 2>&1 | Select-Object -First 10
        }
    } else {
        Write-Host "  $c 未运行（可稍后 apply workers.yaml 创建）。" -ForegroundColor Yellow
    }
}

Write-Host "`n完成。验证：docker exec agentteams-worker-fixer mcporter list code-scan --schema" -ForegroundColor Green
Write-Host "        docker exec agentteams-worker-tester mcporter list test-platform --schema" -ForegroundColor Green
