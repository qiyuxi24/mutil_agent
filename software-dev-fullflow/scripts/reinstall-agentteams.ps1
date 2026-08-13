# ============================================================
# AgentTeams 全新重装脚本（Windows）
#
# 背景：官方 agentteams-install.ps1 在 Windows 上漏掉了 Matrix
#   AppService token（AS_TOKEN/HS_TOKEN）的生成与透传，导致
#   agentteams-controller 启动即 panic。本脚本：
#   1. 清理残缺 env / 数据卷 / 网络 / 容器
#   2. 用补丁版 agentteams-install-patched.ps1 以非交互模式重装
#   （补丁已修复 token 问题，见 agentteams-install-patched.ps1）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File reinstall-agentteams.ps1
# ============================================================

# 用 Continue 而非 Stop：安装脚本内部大量 docker 调用会输出 stderr（如 network not found），
# 若继承 Stop 会被提升为终止性错误导致安装中止。
$ErrorActionPreference = "Continue"

# ---------- 配置（可自行修改） ----------
# DeepSeek（OpenAI 兼容）——与 demo/.env 一致
$env:AGENTTEAMS_LLM_PROVIDER = "openai-compat"
$env:AGENTTEAMS_DEFAULT_MODEL = "deepseek-v4-flash"
$env:AGENTTEAMS_OPENAI_BASE_URL = "https://api.deepseek.com/v1"
$env:AGENTTEAMS_LLM_API_KEY = $env:DEEPSEEK_API_KEY   # 从当前环境读取，或在此填硬编码

# 管理后台账号
$env:AGENTTEAMS_ADMIN_USER = "admin"
$env:AGENTTEAMS_ADMIN_PASSWORD = "AgentTeams2026!"
$env:AGENTTEAMS_MANAGER_PASSWORD = "AgentTeams2026!"

# 非交互 + 本地模式
$env:AGENTTEAMS_NON_INTERACTIVE = "1"
$env:AGENTTEAMS_LOCAL_ONLY = "1"
$env:AGENTTEAMS_LANGUAGE = "zh"
$env:AGENTTEAMS_MATRIX_E2EE = "0"
$env:AGENTTEAMS_DEFAULT_WORKER_RUNTIME = "copaw"
$env:AGENTTEAMS_MANAGER_RUNTIME = "copaw"

# ---------- 校验 ----------
if (-not $env:AGENTTEAMS_LLM_API_KEY) {
    Write-Host "[ERROR] 未找到 AGENTTEAMS_LLM_API_KEY（DeepSeek API Key）" -ForegroundColor Red
    Write-Host "  请在运行前设置：`$env:DEEPSEEK_API_KEY='sk-...' 或在此脚本中填硬编码" -ForegroundColor Yellow
    exit 1
}

$patch = Join-Path $PSScriptRoot "agentteams-install-patched.ps1"
if (-not (Test-Path $patch)) {
    Write-Host "[ERROR] 找不到补丁版安装脚本：$patch" -ForegroundColor Red
    exit 1
}

$envFile = "$env:USERPROFILE\agentteams-manager.env"

Write-Host ""
Write-Host "================ AgentTeams 全新重装 ================" -ForegroundColor Cyan
Write-Host "LLM      : $($env:AGENTTEAMS_DEFAULT_MODEL) @ $($env:AGENTTEAMS_OPENAI_BASE_URL)"
Write-Host "Env 文件 : $envFile"
Write-Host "补丁脚本 : $patch"
Write-Host "警告: 将删除现有 env 文件、agentteams-data 卷、agentteams-net 网络及残留容器！" -ForegroundColor Yellow
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host ""

if ($env:AGENTTEAMS_CONFIRM_REINSTALL -ne "yes") {
    Write-Host "10 秒后开始清理并重装（若要取消，按 Ctrl+C）..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}

# ---------- 1. 清理现有 AgentTeams 残留 ----------
Write-Host ""
Write-Host ">>> 第 1 步：清理现有 AgentTeams 残留" -ForegroundColor Green

# 停/删 worker + manager + controller 容器
docker ps -a --format "{{.Names}}" 2>$null | Select-String "^agentteams-(worker|manager|controller)" | ForEach-Object {
    $name = $_.ToString().Trim()
    Write-Host "  删除容器: $name"
    docker stop $name *>$null
    docker rm $name *>$null
}

# 删除数据卷
if (docker volume ls -q 2>$null | Select-String "^agentteams-data$") {
    Write-Host "  删除数据卷: agentteams-data"
    docker volume rm agentteams-data *>$null
}

# 删除网络
if (docker network ls --format "{{.Name}}" 2>$null | Select-String "^agentteams-net$") {
    Write-Host "  删除网络: agentteams-net"
    docker network rm agentteams-net *>$null
}

# 删除残缺 env 文件
if (Test-Path $envFile) {
    Write-Host "  删除残缺 env 文件: $envFile"
    Remove-Item -Force $envFile
}

# 删除残缺工作空间
$ws = "$env:USERPROFILE\agentteams-manager"
if (Test-Path $ws) {
    Write-Host "  删除工作空间: $ws"
    Remove-Item -Recurse -Force $ws -ErrorAction SilentlyContinue
}

Write-Host "  清理完成。"
Write-Host ""

# ---------- 2. 用补丁版脚本非交互重装 ----------
Write-Host ">>> 第 2 步：执行补丁版安装脚本（非交互）" -ForegroundColor Green
Write-Host "    这可能耗时 10-20 分钟（拉取镜像 + 启动容器）..." -ForegroundColor Yellow
Write-Host ""

Push-Location (Split-Path $patch)
try {
    & $patch
} finally {
    Pop-Location
}

$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] AgentTeams 安装失败，退出码 $code" -ForegroundColor Red
    exit $code
}

Write-Host ""
Write-Host "================ 安装完成 ================" -ForegroundColor Green
Write-Host "1. 浏览器打开 http://127.0.0.1:18088 登录 Element Web"
Write-Host "   账号: $env:AGENTTEAMS_ADMIN_USER / 密码: $env:AGENTTEAMS_ADMIN_PASSWORD"
Write-Host "2. 排查日志: docker exec agentteams-controller cat /var/log/agentteams/agentteams-controller-error.log"
Write-Host "==========================================" -ForegroundColor Green
