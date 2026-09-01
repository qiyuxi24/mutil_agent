# ============================================================
# setup-runtime-sandbox.ps1
# 沙箱阶段三（GAP-18）：一键编排 AgentScope Runtime 沙箱 MCP 服务。
#
# 启动链路：
#   Docker 校验 → 镜像校验(可选 ACR) → 后台起 runtime-sandbox-mcp.py
#   （streamable-http 于 localhost:<Port>/mcp）→ 健康轮询 → 可选注册 Higress
#
# 用法（在 software-dev-fullflow 目录执行）：
#   启动：        .\scripts\setup-runtime-sandbox.ps1
#   指定端口/镜像源： .\scripts\setup-runtime-sandbox.ps1 -Port 8322 -Registry agentscope-registry.ap-southeast-1.cr.aliyuncs.com
#   注册 Higress：.\scripts\setup-runtime-sandbox.ps1 -Register
#   停止：        .\scripts\setup-runtime-sandbox.ps1 -Stop
#
# 依赖：Docker 已运行；demo\.venv 已装 agentscope-runtime + uvicorn
# ============================================================

param(
    [int]$Port = 8322,
    [string]$Registry = "",
    [string]$Workspace = "data\runtime-sandbox-ws",
    [switch]$Register,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$py = ".\demo\.venv\Scripts\python.exe"
$pidFile = "data\logs\runtime-sandbox-mcp.pid"
$outLog  = "data\logs\runtime-sandbox-mcp.out.log"
$errLog  = "data\logs\runtime-sandbox-mcp.err.log"
$mcpUrl  = "http://127.0.0.1:$Port/mcp"

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-OK  ($msg) { Write-Host "    $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "    $msg" -ForegroundColor Red }

# ---------------- Stop 模式 ----------------
if ($Stop) {
    Write-Step "停止 Runtime Sandbox MCP 服务 ..."
    # 1) 按 pid 文件停止（直接启动 python 后，此 pid 即真实 python 进程）
    if (Test-Path $pidFile) {
        $oldPid = (Get-Content $pidFile).Trim()
        if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Stop-Process -Id $oldPid -Force
            Write-OK "已停止进程 $oldPid"
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    # 2) 无条件兜底：按命令行匹配，确保残留 python 子进程（含旧版 cmd 壳遗留）被停
    $residual = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match "runtime-sandbox-mcp.py" }
    if ($residual) {
        foreach ($p in $residual) {
            Stop-Process -Id $p.ProcessId -Force
            Write-OK "已停止残留进程 $($p.ProcessId)"
        }
    } else {
        Write-OK "无残留 python 进程"
    }
    $left = docker ps --format "{{.Names}}" | Select-String "runtime_sandbox"
    if ($left) {
        Write-Host "    提示：以下沙箱容器可能残留，可手动清理:" -ForegroundColor Yellow
        $left | ForEach-Object { Write-Host "      docker rm -f $_" -ForegroundColor Yellow }
    } else {
        Write-OK "无残留沙箱容器"
    }
    exit 0
}

# ---------------- 前置校验 ----------------
Write-Step "前置校验 ..."
if (-not (docker ps --format "{{.ID}}" | Select-Object -First 1)) {
    Write-Fail "Docker 不可用，请先启动 Docker Desktop"
    exit 1
}
Write-OK "Docker 正常"

if (-not (Test-Path $py)) {
    Write-Fail "未找到 $py，请先创建 demo\.venv 并安装 agentscope-runtime"
    exit 1
}
Write-OK "venv Python 存在"

# ---------------- 镜像校验 ----------------
Write-Step "镜像校验 ..."
$image = "runtime-sandbox-base:latest"
if ($Registry) {
    $full = "$Registry/agentscope/$image"
} else {
    $full = "agentscope/$image"
}
$have = docker images --format "{{.Repository}}:{{.Tag}}" | Where-Object { $_ -eq $full }
if (-not $have) {
    Write-Host "    本地无 $full，尝试拉取（大陆建议加 -Registry 走阿里云 ACR）..." -ForegroundColor Yellow
    docker pull $full 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "拉取镜像失败: $full"
        exit 1
    }
}
Write-OK "镜像就绪: $full"

# ---------------- 启动服务 ----------------
Write-Step "启动 runtime-sandbox-mcp.py (端口 $Port) ..."
New-Item -ItemType Directory -Force -Path "data\logs" | Out-Null
New-Item -ItemType Directory -Force -Path $Workspace | Out-Null

if (Test-Path $pidFile) {
    $oldPid = (Get-Content $pidFile).Trim()
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "    服务已在运行 (pid=$oldPid)，跳过启动" -ForegroundColor Yellow
        $proc = Get-Process -Id $oldPid
    } else {
        Remove-Item $pidFile -Force
    }
}

