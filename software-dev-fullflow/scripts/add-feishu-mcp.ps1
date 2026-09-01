# ============================================================
# add-feishu-mcp.ps1
# 把「飞书（Lark）官方 MCP」接入团队，一键完成：
#   1) 宿主机后台拉起 lark-mcp（SSE 模式，官方 @larksuiteoapi/lark-mcp）
#   2) 探活 /sse 端点
#   3) 复用 register-mcp.ps1（proxy 模式）注册 feishu 到 Higress 网关
#   4) 触发相关 Worker 拉取 mcporter 配置 + 验证工具列表
#
# 前置：
#   - 已创建飞书「企业自建应用」并拿到 App ID / App Secret（见 design/LARK-MCP-INTEGRATION.md）
#   - 本机 Node >= 20（npx 可用；lark-mcp 要求 >=20）
#   - AgentTeams 已部署（agentteams-controller 容器在跑）
#   - 脚本需在 software-dev-fullflow 目录执行
#
# 用法：
#   .\scripts\add-feishu-mcp.ps1 -AppId "cli_xxx" -AppSecret "yyy"
#   .\scripts\add-feishu-mcp.ps1 -AppId "cli_xxx" -AppSecret "yyy" -Preset preset.im.default -Workers "leader,aggregator,rootcause"
#
# 说明：
#   - 默认 preset.light（精简工具集，省 token）；需要消息/文档/表格/任务/日历换对应 preset
#   - 注册成功后把 feishu 挂到 workers.yaml 再 agt apply（脚本末尾会提示）
#   - lark-mcp 服务保持后台运行；PID 写 data/feishu-mcp.pid，日志写 logs/feishu-mcp.log
#   - 停止服务：Stop-Process -Id (Get-Content data/feishu-mcp.pid)
# ============================================================

param(
    [Parameter(Mandatory)][string]$AppId,       # 飞书应用 App ID（cli_ 开头）
    [Parameter(Mandatory)][string]$AppSecret,   # 飞书应用 App Secret
    [ValidateSet("preset.light","preset.default","preset.im.default","preset.base.default","preset.base.batch","preset.doc.default","preset.task.default","preset.calendar.default")]
    [string]$Preset = "preset.light",           # 预设工具集（省 token 用 light）
    [int]$Port = 8300,                          # lark-mcp SSE 监听端口
    [string]$Workers = "leader,aggregator,rootcause",  # 要通知的 Worker（逗号分隔）
    [string]$ControllerContainer = "agentteams-controller"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # software-dev-fullflow
$pidFile = Join-Path $root "data\feishu-mcp.pid"
$logFile = Join-Path $root "logs\feishu-mcp.log"

# ---- 0. 前置校验 ----
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 node。请先安装 Node.js >= 20。"
    exit 1
}
$nodeVer = [int]((node -v) -replace 'v', '' -split '\.')[0]
if ($nodeVer -lt 20) {
    Write-Error "Node 版本过低（v$nodeVer，需 >=20）。请升级。"
    exit 1
}
if (-not (docker ps --format "{{.Names}}" | Where-Object { $_ -eq $ControllerContainer })) {
    Write-Error "未发现 $ControllerContainer 容器。AgentTeams 未运行？"
    exit 1
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $pidFile) | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logFile) | Out-Null

# ---- 1. 后台启动 lark-mcp（SSE 模式，监听 0.0.0.0 供容器访问）----
Write-Host "`n=== [1/4] 启动 lark-mcp SSE 服务（端口 $Port，preset=$Preset）===" -ForegroundColor Cyan

# 已运行则复用
if (Test-Path $pidFile) {
    $oldPid = Get-Content $pidFile
    $alive = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    if ($alive) {
        Write-Host "    检测到 lark-mcp 已在运行（PID $oldPid），跳过启动。" -ForegroundColor Yellow
        $procId = $oldPid
    }
}
if (-not $procId) {
    # npx 拉包 + 起服务。首次运行会联网下载 @larksuiteoapi/lark-mcp。
    $args = @("--yes", "@larksuiteoapi/lark-mcp", "mcp",
        "-a", $AppId, "-s", $AppSecret,
        "-m", "sse", "--host", "0.0.0.0", "-p", "$Port",
        "-t", $Preset, "-l", "zh")
    Write-Host "    命令: npx @larksuiteoapi/lark-mcp mcp -a <AppId> -s <secret> -m sse --host 0.0.0.0 -p $Port -t $Preset"
    $p = Start-Process -FilePath "npx.cmd" -ArgumentList $args `
        -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err" -PassThru
    $procId = $p.Id
    Set-Content -Path $pidFile -Value $procId
    Write-Host "    lark-mcp 已后台启动（PID $procId），日志: logs/feishu-mcp.log"
}

# ---- 2. 探活 /sse 端点（首次 npx 下载可能较慢，最多等 60s）----
Write-Host "`n=== [2/4] 探活 SSE 端点 http://127.0.0.1:$Port/sse ===" -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    $listening = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($listening) { $ok = $true; break }
    if (-not (Get-Process -Id $procId -ErrorAction SilentlyContinue)) {
        Write-Error "lark-mcp 进程已退出。查看日志: $logFile / $logFile.err"
        exit 1
    }
    Start-Sleep -Seconds 2
}
if (-not $ok) {
    Write-Error "60s 内未监听到端口 $Port。查看日志: $logFile / $logFile.err（首次 npx 下载可能更久，可手动重跑）"
    exit 1
}
Write-Host "    SSE 端口已监听。端点: http://host.docker.internal:$Port/sse" -ForegroundColor Green

# ---- 3. 注册 Higress（复用 register-mcp.ps1 proxy 模式）----
Write-Host "`n=== [3/4] 注册 feishu 到 Higress 网关 ===" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "register-mcp.ps1") `
    -Name "feishu" -Mode "proxy" `
    -Url "http://host.docker.internal:$Port/sse" -Transport "sse" `
    -Workers $Workers -ControllerContainer $ControllerContainer
if ($LASTEXITCODE -ne 0) { Write-Error "register-mcp.ps1 失败"; exit 1 }

# ---- 4. 收尾提示 ----
Write-Host "`n=== [4/4] 完成 ===" -ForegroundColor Green
Write-Host "  飞书 MCP 已注册到 Higress（server 名: feishu），相关 Worker 已同步。" -ForegroundColor Green
Write-Host ""
Write-Host "下一步（把 feishu 挂给 Worker）:" -ForegroundColor Cyan
Write-Host "  1. 确认 src\agentteams\workers.yaml 中 leader/aggregator/rootcause 已声明 feishu mcpServer"
Write-Host "  2. docker cp src\agentteams\workers.yaml $ControllerContainer`:/tmp/workers.yaml"
Write-Host "  3. docker exec $ControllerContainer agt apply -f /tmp/workers.yaml"
Write-Host ""
Write-Host "验证工具:" -ForegroundColor Cyan
Write-Host "  docker exec agentteams-worker-aggregator mcporter list feishu --schema"
Write-Host ""
Write-Host "管理 lark-mcp 服务:" -ForegroundColor Cyan
Write-Host "  停止: Stop-Process -Id (Get-Content $pidFile)"
Write-Host "  日志: Get-Content $logFile -Tail 50"
