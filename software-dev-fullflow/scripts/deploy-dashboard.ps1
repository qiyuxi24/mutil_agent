# ============================================================
# AgentTeams Dashboard 增量部署脚本（Windows）
#
# 背景：官方 AgentTeams v1.2.0 新增可选 Dashboard（可视化 Worker/
#   Team/Human/Manager/Matrix 管理）。当前 Windows 补丁版安装脚本
#   （agentteams-install-patched.ps1）不含 Dashboard 部署，而官方
#   Dashboard 部署逻辑在 bash 版 agentteams-install.sh 的
#   _start_dashboard()。本脚本按官方契约用纯 docker 命令增量部署，
#   无需重装整个 AgentTeams。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File deploy-dashboard.ps1
#   可选参数：-Remove（停止并移除 dashboard 容器）
#
# Dashboard 依赖：controller 容器必须运行（agentteams-controller），
#   且已生成 CLI SA token（/var/run/agentteams/cli-token）。
# ============================================================

param(
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$CTRL = "agentteams-controller"
$DASH = "agentteams-dashboard"
# 镜像源与项目其他组件一致（controller/worker 均为阿里云 registry，见 controller env AGENTTEAMS_*_IMAGE）
$REGISTRY = "higress-registry.cn-hangzhou.cr.aliyuncs.com"
$IMAGE = "${REGISTRY}/agentteams/agentteams-dashboard:latest"
$PORT = 13000          # 宿主机端口
$CONTAINER_PORT = 3000 # 容器内部端口
$NETWORK = "agentteams-net"
$VOLUME = "agentteams-dashboard-data"

function Get-ControllerEnv {
    # 读取 controller 容器全部环境变量，返回 Hashtable
    $envText = docker inspect $CTRL --format='{{range .Config.Env}}{{println .}}{{end}}' 2>$null
    $map = @{}
    foreach ($line in $envText) {
        if ($line -match '^([^=]+)=(.*)$') {
            $map[$Matches[1]] = $Matches[2]
        }
    }
    return $map
}

# ---------- Remove mode ----------
if ($Remove) {
    Write-Host ">>> 停止并移除 dashboard 容器: $DASH" -ForegroundColor Yellow
    docker stop $DASH *>$null
    docker rm -f $DASH *>$null
    Write-Host "完成。数据卷 $VOLUME 保留（若需彻底删除请手动 docker volume rm）。"
    exit 0
}

# ---------- Pre-checks ----------
if (-not (docker ps --format '{{.Names}}' 2>$null | Select-String -Quiet "^$CTRL$")) {
    Write-Host "[ERROR] $CTRL 容器未运行，Dashboard 无法启动（需要 embedded 架构）" -ForegroundColor Red
    exit 1
}

Write-Host "================ AgentTeams Dashboard 增量部署 ================" -ForegroundColor Cyan
Write-Host "镜像   : $IMAGE"
Write-Host "端口   : 127.0.0.1:${PORT} -> ${CONTAINER_PORT}"
Write-Host "网络   : $NETWORK"
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host ""

# ---------- Pull image ----------
docker image inspect $IMAGE *>$null 2>&1 | Out-Null
$imgExists = ($LASTEXITCODE -eq 0)
if (-not $imgExists) {
    Write-Host ">>> 拉取 dashboard 镜像（首次约几分钟）..." -ForegroundColor Green
    docker pull $IMAGE
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] 拉取镜像失败: $IMAGE" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "镜像已存在: $IMAGE"
}

# ---------- Remove existing container ----------
if (docker ps -a --format '{{.Names}}' 2>$null | Select-String -Quiet "^$DASH$") {
    Write-Host ">>> 移除已存在的 dashboard 容器" -ForegroundColor Green
    docker rm -f $DASH *>$null
}

# ---------- Build env args from controller ----------
Write-Host ">>> 从 controller 读取环境变量..." -ForegroundColor Green
$envC = Get-ControllerEnv

$envArgs = New-Object System.Collections.Generic.List[string]
$envArgs.Add("-e")
$envArgs.Add("AGENTTEAMS_CONTROLLER_URL=http://${CTRL}:8090")
$envArgs.Add("-e")
$envArgs.Add("NEXT_PUBLIC_MATRIX_API_URL=http://${CTRL}:6167")
$envArgs.Add("-e")
$envArgs.Add("MATRIX_HOMESERVER_ALLOWLIST=${CTRL},matrix-local.agentteams.io,matrix.org")

# MinIO / FS
$fsEndpoint = $envC["AGENTTEAMS_FS_ENDPOINT"]
if (-not $fsEndpoint) { $fsEndpoint = $envC["AGENTTEAMS_MINIO_ENDPOINT"] }
if ($fsEndpoint) {
    $fsEndpoint = $fsEndpoint -replace "127\.0\.0\.1", $CTRL -replace "localhost", $CTRL
} else {
    $fsEndpoint = "http://${CTRL}:9000"
}
$envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_FS_ENDPOINT=$fsEndpoint")