if (-not $proc) {
    # 直接启动 python.exe（不用 cmd 壳），确保 $proc.Id 即真实 python 进程 pid，
    # 否则 -Stop 停 cmd 壳后 python 子进程仍存活导致端口残留。
    $pyArgs = @(
        "scripts\runtime-sandbox-mcp.py",
        "--port", "$Port",
        "--workspace-dir", "$Workspace"
    )
    if ($Registry) {
        # 环境变量注入到子进程：先设当前会话环境，再直接起 python
        $env:RUNTIME_SANDBOX_REGISTRY = $Registry
    }
    $proc = Start-Process -FilePath $py -ArgumentList $pyArgs `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
        -WindowStyle Hidden -PassThru
    # 避免 RUNTIME_SANDBOX_REGISTRY 污染后续调用
    if ($Registry) { Remove-Item Env:\RUNTIME_SANDBOX_REGISTRY -ErrorAction SilentlyContinue }
    $proc.Id | Out-File $pidFile -Encoding ascii
    Write-OK "已启动 pid=$($proc.Id)"
}

# ---------------- 健康轮询 ----------------
Write-Step "健康轮询 GET $mcpUrl ..."
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 3
    $code = curl.exe -s -o NUL -w "%{http_code}" -H "Accept: application/json, text/event-stream" $mcpUrl
    # streamable-http 端点对 GET 返回 405/406 均表示服务在线；000 表示连不上
    if ($code -ne "000") { $ok = $true; Write-OK "HTTP /mcp => $code（服务在线）"; break }
}
if (-not $ok) {
    Write-Fail "健康检查超时，查看日志:"
    if (Test-Path $outLog) { Get-Content $outLog -Tail 10 }
    if (Test-Path $errLog) { Get-Content $errLog -Tail 15 }
    exit 1
}

$sid = (Select-String -Path $outLog -Pattern "sandbox_id=(\S+)" -ErrorAction SilentlyContinue | Select-Object -Last 1).Matches.Groups[1].Value
if ($sid) { Write-OK "sandbox_id: $sid" }

Write-Host ""
Write-Host "==== Runtime Sandbox MCP 就绪 ====" -ForegroundColor Green
Write-Host "  MCP 端点: $mcpUrl"
Write-Host "  日志:      $outLog"
Write-Host "  验证:      demo\.venv\Scripts\python.exe scripts\verify-runtime-sandbox-mcp.py --url $mcpUrl"
Write-Host "  SDK 直连:  demo\.venv\Scripts\python.exe scripts\verify-runtime-sandbox.py"
Write-Host ""

# ---------------- 注册 Higress（可选） ----------------
if ($Register) {
    Write-Step "注册 Higress MCP (proxy 模式, host.docker.internal:$Port) ..."
    & ".\scripts\register-mcp.ps1" `
        -Name "runtime-sandbox" `
        -Mode proxy `
        -Url "http://host.docker.internal:$Port/mcp" `
        -Transport http
    if ($LASTEXITCODE -eq 0) {
        Write-OK "已注册并授权 Worker。可在 Higress 控制台 http://127.0.0.1:18001 查看 mcp-runtime-sandbox"
    } else {
        Write-Host "    register-mcp.ps1 退出码 $LASTEXITCODE，请检查 AgentTeams/Higress" -ForegroundColor Yellow
    }
}
