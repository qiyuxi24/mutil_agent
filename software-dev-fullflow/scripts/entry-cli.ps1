# ============================================================
# 命令行入口 —— AgentTeams 官方 CLI（agt）+ 任务派发
#
# 统一命令行入口，按"官方方式"接入 AgentTeams 平台：
#   - 资源管理（Worker/Team/Manager）直接用官方 `agt` CLI
#   - 任务提交通过 Matrix 给 @manager 发消息（官方派单方式）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File entry-cli.ps1
#   powershell -ExecutionPolicy Bypass -File entry-cli.ps1 "任务描述"
#   powershell -ExecutionPolicy Bypass -File entry-cli.ps1 --submit "任务描述"
# ============================================================

param(
    [Parameter(Position=0)]
    [string]$Action,        # 直接命令: status / workers / teams / submit / apply / help / 或任务描述
    [Parameter(Position=1)]
    [string]$Arg            # 第二个参数（如任务描述）
)

$ErrorActionPreference = "Stop"
$CTRL = "agentteams-controller"
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root "src"
$venv = Join-Path $root "demo\.venv\Scripts\python.exe"
if (-not (Test-Path $venv)) { $venv = "python" }

# 从 controller 容器读 AGENTTEAMS_ADMIN_PASSWORD 作为默认（若未设置）
if (-not $env:AGENTTEAMS_ADMIN_PASSWORD) {
    $pw = docker inspect $CTRL --format '{{range .Config.Env}}{{println .}}{{end}}' 2>$null |
        Where-Object { $_ -match '^AGENTTEAMS_ADMIN_PASSWORD=(.+)$' }
    if ($pw) { $env:AGENTTEAMS_ADMIN_PASSWORD = ($pw -split '=',2)[1] }
}

function agt {
    param([Parameter(ValueFromRemainingArguments)]$args)
    docker exec $CTRL agt @args
}

function Ensure-Platform {
    $up = docker ps --format '{{.Names}}' 2>$null | Select-String -Quiet "^$CTRL$"
    if (-not $up) {
        Write-Host "[ERROR] AgentTeams 平台未运行（缺少 $CTRL 容器）。" -ForegroundColor Red
        Write-Host "        请先启动 Docker Desktop 并部署平台：scripts\reinstall-agentteams.ps1" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "✓ AgentTeams 平台在线" -ForegroundColor Green
}

function Show-Status {
    Write-Host "`n===== 平台状态 =====`n" -ForegroundColor Cyan
    agt status
    Write-Host "`n===== Workers =====`n" -ForegroundColor Cyan
    agt get workers
    Write-Host "`n===== Teams =====`n" -ForegroundColor Cyan
    agt get teams
}

function Submit-Task {
    param([Parameter(Mandatory=$true)][string]$Task)
    Ensure-Platform
    Write-Host "`n→ 提交任务给 Manager...`n" -ForegroundColor Cyan
    & $venv -c "import sys; sys.path.insert(0, r'$src'); from loop.agentteams_client import AgentTeamsClient; c=AgentTeamsClient(mode='docker'); c.matrix_login(); rid=c.ensure_manager_room(); c.send_matrix_message(rid, '【PDCA 闭环任务】'+r'''$Task'''+'\n请按 6 Worker 流水线接力，输出里程碑词'); print('✓ 任务已提交到 Manager 房间:', rid)" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] 任务提交失败（确认平台 + AGENTTEAMS_ADMIN_PASSWORD）" -ForegroundColor Red
    }
}

function Show-Help {
    Write-Host @"

  ┌──────────────────────────────────────────────────────────┐
  │  AgentTeams 命令行入口（官方 agt CLI）                      │
  ├──────────────────────────────────────────────────────────┤
  │  status               查看平台 / Worker / Team 状态        │
  │  workers              查看 7 个 Worker                    │
  │  teams                查看 Team                          │
  │  submit <任务>        提交 PDCA 任务给 Manager            │
  │  apply                应用 workers.yaml（批量管理 Worker） │
  │  <任务描述>           直接提交该任务                       │
  │  help                 显示此帮助                          │
  │  exit / q             退出                               │
  └──────────────────────────────────────────────────────────┘
"@
}

# ---- 有参数：执行一次即退 ----
if ($Action) {
    switch -Regex ($Action.ToLower()) {
        "^(status)$"            { Ensure-Platform; Show-Status; exit 0 }
        "^(workers?)$"          { Ensure-Platform; agt get workers; exit 0 }
        "^(teams?)$"            { Ensure-Platform; agt get teams; exit 0 }
        "^(submit)$"            { if (-not $Arg) { Write-Host "用法: entry-cli.ps1 submit <任务描述>"; exit 1 }; Submit-Task $Arg; exit 0 }
        "^(apply)$"             { Ensure-Platform; docker cp (Join-Path $root "src\agentteams\workers.yaml") "$CTRL`:/tmp/workers.yaml"; agt apply -f /tmp/workers.yaml; exit 0 }
        "^(help|h|-\w+)"        { Show-Help; exit 0 }
        default                 { Submit-Task ($Action + $(if ($Arg) {" $Arg"} else {""})); exit 0 }
    }
}

# ---- 交互模式 ----
Ensure-Platform
Write-Host @"

  AgentTeams 命令行入口 · 输入 help 查看命令
"@ -ForegroundColor Cyan

while ($true) {
    $cmd = Read-Host "`nagt> "
    if (-not $cmd) { continue }
    $parts = $cmd -split ' ', 2
    $a = $parts[0].ToLower()
    $rest = if ($parts.Length -gt 1) { $parts[1] } else { "" }
    switch ($a) {
        { $_ -in @("q","quit","exit") } { Write-Host "再见。"; exit 0 }
        "help" { Show-Help }
        "status" { Show-Status }
        { $_ -in @("w","workers") } { agt get workers }
        { $_ -in @("t","teams") } { agt get teams }
        { $_ -in @("submit","run","task") } {
            if (-not $rest) { $rest = Read-Host "  请输入任务描述" }
            Submit-Task $rest
        }
        "apply" {
            docker cp (Join-Path $root "src\agentteams\workers.yaml") "$CTRL`:/tmp/workers.yaml"
            agt apply -f /tmp/workers.yaml
        }
        default { Submit-Task $cmd }
    }
}