$fsBucket = $envC["AGENTTEAMS_FS_BUCKET"]
if (-not $fsBucket) { $fsBucket = $envC["AGENTTEAMS_MINIO_BUCKET"] }
if ($fsBucket) { $envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_FS_BUCKET=$fsBucket") }

$fsUser = $envC["AGENTTEAMS_FS_ACCESS_KEY"]
if (-not $fsUser) { $fsUser = $envC["AGENTTEAMS_MINIO_USER"] }
if ($fsUser) { $envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_FS_ACCESS_KEY=$fsUser") }

$fsPass = $envC["AGENTTEAMS_FS_SECRET_KEY"]
if (-not $fsPass) { $fsPass = $envC["AGENTTEAMS_MINIO_PASSWORD"] }
if ($fsPass) { $envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_FS_SECRET_KEY=$fsPass") }

# LLM
foreach ($k in @("AGENTTEAMS_LLM_PROVIDER","AGENTTEAMS_LLM_API_KEY","AGENTTEAMS_OPENAI_BASE_URL","AGENTTEAMS_DEFAULT_MODEL")) {
    if ($envC[$k]) { $envArgs.Add("-e"); $envArgs.Add("${k}=$($envC[$k])") }
}

# CLI SA token（controller 写的 /var/run/agentteams/cli-token）
Write-Host ">>> 读取 controller CLI SA token..." -ForegroundColor Green
$authToken = docker exec $CTRL sh -c "cat /var/run/agentteams/cli-token 2>/dev/null || cat /var/run/hiclaw/cli-token 2>/dev/null" 2>$null
$authToken = $authToken -replace "[\r\n]", ""
if ($authToken) {
    $envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_AUTH_TOKEN=$authToken")
} else {
    Write-Host "  [WARN] 未读到 CLI token；Dashboard 部分 API 可能需在 Higress Console 登录后可用" -ForegroundColor Yellow
}

# Admin 凭据
if ($envC["AGENTTEAMS_ADMIN_USER"]) { $envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_ADMIN_USER=$($envC['AGENTTEAMS_ADMIN_USER'])") }
if ($envC["AGENTTEAMS_ADMIN_PASSWORD"]) { $envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_ADMIN_PASSWORD=$($envC['AGENTTEAMS_ADMIN_PASSWORD'])") }

# Higress Console URL（优先显式配置，兜底自动探测 controller:8001）
$gwUrl = ""
if ($envC["AGENTTEAMS_AI_GATEWAY_ADMIN_URL"]) {
    $gwUrl = $envC["AGENTTEAMS_AI_GATEWAY_ADMIN_URL"]
    if ($gwUrl -notmatch "^https?://") { $gwUrl = "http://$gwUrl" }
    $envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_AI_GATEWAY_ADMIN_URL=$gwUrl")
} elseif (docker exec $CTRL wget -q -O- --timeout=2 http://127.0.0.1:8001/ 2>&1 | Out-Null) {
    $gwUrl = "http://${CTRL}:8001"
    $envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_AI_GATEWAY_ADMIN_URL=$gwUrl")
} else {
    # Higress Console 在 controller 内 8001，采用自动探测失败则仍注入（尽力而为）
    $gwUrl = "http://${CTRL}:8001"
    $envArgs.Add("-e"); $envArgs.Add("AGENTTEAMS_AI_GATEWAY_ADMIN_URL=$gwUrl")
}
Write-Host "  网关 Admin URL: $gwUrl"

# ---------- Create volume ----------
docker volume create $VOLUME *>$null 2>&1 | Out-Null

# ---------- docker run ----------
Write-Host ">>> 启动 dashboard 容器..." -ForegroundColor Green
$dockerCmd = @("run","-d","--name",$DASH,"--restart","unless-stopped","--network",$NETWORK,"--network-alias","dashboard.agentteams.io","-p","127.0.0.1:${PORT}:${CONTAINER_PORT}")
$dockerCmd += $envArgs.ToArray()
$dockerCmd += @("-v","${VOLUME}:/app/db",$IMAGE)

& docker $dockerCmd
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] docker run 失败" -ForegroundColor Red
    exit 1
}

# ---------- Wait for readiness ----------
Write-Host ">>> 等待 Dashboard 就绪（最多 60s）..." -ForegroundColor Green
$waited = 0
$ready = $false
while ($waited -lt 60) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:${PORT}/" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
    $waited += 2
}

if ($ready) {
    Write-Host ""
    Write-Host "================ Dashboard 部署成功 ================" -ForegroundColor Green
    Write-Host "  访问: http://127.0.0.1:${PORT}"
    Write-Host "  登录: admin / AgentTeams2026!（沿用 controller 的 AGENTTEAMS_ADMIN_USER/PASSWORD）"
    Write-Host "  说明: Dashboard 管理 Worker/Team/Human/Manager/Matrix，版本独立于 AgentTeams。"
    Write-Host "====================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  （注意：Dashboard 内 Shared Login 走 Higress Console，若提示失败，"
    Write-Host "  先确认 controller:8001 可达。Worker/Team 数据来自 controller agt API。）"
} else {
    Write-Host ""
    Write-Host "[WARN] Dashboard 启动超时，容器日志如下：" -ForegroundColor Yellow
    docker logs $DASH 2>&1 | Select-Object -Last 20
}
