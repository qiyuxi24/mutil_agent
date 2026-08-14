# ============================================================
# 通过 Matrix 给 AgentTeams Manager 派任务
# 用法: powershell -ExecutionPolicy Bypass -File dispatch-task.ps1 "任务内容"
# ============================================================
param(
    [Parameter(Mandatory=$true)]
    [string]$Task
)

$ErrorActionPreference = "Stop"

# 用 docker exec 在 controller 容器内执行（容器内有 curl）
$loginResp = docker exec agentteams-controller sh -c 'curl -s --connect-timeout 8 -X POST "http://127.0.0.1:6167/_matrix/client/v3/login" -H "Content-Type: application/json" -d "{\"type\":\"m.login.password\",\"identifier\":{\"type\":\"m.id.user\",\"user\":\"admin\"},\"password\":\"AgentTeams2026!\",\"initial_device_display_name\":\"task-dispatcher\"}"' 2>&1
$token = ($loginResp | ConvertFrom-Json).access_token
if (-not $token) {
    Write-Host "[ERROR] Matrix 登录失败: $loginResp" -ForegroundColor Red
    exit 1
}
Write-Host "✓ Matrix 登录成功" -ForegroundColor Green

# Manager 的房间 ID（从 agt get managers 获取）
$roomId = "!rWJbhh3Nl2NtRQWNrc:matrix-local.agentteams.io:18080"

# 构造 JSON 消息（sendMessage 事件）
$escapedTask = $Task.Replace('\', '\\').Replace('"', '\"').Replace('`n', '\n').Replace('`r', '')
$msgBody = @{
    msgtype = "m.text"
    body = $Task
} | ConvertTo-Json -Compress

# URL 编码房间 ID
$encodedRoom = $roomId.Replace('!', '%21').Replace(':', '%3A')
$txnId = [Guid]::NewGuid().ToString("N")

$sendUrl = "http://127.0.0.1:6167/_matrix/client/v3/rooms/$encodedRoom/send/m.room.message/$txnId"
$sendResp = docker exec agentteams-controller sh -c "curl -s --connect-timeout 10 -X PUT '$sendUrl' -H 'Authorization: Bearer $token' -H 'Content-Type: application/json' -d '$msgBody'" 2>&1
Write-Host "✓ 任务已发送到 Manager 房间" -ForegroundColor Green
Write-Host "  响应: $sendResp"
Write-Host "  任务: $($Task.Substring(0, [Math]::Min(80, $Task.Length)))..."
