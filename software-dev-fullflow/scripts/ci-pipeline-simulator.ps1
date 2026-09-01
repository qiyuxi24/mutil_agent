# ============================================================
# ci-pipeline-simulator.ps1
# CI/CD 流水线模拟器（初赛 L1 shell 兜底方案）
#
# 模拟完整流水线：构建 → 测试 → 部署 → 审批 → 回滚
# 与 mcp-ci.yaml 的 5 个工具对齐，供 releaser Worker 调用。
#
# 用法：
#   .\scripts\ci-pipeline-simulator.ps1 -Action trigger -Repo "test/repo" -Branch "main"
#   .\scripts\ci-pipeline-simulator.ps1 -Action status -PipelineId "pipe-0001"
#   .\scripts\ci-pipeline-simulator.ps1 -Action log -PipelineId "pipe-0001" -Stage "build"
#   .\scripts\ci-pipeline-simulator.ps1 -Action approve -PipelineId "pipe-0001"
#   .\scripts\ci-pipeline-simulator.ps1 -Action rollback -Repo "test/repo" -Version "v1.2.3"
#
# 状态文件：shared/ci/pipelines.json（模拟流水线状态持久化）
# ============================================================

param(
    [Parameter(Mandatory)]
    [ValidateSet("trigger", "status", "log", "approve", "rollback")]
    [string]$Action,

    [string]$Repo = "",
    [string]$Branch = "main",
    [string]$PipelineId = "",
    [string]$Stage = "",
    [string]$Version = "",
    [string]$Environment = "production"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$StateDir = Join-Path $ProjectRoot "shared\ci"
$StateFile = Join-Path $StateDir "pipelines.json"

# 确保状态目录存在
if (-not (Test-Path $StateDir)) {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
}

# 加载/保存状态（使用 -AsHashtable 支持属性赋值）
function Load-State {
    if (Test-Path $StateFile) {
        $json = Get-Content $StateFile -Raw
        if ($json) {
            return $json | ConvertFrom-Json -AsHashtable
        }
    }
    return @{}
}

function Save-State($state) {
    $state | ConvertTo-Json -Depth 10 | Set-Content $StateFile -Encoding UTF8
}

# 生成 ID
$counterFile = Join-Path $StateDir ".counter"
function Next-Id {
    $c = 0
    if (Test-Path $counterFile) {
        $c = [int](Get-Content $counterFile -Raw)
    }
    $c++
    $c | Set-Content $counterFile
    return "pipe-{0:D4}" -f $c
}

# 模拟构建日志
function Simulate-BuildLog {
    return @"
[BUILD] Starting build for $Repo @ $Branch ...
[BUILD] Installing dependencies... OK
[BUILD] Compiling source... OK
[BUILD] Running linters... OK (0 warnings)
[BUILD] Build artifact: dist/app.tar.gz (12.3 MB)
[BUILD] Build completed successfully in 45s
"@
}

function Simulate-TestLog {
    return @"
[TEST] Running test suite: unit + integration + e2e
[TEST] unit tests: 42 passed, 0 failed
[TEST] integration tests: 8 passed, 0 failed
[TEST] e2e tests: 3 passed, 0 failed
[TEST] Coverage: 87.3% (threshold: 80%)
[TEST] All tests passed in 2m 15s
"@
}

function Simulate-DeployLog {
    return @"
[DEPLOY] Deploying to $Environment ...
[DEPLOY] Health check: OK
[DEPLOY] Canary traffic: 10% → 50% → 100%
[DEPLOY] Smoke tests: PASS
[DEPLOY] Deployment completed in 1m 30s
"@
}

# ---- 动作分发 ----

switch ($Action) {
    "trigger" {
        if (-not $Repo) {
            Write-Error "trigger 需要 -Repo"
            exit 1
        }
        $id = Next-Id
        $state = Load-State
        $state[$id] = @{
            id = $id
            repo = $Repo
            branch = $Branch
            status = "running"
            stage = "build"
            stages = @{
                build = @{ status = "running"; log = "" }
                test = @{ status = "pending"; log = "" }
                deploy = @{ status = "pending"; log = "" }
            }
            approved = $false
            created_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
        }
        Save-State $state

        # 模拟流水线执行（异步，这里简化同步完成）
        Start-Sleep -Seconds 1
        $state = Load-State
        $state[$id]["stages"]["build"]["status"] = "completed"
        $state[$id]["stages"]["build"]["log"] = (Simulate-BuildLog)
        $state[$id]["stage"] = "test"
        $state[$id]["stages"]["test"]["status"] = "running"
        $state[$id]["stages"]["test"]["log"] = (Simulate-TestLog)
        Save-State $state

        Start-Sleep -Seconds 1
        $state = Load-State
        $state[$id]["stages"]["test"]["status"] = "completed"
        $state[$id]["stage"] = "deploy"
        $state[$id]["stages"]["deploy"]["status"] = "awaiting_approval"
        Save-State $state

        Write-Host "流水线已触发: $id" -ForegroundColor Green
        Write-Host "  仓库: $Repo" -ForegroundColor Gray
        Write-Host "  分支: $Branch" -ForegroundColor Gray
        Write-Host "  状态: 等待部署审批" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "下一步: .\scripts\ci-pipeline-simulator.ps1 -Action approve -PipelineId $id" -ForegroundColor Cyan
    }

    "status" {
        if (-not $PipelineId) {
            Write-Error "status 需要 -PipelineId"
            exit 1
        }
        $state = Load-State
        if (-not $state[$PipelineId]) {
            Write-Error "流水线不存在: $PipelineId"
            exit 1
        }
        $p = $state[$PipelineId]
        Write-Host "流水线: $($p['id'])" -ForegroundColor Cyan
        Write-Host "  仓库: $($p['repo'])" -ForegroundColor Gray
        Write-Host "  分支: $($p['branch'])" -ForegroundColor Gray
        Write-Host "  状态: $($p['status'])" -ForegroundColor $(if ($p['status'] -eq "completed") { "Green" } else { "Yellow" })
        Write-Host "  当前阶段: $($p['stage'])" -ForegroundColor Gray
        Write-Host "  阶段进度:" -ForegroundColor Gray
        foreach ($key in @("build", "test", "deploy")) {
            $s = $p["stages"][$key]
            $icon = if ($s["status"] -eq "completed") { "[OK]" } elseif ($s["status"] -eq "running") { "[>>]" } else { "[  ]" }
            Write-Host "    $icon $key : $($s['status'])"
        }
    }

    "log" {
        if (-not $PipelineId) {
            Write-Error "log 需要 -PipelineId"
            exit 1
        }
        if (-not $Stage) {
            Write-Error "log 需要 -Stage (build|test|deploy)"
            exit 1
        }
        $state = Load-State
        if (-not $state[$PipelineId]) {
            Write-Error "流水线不存在: $PipelineId"
            exit 1
        }
        $log = $state[$PipelineId]["stages"][$Stage]["log"]
        if (-not $log) {
            Write-Host "(此阶段尚无日志)" -ForegroundColor Yellow
        } else {
            Write-Host $log
        }
    }

    "approve" {
        if (-not $PipelineId) {
            Write-Error "approve 需要 -PipelineId"
            exit 1
        }
        $state = Load-State
        if (-not $state[$PipelineId]) {
            Write-Error "流水线不存在: $PipelineId"
            exit 1
        }
        $state[$PipelineId]["approved"] = $true
        $state[$PipelineId]["stages"]["deploy"]["status"] = "running"
        $state[$PipelineId]["stages"]["deploy"]["log"] = (Simulate-DeployLog)
        Save-State $state

        Start-Sleep -Seconds 1
        $state = Load-State
        $state[$PipelineId]["stages"]["deploy"]["status"] = "completed"
        $state[$PipelineId]["status"] = "completed"
        $state[$PipelineId]["stage"] = "done"
        Save-State $state

        Write-Host "部署已审批通过并执行完成: $PipelineId" -ForegroundColor Green
    }

    "rollback" {
        if (-not $Repo) {
            Write-Error "rollback 需要 -Repo"
            exit 1
        }
        $targetVersion = if ($Version) { $Version } else { "上一个稳定版本" }
        Write-Host "回滚触发: $Repo -> $targetVersion" -ForegroundColor Yellow
        Write-Host "[ROLLBACK] 停止当前部署..." -ForegroundColor Gray
        Write-Host "[ROLLBACK] 切换到 $targetVersion ..." -ForegroundColor Gray
        Write-Host "[ROLLBACK] 健康检查: OK" -ForegroundColor Gray
        Write-Host "[ROLLBACK] 回滚完成，环境已恢复" -ForegroundColor Green
    }
}