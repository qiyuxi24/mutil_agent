# ============================================================
# 重建 agentteams-controller，把 LLM 上游从 DeepSeek 官方切到逆向适配层
# （reverse_gateway.py，宿主 9001 端口）
#
# 前提：
#   1. reverse_gateway.py 已在宿主运行（python reverse_gateway.py）
#   2. 已确认容器内可访问 host.docker.internal:9001
#   3. 环境变量快照存在：scripts/controller-env-snapshot-20260814.json
#
# 回滚：把 AGENTTEAMS_OPENAI_BASE_URL 改回 https://api.deepseek.com/v1 再跑本脚本
# ============================================================
$ErrorActionPreference = "Stop"

$snapshot = Join-Path $PSScriptRoot "controller-env-snapshot-20260814.json"
if (-not (Test-Path $snapshot)) {
    Write-Host "[ERROR] 找不到环境快照: $snapshot" -ForegroundColor Red
    exit 1
}

# 读取快照 env
$envList = Get-Content $snapshot -Raw | ConvertFrom-Json

# 新的 LLM 上游：指向适配层（跳过系统 PATH/JAVA_HOME 等镜像默认 env）
$reverseBase = "http://host.docker.internal:9001/v1"
$llmApiKey = "sk-reverse-gateway-local"   # 适配层不校验 key，透传逆向凭据

$dockerArgs = @("run", "-d", "--name", "agentteams-controller")
$dockerArgs += @("--network", "agentteams-net")
$dockerArgs += @("-v", "//var/run/docker.sock:/var/run/docker.sock")
$dockerArgs += @("--security-opt", "label=disable")
$dockerArgs += @("-p", "127.0.0.1:18001:8001")   # Higress 管理面 (admin)
$dockerArgs += @("-p", "127.0.0.1:18080:8080")   # AI 网关数据面
$dockerArgs += @("-p", "127.0.0.1:18088:8088")   # Element Web
$dockerArgs += @("-v", "agentteams-data:/data")
$dockerArgs += @("-v", "/run/desktop/mnt/host/c/Users/34239/agentteams-manager:/root/agentteams-fs/agents/manager")

# 注入 env（跳过镜像默认的 PATH/JAVA_HOME/DEBIAN_FRONTEND）
foreach ($entry in $envList) {
    if ($entry -match "^PATH=" -or $entry -match "^JAVA_HOME=" -or $entry -match "^DEBIAN_FRONTEND=") {
        continue
    }
    if ($entry -match "^AGENTTEAMS_OPENAI_BASE_URL=") {
        $dockerArgs += @("-e", "AGENTTEAMS_OPENAI_BASE_URL=$reverseBase")
        continue
    }
    if ($entry -match "^AGENTTEAMS_LLM_API_KEY=") {
        $dockerArgs += @("-e", "AGENTTEAMS_LLM_API_KEY=$llmApiKey")
        continue
    }
    $dockerArgs += @("-e", $entry)
}

$dockerArgs += @("--restart", "unless-stopped")
$dockerArgs += "higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-embedded:latest"

Write-Host "================ 重建 agentteams-controller ================" -ForegroundColor Cyan
Write-Host "LLM 上游: https://api.deepseek.com/v1  ->  $reverseBase" -ForegroundColor Yellow
Write-Host "端口: 18001(admin) 18080(gateway) 18088(element)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. 停并删除旧 controller
Write-Host ">>> 停止并删除旧 controller ..." -ForegroundColor Green
docker stop agentteams-controller *>$null
docker rm agentteams-controller *>$null

# 2. 用新配置重建
Write-Host ">>> 重建 controller（指向适配层）..." -ForegroundColor Green
& docker @dockerArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] docker run 失败，退出码 $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host ">>> 等待 controller 启动..." -ForegroundColor Green
Start-Sleep -Seconds 15

# 3. 检查 controller 日志是否有 LLM provider 初始化错误
Write-Host ">>> 检查 controller 日志（最近 30 行）..." -ForegroundColor Green
docker logs --tail 30 agentteams-controller 2>&1 | Select-Object -Last 30

Write-Host ""
Write-Host "================ 完成 ================" -ForegroundColor Green
Write-Host "下一步验证: 容器内 curl AI 网关测试 LLM（见下一步）" -ForegroundColor Yellow
