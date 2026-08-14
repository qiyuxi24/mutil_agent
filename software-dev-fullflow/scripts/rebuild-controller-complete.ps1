# ============================================================
# 用完整 env 重建 agentteams-controller（指向逆向适配层）
# 从快照读取全部 env，只替换 LLM 上游相关，其余全部保留。
# 用法: powershell -ExecutionPolicy Bypass -File rebuild-controller-complete.ps1
# ============================================================
$ErrorActionPreference = "Stop"

$snapshot = Join-Path $PSScriptRoot "controller-env-snapshot-20260814.json"
if (-not (Test-Path $snapshot)) {
    Write-Host "[ERROR] 找不到快照: $snapshot" -ForegroundColor Red
    exit 1
}
$envList = Get-Content $snapshot -Raw | ConvertFrom-Json

# 显式构造 docker run 命令（字符串拼接，避免 PowerShell 数组传参的坑）
$cmd = "docker run -d --name agentteams-controller --network agentteams-net "
$cmd += "-v `"//var/run/docker.sock:/var/run/docker.sock`" "
$cmd += "--security-opt label=disable "
$cmd += "-p `"127.0.0.1:18001:8001`" "
$cmd += "-p `"127.0.0.1:18080:8080`" "
$cmd += "-p `"127.0.0.1:18088:8088`" "
$cmd += "-v `"agentteams-data:/data`" "
$cmd += "-v `"/run/desktop/mnt/host/c/Users/34239/agentteams-manager:/root/agentteams-fs/agents/manager`" "

foreach ($entry in $envList) {
    # 跳过镜像默认 env
    if ($entry -match "^PATH=" -or $entry -match "^JAVA_HOME=" -or $entry -match "^DEBIAN_FRONTEND=") { continue }
    if ($entry -match "^AGENTTEAMS_OPENAI_BASE_URL=") {
        $cmd += "-e `"AGENTTEAMS_OPENAI_BASE_URL=http://host.docker.internal:9001/v1`" "
        continue
    }
    if ($entry -match "^AGENTTEAMS_LLM_API_KEY=") {
        $cmd += "-e `"AGENTTEAMS_LLM_API_KEY=sk-reverse-gateway-local`" "
        continue
    }
    # 其他 env 用单引号包裹值，防止特殊字符(如 ! 在双引号里被展开)
    $key = ($entry -split "=", 2)[0]
    $val = ($entry -split "=", 2)[1]
    $cmd += "-e `"$key=$val`" "
}
$cmd += "--restart unless-stopped "
$cmd += "higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-embedded:latest"

Write-Host ">>> 重建 controller（完整 env，LLM 指向适配层）..." -ForegroundColor Green
Write-Host "    OPENAI_BASE_URL -> http://host.docker.internal:9001/v1" -ForegroundColor Yellow
Write-Output $cmd | Out-File "$PSScriptRoot\last-rebuild-cmd.txt" -Encoding utf8

# 用 cmd 执行（避免 PowerShell 对 ! 的展开问题）
cmd /c $cmd
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] docker run 失败，退出码 $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host ">>> 容器已创建，等待启动..." -ForegroundColor Green
Start-Sleep -Seconds 20
Write-Host ">>> 验证 controller 状态与端口：" -ForegroundColor Green
docker ps --filter name=agentteams-controller --format "{{.Names}}: {{.Status}}"
docker exec agentteams-controller sh -c 'printenv AGENTTEAMS_OPENAI_BASE_URL' 2>&1
