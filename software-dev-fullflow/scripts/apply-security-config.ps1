# ============================================================
# apply-security-config.ps1
# 把 src/agentteams/security-config.json 的 security 段注入所有
# agentteams-worker-* 容器的 copaw config.json，并重启使配置生效。
#
# 用法（在 software-dev-fullflow 目录执行）：
#   .\scripts\apply-security-config.ps1
# 或只处理指定 Worker：
#   .\scripts\apply-security-config.ps1 -Only fixer,tester
#
# 依赖：docker 已运行，AgentTeams 已部署（对齐 reinstall-agentteams.ps1 场景）
# ============================================================

param(
    [string]$Only = ""   # 逗号分隔的 worker 名，空 = 全部
)

$ErrorActionPreference = "Stop"

$SecurityFile = Join-Path $PSScriptRoot "..\src\agentteams\security-config.json"
$InlineSh     = Join-Path $PSScriptRoot "apply-security-in-container.sh"

if (-not (Test-Path $SecurityFile)) { Write-Error "找不到 $SecurityFile"; exit 1 }
if (-not (Test-Path $InlineSh))     { Write-Error "找不到 $InlineSh"; exit 1 }

# 找出所有 worker 容器
$containers = @(docker ps --format "{{.Names}}" | Where-Object { $_ -match '^agentteams-worker-' })
if ($containers.Count -eq 0) {
    Write-Host "未发现 agentteams-worker-* 容器，跳过。" -ForegroundColor Yellow
    exit 0
}

# 可选过滤
if ($Only) {
    $names = @($Only -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $containers = @($containers | Where-Object { $n = $_ -replace '^agentteams-worker-', ''; $names -contains $n })
    if ($containers.Count -eq 0) { Write-Host "无匹配 Worker（$Only）。" -ForegroundColor Yellow; exit 0 }
}

Write-Host "==> 目标 Worker：$($containers -join ', ')" -ForegroundColor Cyan

foreach ($c in $containers) {
    $workerName = $c -replace '^agentteams-worker-', ''
    Write-Host "`n==> 处理 $c" -ForegroundColor Cyan

    # 1. 拷贝两个文件进容器
    docker cp $SecurityFile "${c}:/tmp/security-config.json"        | Out-Null
    docker cp $InlineSh     "${c}:/tmp/apply-security-in-container.sh" | Out-Null

    # 2. 容器内合并 security 段
    docker exec $c sh /tmp/apply-security-in-container.sh

    # 3. 重启容器使配置生效
    docker restart $c | Out-Null
    Write-Host "    已重启 $c" -ForegroundColor Green
}

Write-Host "`n完成。抽查：docker exec <容器> cat /root/.copaw-worker/<name>/.copaw/config.json" -ForegroundColor Green
