# ============================================================
# start-toolchains.ps1
# 一键启动「团队自建工具链」三个 REST/MCP 服务。
#
#   code-scan        :9100   src/agentteams/toolchains/code_scan_service.py
#   test-platform    :9200   src/agentteams/toolchains/test_platform_service.py
#   host-tools       :9300   src/agentteams/toolchains/host_tools_service.py（本机操控）
#   email            :9400   src/agentteams/toolchains/email_service.py（邮箱收信，IMAP 只读）
#
# 用法（在 software-dev-fullflow 目录执行）：
#   .\scripts\start-toolchains.ps1              # 启动三个服务
#   .\scripts\start-toolchains.ps1 -Stop        # 停止已启动的服务
#   .\scripts\start-toolchains.ps1 -Health      # 只检查健康状态
# ============================================================

param(
    [switch]$Stop,
    [switch]$Health,
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $ProjectRoot) { $ProjectRoot = Split-Path $PSScriptRoot -Parent }
Set-Location $ProjectRoot

if ($Stop) {
    Get-Process -Name python -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -match "Python311" } |
        ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "已停止全部 Python 进程。" -ForegroundColor Green
    exit 0
}

if ($Health) {
    foreach ($svc in @(@{n="code-scan";p=9100}, @{n="test-platform";p=9200}, @{n="host-tools";p=9300}, @{n="email";p=9400})) {
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:$($svc.p)/health" -Method Get -TimeoutSec 3
            Write-Host "$($svc.n) [:$($svc.p)] OK: $($r.status)" -ForegroundColor Green
        } catch {
            Write-Host "$($svc.n) [:$($svc.p)] DOWN: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    exit 0
}

# ---- 启动三个服务 ----
$services = @(
    @{name="code_scan_service"; port=9100; env="CODE_SCAN_PORT"; log="scripts\_scan_svc.log"; err="scripts\_scan_svc_err.log"},
    @{name="test_platform_service"; port=9200; env="TEST_PLATFORM_PORT"; log="scripts\_test_svc.log"; err="scripts\_test_svc_err.log"},
    @{name="host_tools_service"; port=9300; env="HOST_TOOLS_PORT"; log="scripts\_host_tools.log"; err="scripts\_host_tools_err.log"},
    @{name="email_service"; port=9400; env="EMAIL_SERVICE_PORT"; log="scripts\_email.log"; err="scripts\_email_err.log"}
)

foreach ($svc in $services) {
    # 先杀可能占用端口的旧进程
    Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.Path -match "Python311" } |
        ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1

    Write-Host "==> 启动 $($svc.name) [:$($svc.port)] ..." -ForegroundColor Cyan
    $env:$($svc.env) = "$($svc.port)"
    $p = Start-Process -WindowStyle Hidden -FilePath "python" `
        -ArgumentList "-m", "src.agentteams.toolchains.$($svc.name)" `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput (Join-Path $ProjectRoot $svc.log) `
        -RedirectStandardError (Join-Path $ProjectRoot $svc.err) `
        -PassThru
    Write-Host "    PID=$($p.Id)"
    Start-Sleep -Seconds 3
}

Write-Host "`n工具链服务已启动。健康检查：.\\scripts\\start-toolchains.ps1 -Health" -ForegroundColor Green
Write-Host "注册到 Higress：.\\scripts\\register-toolchains.ps1（邮箱：register-mcp.ps1 -Name email -Mode proxy，见 mcp/README.md）" -ForegroundColor Green
