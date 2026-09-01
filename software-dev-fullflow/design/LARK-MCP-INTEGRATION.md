# 飞书 MCP 接入设计

> 状态：✅ 可执行（2026-08-31 落地胶水层）
> 方案：宿主机自托管 `lark-mcp`（官方 `@larksuiteoapi/lark-mcp`，SSE 模式）→ Higress 网关代理 → 团队 Worker 统一使用

## 1. 背景与价值

把「飞书」接进团队后，Worker 可以直接操作飞书，形成「研发团队 + 协作办公」闭环：

| 能力 | 典型用法 | 适用 Worker |
| --- | --- | --- |
| 消息/群组（im） | 向用户/团队群发需求确认、进度播报、发布通知 | Leader / Aggregator / Releaser |
| 云文档（docx） | 读取需求文档、导出设计文档、沉淀团队 Wiki | Leader / Aggregator / RootCause |
| 多维表格（bitable） | 需求池、缺陷跟踪表、验收清单读改写 | Aggregator / Tester |
| 任务（task） | 派发/更新任务，同步 PDCA 里程碑 | Leader |
| 日历（calendar） | 查忙闲、建会议、安排站会 | Leader |
| 云盘/知识库（wiki/drive） | 检索团队知识库做方案依据 | RootCause |

## 2. 架构

```
┌────────────────────────── 宿主机 (Windows) ──────────────────────────┐
│  npx @larksuiteoapi/lark-mcp mcp  -m sse --host 0.0.0.0 -p 8300      │
│   (SSE 端点 http://127.0.0.1:8300/sse，App ID/Secret 以参数注入)      │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ http://host.docker.internal:8300/sse
┌────────────────────────────────▼─────────────────────────────────────┐
│ Docker: agentteams-controller（Higress 网关，容器内网)                │
│  feishu server  →  proxy 到 host.docker.internal:8300/sse            │
│  对外: http://aigw-local.agentteams.io:8080/mcp-servers/feishu/mcp   │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ mcporter（HTTP transport）
┌────────────────────────────────▼─────────────────────────────────────┐
│ Docker: 9 Workers（leader/aggregator/rootcause/...）                  │
│  mcpServers: feishu → 工具统一注入 LLM（飞书工具名 feishu_*）          │
└──────────────────────────────────────────────────────────────────────┘
```

**为什么选「宿主机自托管 SSE」而非其他路径**（对比见 §5）：
- 官方 `@larksuiteoapi/lark-mcp` 是标准 npm 包、与飞书开放平台 API 同步，信任度高；
- `-m sse` 原生输出 HTTP 端点，正好落在 Higress `setup-mcp-proxy.sh` 支持的 `sse` 传输类型上，无需额外桥接；
- App ID/App Secret 只存在宿主机进程参数中，不进镜像、不进代码仓库。

## 3. 前置准备（一次性，需要企业管理员/应用开发者）

