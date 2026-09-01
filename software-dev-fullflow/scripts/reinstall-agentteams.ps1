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

# ============================================================
# 配置加载：统一从项目根目录 .env 读取（模板：software-dev-fullflow\.env.example）
# 避免配置散落 / 凭据硬编码。读取顺序：真实环境变量 > .env > 内置默认值。
# ============================================================
$script:root = Split-Path -Parent $PSScriptRoot
$script:dotenv = Join-Path $script:root ".env"

# 读取 .env 键值（简单 KEY=VALUE 解析，忽略 # 注释行）
function Read-Dotenv {
    param([string]$Path)
    $map = @{}
    if (Test-Path $Path) {
        Get-Content $Path | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
                $k, $v = $line -split "=", 2
                $map[$k.Trim()] = $v.Trim()
            }
        }
    }
    return $map
}
# 读取配置：真实环境变量优先，其次 .env，最后默认值
function Get-Config {
    param([string]$Key, [string]$Default = "")
    $envVal = [Environment]::GetEnvironmentVariable($Key, "Process")
    if ($envVal) { return $envVal }
    if ($script:envMap.ContainsKey($Key) -and $script:envMap[$Key]) { return $script:envMap[$Key] }
    return $Default
}
$script:envMap = Read-Dotenv $script:dotenv

# ---------- LLM（OpenAI 兼容）----------
$env:AGENTTEAMS_LLM_PROVIDER = Get-Config "AGENTTEAMS_LLM_PROVIDER" "openai-compat"
$env:AGENTTEAMS_DEFAULT_MODEL = Get-Config "AGENTTEAMS_DEFAULT_MODEL" "deepseek-v4-flash"
$env:AGENTTEAMS_OPENAI_BASE_URL = Get-Config "AGENTTEAMS_OPENAI_BASE_URL" "https://api.deepseek.com/v1"
# LLM API Key：AGENTTEAMS_LLM_API_KEY 优先，回退 DEEPSEEK_API_KEY
$env:AGENTTEAMS_LLM_API_KEY = Get-Config "AGENTTEAMS_LLM_API_KEY" ""
if (-not $env:AGENTTEAMS_LLM_API_KEY) { $env:AGENTTEAMS_LLM_API_KEY = Get-Config "DEEPSEEK_API_KEY" "" }

# ---------- 管理后台账号 ----------
$env:AGENTTEAMS_ADMIN_USER = Get-Config "AGENTTEAMS_ADMIN_USER" "admin"
# 密码：优先 .env 已有值；否则自动生成，并回写 .env（避免硬编码）
$env:AGENTTEAMS_ADMIN_PASSWORD = Get-Config "AGENTTEAMS_ADMIN_PASSWORD" ""
if (-not $env:AGENTTEAMS_ADMIN_PASSWORD) {
    $generated = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
    $env:AGENTTEAMS_ADMIN_PASSWORD = "AGT-" + $generated
    Add-Content -Path $script:dotenv -Value "`n# 由 reinstall-agentteams.ps1 自动生成`nAGENTTEAMS_ADMIN_PASSWORD=$($env:AGENTTEAMS_ADMIN_PASSWORD)"
    Write-Host "  [info] 已生成 AGENTTEAMS_ADMIN_PASSWORD 并写入 $script:dotenv" -ForegroundColor Yellow
}
$env:AGENTTEAMS_MANAGER_PASSWORD = $env:AGENTTEAMS_ADMIN_PASSWORD

# ---------- 非交互 + 本地模式 ----------
$env:AGENTTEAMS_NON_INTERACTIVE = Get-Config "AGENTTEAMS_NON_INTERACTIVE" "1"
$env:AGENTTEAMS_LOCAL_ONLY = Get-Config "AGENTTEAMS_LOCAL_ONLY" "1"
$env:AGENTTEAMS_LANGUAGE = Get-Config "AGENTTEAMS_LANGUAGE" "zh"
$env:AGENTTEAMS_MATRIX_E2EE = Get-Config "AGENTTEAMS_MATRIX_E2EE" "0"
$env:AGENTTEAMS_DEFAULT_WORKER_RUNTIME = Get-Config "AGENTTEAMS_DEFAULT_WORKER_RUNTIME" "copaw"
$env:AGENTTEAMS_MANAGER_RUNTIME = Get-Config "AGENTTEAMS_MANAGER_RUNTIME" "copaw"

# ---------- 校验 ----------
if (-not $env:AGENTTEAMS_LLM_API_KEY) {
    Write-Host "[ERROR] 未找到 LLM API Key（AGENTTEAMS_LLM_API_KEY / DEEPSEEK_API_KEY）" -ForegroundColor Red
    Write-Host "  请在 $script:dotenv 中填入（参考 $script:root\.env.example），例如：" -ForegroundColor Yellow
    Write-Host "    DEEPSEEK_API_KEY=sk-..." -ForegroundColor Yellow
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
