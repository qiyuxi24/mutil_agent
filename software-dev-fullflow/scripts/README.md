# scripts/ — AgentTeams 部署脚本（定制版）

本目录包含修复 AgentTeams Windows 安装 bug 后的一键脚本。

## 🚀 统一入口（最常用，点击即用）

> 项目只有**两个交互入口**，根目录双击即可：

| 入口 | 启动方式 | 说明 |
|------|---------|------|
| **命令行** | 双击 `启动-命令行.bat` 或 `start.bat` 选 1 | 官方 `agt CLI` + Matrix 任务派发 |
| **Web 端** | 双击 `启动-Web端.bat` 或 `start.bat` 选 2 | 官方 AgentTeams Dashboard（自动开浏览器） |

- `scripts/entry-cli.ps1`：命令行入口（`status`/`workers`/`teams`/`submit <任务>`/`apply`）。
- `scripts/entry-web.ps1`：Web 入口（启动官方 Dashboard + 打开浏览器，`-Stop` 可停止）。
- 命令行入口 `submit` 通过 **Matrix 给 @manager 发消息**派单（官方方式），比旧的 `dispatch-task.ps1`（硬编码房间 ID）更通用，已归档到 `archive/`。

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
| `deploy-dashboard.ps1` | **增量部署 AgentTeams Dashboard**（可视化面板，无需重装；`-Remove` 可停止） |

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
| AgentTeams Dashboard（可视化） | http://127.0.0.1:13000 | admin / AgentTeams2026! |

## AgentTeams Dashboard（可视化面板，v1.2.0 新增）

可视化管理 Worker / Team / Human / Manager / Matrix，评审演示更直观。
官方部署逻辑只在 bash 版 `agentteams-install.sh` 的 `_start_dashboard()`，Windows 补丁版安装脚本不含。
本项目用 `deploy-dashboard.ps1` **按官方契约增量部署**（纯 docker 命令，无需重装 AgentTeams）。

**部署**：
```powershell
powershell -ExecutionPolicy Bypass -File deploy-dashboard.ps1
```
- 自动从 `agentteams-controller` 读取 MinIO/LLM/Admin/CLI-token 环境变量
- 镜像源与项目其他组件一致（阿里云 `higress-registry.cn-hangzhou.cr.aliyuncs.com/agentteams/agentteams-dashboard:latest`）
- 端口 `127.0.0.1:13000 -> 3000`，网络 `agentteams-net`，数据卷 `agentteams-dashboard-data`

**停止/移除**：
```powershell
powershell -ExecutionPolicy Bypass -File deploy-dashboard.ps1 -Remove
```

**验证**：
```powershell
docker ps   # agentteams-dashboard 应 Up，13000->3000
# 浏览器打开 http://127.0.0.1:13000，admin / AgentTeams2026!
```

**状态验证**：
```powershell
docker ps                    # agentteams-controller + agentteams-manager 应 Up
docker exec agentteams-controller agt get managers default
# → Phase: Running, Model: deepseek-v4-flash, Runtime: copaw, WelcomeSent: true
```