1. 登录 [飞书开放平台](https://open.feishu.cn) → 「开发者后台」→ 创建 **企业自建应用**（如 `agent-team-mcp`）；
2. 记下 **App ID**（`cli_` 开头）与 **App Secret**（App 凭证页，可重置）；
3. 在「权限管理」按需开通，然后「版本管理与发布」→ 创建版本并发布（**必须发布，自建应用才生效**）。最小权限建议：
   - 发消息：`im:message`（+ 按需 `im:chat`）
   - 读写文档：`docx:document`（按需 `wiki:wiki`）
   - 多维表格：`bitable:app`（按需 `bitable:app:readonly`）
   - 任务：`task:task`
4. 应用「添加能力」/可用范围按需配置（谁可以用这个应用）。

> 权限开通对照：`lark-mcp` 各预设集所需 scope 见官方 README（preset.light 只需要最基本的 im/bitable/docx 子集）。

## 4. 接入步骤

### 4.1 一键接入（推荐）

```powershell
# 在 software-dev-fullflow 目录执行
.\scripts\add-feishu-mcp.ps1 -AppId "cli_xxx" -AppSecret "yyy"

# 按需调整：工具集预设 / 端口 / 通知的 Worker
.\scripts\add-feishu-mcp.ps1 -AppId "cli_xxx" -AppSecret "yyy" `
    -Preset preset.im.default -Workers "leader,aggregator,rootcause,releaser"
```

脚本自动完成：校验 Node ≥ 20 → 后台拉起 lark-mcp（SSE，PID 落 `data/feishu-mcp.pid`）→ 探活 `/sse` → `register-mcp.ps1 -Mode proxy` 注册 `feishu` 到 Higress → 同步相关 Worker。

### 4.2 挂载到 Worker

`src/agentteams/workers.yaml` 中 leader/aggregator/rootcause 已声明（见 §6），注册成功后同步：

```powershell
docker cp src\agentteams\workers.yaml agentteams-controller:/tmp/workers.yaml
docker exec agentteams-controller agt apply -f /tmp/workers.yaml
```

### 4.3 验证

```powershell
# Worker 侧能看到 feishu_* 工具
docker exec agentteams-worker-aggregator mcporter list feishu --schema
# 或走管理端查看 server 状态
agt get mcp
```

### 4.4 维护

```powershell
# 停止 lark-mcp
Stop-Process -Id (Get-Content data\feishu-mcp.pid)
# 日志
Get-Content logs\feishu-mcp.log -Tail 50
# 重新注册（改 preset / 端口后）
docker exec agentteams-controller agt update mcp feishu --url http://host.docker.internal:8300/sse --transport sse
```

## 5. 接入路径对比（选型依据）

| 路径 | 传输 | 优点 | 缺点 | 结论 |
| --- | --- | --- | --- | --- |
| **自托管 lark-mcp SSE（本方案）** | sse | 官方包、信任度高；SSE 直连 Higress 免桥接；凭据只在宿主机 | 需本机 Node ≥ 20；服务常驻 | ✅ 采用 |
| 飞书开放平台托管 MCP | http | 零运维、飞书托管 | 需企业管理员在开放平台开通 MCP 能力并配置；URL 与租户绑定 | 可作为备选 |
| 社区 docker（feishu-mcp 等） | streamable-http | 容器化 | 社区维护、安全性存疑 | 不采用 |
| 自建 REST API 包装 | http | 完全可控 | 需自己实现 tenant_access_token 动态获取与 API 封装，成本高 | 不采用 |

## 6. Worker 挂载规划

- **leader（编排者）**：发需求确认/进度播报/发布通知、建任务、安排会议 —— `feishu`（im/task/calendar）
- **aggregator（产品经理）**：读需求文档、维护多维表格需求池 —— `feishu`（docx/bitable）
- **rootcause（架构师）**：查知识库/Wiki 做方案依据 —— `feishu`（wiki/drive）
- 其余 Worker 暂不挂（避免 token 浪费）；后续可按需扩展。

> 若希望「一键把 feishu 挂给更多 Worker」，修改 `add-feishu-mcp.ps1` 的 `-Workers` 默认值，并同步 `workers.yaml`。

## 7. 安全注意事项

1. **凭据**：App Secret 只通过脚本参数/环境变量传入宿主机进程，不进代码仓库（`.gitignore` 已含 `data/`、`logs/`）。
2. **端口暴露**：lark-mcp 监听 `0.0.0.0` 是为了让 Docker 容器经 `host.docker.internal` 访问；该端口仅在局域网内可用，勿暴露公网（Windows 防火墙默认放行内网）。若需更强隔离，改为 `--host 127.0.0.1` + 容器走 `host-gateway` 反向代理。
3. **权限最小化**：只开通团队真正用到的 scope；Worker 侧只把 `feishu` 挂给需要的角色。
4. **审计**：Worker 调飞书工具会走 Higress access log；敏感操作（删文档/发消息）可结合团队审计日志追查。
5. **令牌机制**：`lark-mcp` 内部自动获取/刷新 `tenant_access_token`，无需手工管理。

## 8. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 探活失败：端口未监听 | npx 首次下载慢 / Node 版本低 | 查看 `logs/feishu-mcp.log(.err)`；`node -v` 确认 ≥20；重跑脚本 |
| `mcporter list feishu` 无工具 | Worker 未同步 / 注册未生效 | 重跑 register-mcp.ps1；`agt apply` 后等 30s 再查 |
| 调用返回 401/权限不足 | 应用未发布 / scope 未开通 / 可用范围未包含用户 | 开放平台「版本管理与发布」发布版本；补 scope；检查应用可用范围 |
| `/sse` 404 | lark-mcp 版本路径差异 | 升级包：`npx -y @larksuiteoapi/lark-mcp@latest ...`；或看日志确认实际路径 |
| 网关 503 | Higress 连不上宿主端口 | 确认 lark-mcp 进程存活；`--host 0.0.0.0` 未加则容器连不上 |
| 中文字段乱码 | 未传 `-l zh` | 重跑脚本（脚本默认已加 `-l zh`） |

## 9. 参考

- 官方包：`@larksuiteoapi/lark-mcp`（npm）
- 飞书开放平台 MCP 文档：`open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/mcp_integration/*`
- 本仓库复用：`scripts/register-mcp.ps1`（proxy 模式）、`src/agentteams/mcp/`（配置目录）、`setup-mcp-proxy.sh`（Higress 官方脚本）
