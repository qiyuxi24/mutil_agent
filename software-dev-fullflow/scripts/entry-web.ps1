# ============================================================
# Web 端入口 —— 官方 AgentTeams Dashboard
#
# 统一 Web 入口：启动官方 AgentTeams Dashboard（可视化 Worker/Team/
#   Manager/Matrix 管理），并自动打开浏览器。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File entry-web.ps1          # 启动并打开浏览器
#   powershell -ExecutionPolicy Bypass -File entry-web.ps1 -Open    # 同上
#   powershell -ExecutionPolicy Bypass -File entry-web.ps1 -NoBrowser  # 只启动不打开浏览器
#   powershell -ExecutionPolicy Bypass -File entry-web.ps1 -Stop    # 停止 Dashboard
# ============================================================

param(
    [switch]$NoBrowser,
    [switch]$Open,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$CTRL = "agentteams-controller"
$DASH = "agentteams-dashboard"
$URL = "http://127.0.0.1:13000"
$root = Split-Path -Parent $PSScriptRoot

# 打开浏览器
function Open-Browser {
    param([string]$Url)
    try { Start-Process $Url } catch {
        Write-Host "  请手动打开浏览器访问: $Url" -ForegroundColor Yellow
    }
}

# ---- 停止 ----
if ($Stop) {
    Write-Host ">>> 停止 Dashboard..." -ForegroundColor Yellow
    docker stop $DASH *>$null
    docker rm -f $DASH *>$null
    Write-Host "✓ Dashboard 已停止" -ForegroundColor Green
    exit 0
}

# ---- 检查 Docker + 平台 ----
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "[ERROR] 未检测到 Docker。请先安装并启动 Docker Desktop。" -ForegroundColor Red
    exit 1
}
$ctrlUp = docker ps --format '{{.Names}}' 2>$null | Select-String -Quiet "^$CTRL$"
if (-not $ctrlUp) {
    Write-Host "[ERROR] AgentTeams 平台未运行（缺少 $CTRL 容器）。" -ForegroundColor Red
    Write-Host "        请先启动 Docker Desktop 并部署平台。" -ForegroundColor Yellow
    exit 1
}

# ---- 启动 Dashboard（若未运行）----
$dashUp = docker ps --format '{{.Names}}' 2>$null | Select-String -Quiet "^$DASH$"
$wasJustStarted = $false
if (-not $dashUp) {
    Write-Host ">>> 启动官方 AgentTeams Dashboard..." -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "deploy-dashboard.ps1")
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Dashboard 启动失败" -ForegroundColor Red; exit 1 }
    $wasJustStarted = $true
}

Write-Host "`n✓ AgentTeams Dashboard 已就绪" -ForegroundColor Green
Write-Host "  访问地址: $URL" -ForegroundColor White
Write-Host "  登录账号: admin / AgentTeams2026!" -ForegroundColor Gray
Write-Host "  (若提示登录失败，先确认 controller 可访问 Higress 控制台 18001)`n"

# 幂等防重复：仅本次首次拉起 Dashboard 时自动开浏览器；
# 若 Dashboard 已在运行（说明之前已开过），除非显式 -Open 否则不再弹窗。
if ($wasJustStarted) {
    Open-Browser -Url $URL
} elseif ($Open) {
    Open-Browser -Url $URL
}

exit 0
