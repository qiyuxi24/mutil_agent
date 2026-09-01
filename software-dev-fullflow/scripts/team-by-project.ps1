# team-by-project.ps1 — HR 按项目「拉人进群」生成 Team（阶段 D1）
#
# 用途：为「搭建」类项目动态组建团队（HR 招聘经理的核心动作），
#       把选定 Worker 拉进一个项目级 Team，并指定 Team Leader 协调。
# 对比 rnd-team.yaml（固定修复模式 6 人），本脚本生成「按项目定制的 Team」。
#
# 用法（在 controller 容器可访问的宿主上）：
#   powershell -ExecutionPolicy Bypass -File scripts/team-by-project.ps1 `
#     -TeamName proj-T0001 -Leader team-leader -Workers architect,backend,tester,deployer `
#     -Description "搭建带POST的官网"
#
# 说明：Workers 参数里的 Worker CR 必须已存在（HR 先用 dynamic-hiring 确保）。
#       生成的 YAML 会写到 src/agentteams/teams/ 下，再 docker cp + agt apply。
param(
    [Parameter(Mandatory = $true)][string]$TeamName,
    [Parameter(Mandatory = $false)][string]$Leader = "team-leader",
    [Parameter(Mandatory = $true)][string]$Workers,   # 逗号分隔的 worker 名单
    [Parameter(Mandatory = $false)][string]$Description = "按项目动态组建的研发团队",
    [Parameter(Mandatory = $false)][string]$Controller = "agentteams-controller"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$teamsDir = Join-Path $root "src\agentteams\teams"
New-Item -ItemType Directory -Force -Path $teamsDir | Out-Null

# 校验 worker 名单不能为空、leader 唯一
$workerList = @($Workers.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($workerList.Count -eq 0) { throw "Workers 不能为空" }

# 生成 Team YAML（workerMembers：1 个 leader + N 个 worker）
$members = @("    - { name: $Leader, role: team_leader }")
foreach ($w in $workerList) {
    $members += "    - { name: $w, role: worker }"
}
$memberBlock = $members -join "`n"

$yaml = @"
apiVersion: agentteams.io/v1beta1
kind: Team
metadata:
  name: $TeamName
spec:
  description: $Description
  teamName: $TeamName
  peerMentions: true
  heartbeatEvery: 30m
  workerMembers:
$memberBlock
"@

$yamlPath = Join-Path $teamsDir "$TeamName.yaml"
Set-Content -Path $yamlPath -Value $yaml -Encoding UTF8
Write-Host "✓ Team YAML 已生成: $yamlPath"
Write-Host "  Leader: $Leader | Workers: $($workerList -join ', ')"

# 可选：自动 apply 到 controller（容器内）
if ($env:TEAM_APPLY -eq "1") {
    Write-Host "→ 应用 Team CR 到 controller ..."
    docker cp $yamlPath "${Controller}:/tmp/$TeamName.yaml" | Out-Null
    docker exec $Controller agt apply -f "/tmp/$TeamName.yaml"
    docker exec $Controller agt get team $TeamName -o json | Select-String -Pattern "phase|readyWorkers"
}

Write-Host ""
Write-Host "下一步（手动，若未自动 apply）:"
Write-Host "  docker cp $yamlPath ${Controller}:/tmp/$TeamName.yaml"
Write-Host "  docker exec $Controller agt apply -f /tmp/$TeamName.yaml"
Write-Host "  docker exec $Controller agt get team $TeamName -o json"
