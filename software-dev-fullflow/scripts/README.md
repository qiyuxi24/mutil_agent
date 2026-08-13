# scripts/ — AgentTeams 部署脚本（定制版）

本目录包含修复 AgentTeams Windows 安装 bug 后的一键脚本。

## 背景：为什么需要补丁

官方 `agentteams-install.ps1`（Windows 版）**漏掉了 Matrix AppService token**
（`AGENTTEAMS_MATRIX_APPSERVICE_AS_TOKEN` / `HS_TOKEN`）的生成与透传。
而 embedded controller 的 `config.go` 在 `MatrixAppServiceEnabled=true`（默认）时
强制要求这两个 token，否则 **启动即 panic**：

```
panic: AGENTTEAMS_MATRIX_APPSERVICE_AS_TOKEN is required when AppService mode is enabled
```

官方 `.sh`（Linux）版有正确逻辑，`.ps1` 缺失——这就是之前（2026-08-07）"版本错位 bug 无解"的真正根因。

## 文件

| 文件 | 说明 |
|------|------|
| `agentteams-install-patched.ps1` | 官方脚本 + 3 处补丁（token 生成 + 透传 + network 错误保护） |
| `reinstall-agentteams.ps1` | 自动化「清理 + 全新重装」包装脚本（非交互） |

## 补丁内容（相对官方脚本）

1. **token 生成**：`New-EnvFile` 前，若 `$env:AGENTTEAMS_MATRIX_APPSERVICE_AS_TOKEN` 为空
   则用 `[Guid]` 生成并持久化到 env 文件（对齐官方 `.sh` 的 `openssl rand -hex 32`）。
2. **token 透传**：controller `$ctrlArgs` 定义处补
   `-e AGENTTEAMS_MATRIX_APPSERVICE_ENABLED/AS_TOKEN/HS_TOKEN`。
3. **env 文件模板**：补 3 行 `AGENTTEAMS_MATRIX_APPSERVICE_*`，供升级路径加载。
4. **network 错误保护**：`docker network inspect` 处局部 `$ErrorActionPreference="Continue"`，
   避免被外层 `"Stop"` 提升为终止性错误。

## 全新重装步骤

```powershell
# 1. 设置 DeepSeek key（与 demo/.env 一致）
$env:DEEPSEEK_API_KEY='sk-你的key'

# 2. 运行自动化重装（清理残缺 env/数据卷 + 非交互全新安装）
powershell -ExecutionPolicy Bypass -File reinstall-agentteams.ps1
```

> 注意：全新安装必须删掉残缺 env + 数据卷（`reinstall-agentteams.ps1` 已处理）。
> 不要用升级模式 `AGENTTEAMS_UPGRADE_KEEP_ALL=1`——它会跳过 LLM/Admin 配置，
> 导致 controller 拿到空 `LLM_API_KEY` / `ADMIN_USER`。

## 部署成功后的访问

| 服务 | 地址 | 登录 |
|------|------|------|
| Element Web（人机对话） | http://127.0.0.1:18088 | admin / AgentTeams2026! |
| Higress 控制台 | http://127.0.0.1:18001 | admin / AgentTeams2026! |
| AI 网关 | http://127.0.0.1:18080 | — |

**状态验证**：
```powershell
docker ps                    # agentteams-controller + agentteams-manager 应 Up
docker exec agentteams-controller agt get managers default
# → Phase: Running, Model: deepseek-v4-flash, Runtime: copaw, WelcomeSent: true
```
