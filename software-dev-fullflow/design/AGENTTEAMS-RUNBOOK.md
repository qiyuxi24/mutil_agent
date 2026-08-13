# AgentTeams 落地运行手册（RUNBOOK）

> 目标：回答「怎么先让 AgentTeams 的 agent loop 跑起来」——给出**从零到跑通**的可执行操作步骤，
> 与已有机理文档互补（本文重"动手跑"，不重复"内部机制"）。
>
> - 机制详解见：`design/AGENTTEAMS-INTERNALS.md`
> - Manager Loop 设计见：`design/MANAGER-LOOP-DESIGN.md`
> - 运行时选型（OpenClaw vs QwenPaw/AgentScope）见：`design/OPENCLAW-VS-QWENPAW.md`
> - 官方源码/文档只读参考：`references/refs/agent-teams/`（v1.2.0）
> - 更新日期：2026-08-12

---

## 0. 最重要的一句话

> **AgentTeams 不是"pip 装个包就能写脚本跑"的框架，它是一套基于 Docker 的多 Agent 编排平台。**
> 你要让"agent loop 跑起来"，实际是：**装 Docker → 一键安装 AgentTeams → 登录 Element Web → 让 Manager 创建 Worker → 给 Worker 派任务**。
> Worker/Manager 的 agent loop 在容器里由运行时（OpenClaw / QwenPaw / Hermes）自动驱动，你无需手写 loop。

---

## 1. 架构速览（知道谁在跑 loop 就行）

```
浏览器 → Element Web (IM 客户端, 127.0.0.1:18088)
              │ Matrix
        agentteams-controller (Go)
        ├─ Higress AI 网关  ── 持有真实 API Key / MCP 凭证
        ├─ Tuwunel (Matrix) ── Agent + 人类通信房间
        ├─ MinIO            ── 共享文件系统（Worker 无状态）
        └─ Element Web 代理
              │
        agentteams-manager  (Manager Agent, 运行时 OpenClaw/QwenPaw)
              │ 创建 Worker / 派单
        agentteams-worker-alice / bob / ...  (OpenClaw / QwenPaw / Hermes)
```

- **agent loop 真正"干活"的地方** = 每个 Manager / Worker 容器里的 Agent 运行时。
- **你控制 loop 行为的方式** = 改 `soul`（人格）、`agents`（工作准则）、`skills`（技能）、`HEARTBEAT.md`（周期职责）——它们被注入工作区，Agent 每会话开头读它们。
- **你观察 loop 的方式** = Matrix 房间（人类全程可见可介入）+ Higress 控制台 + 容器日志。

---

## 2. 前置条件（先自查，缺一不可）

| 项 | 要求 | 怎么确认 |
|----|------|---------|
| 操作系统 | Windows 10/11（**不支持虚拟机里的 Windows**，必须 Linux Container） | — |
| WSL2 | 已启用（Docker Desktop 安装时会提示） | PowerShell: `wsl --status` |
| Docker Desktop | 4.20+，且已运行（左下角绿色） | PowerShell: `docker info` |
| PowerShell | 7.0+（Core，不是 5.1） | PowerShell: `$PSVersionTable.PSVersion` |
| 硬件 | 最低 2C4GB，建议 4C8GB，磁盘 ≥10GB | — |
| LLM API Key | 阿里百炼（推荐）或 OpenAI 兼容（DeepSeek 等） | 安装脚本会测联通 |

> **若本机没有 Docker Desktop / 未开 WSL2**：先装 Docker Desktop（会自动引导 WSL2），启动后再继续。这是硬门槛，没有 Docker 跑不了 AgentTeams。

---

## 3. 安装步骤（官方一键 + 命令行双路径）

### 3.1 方式 A：官方一键安装（交互式，推荐新手）

PowerShell 执行（临时放开脚本执行策略并下载运行）：

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force; $wc=New-Object Net.WebClient; $wc.Encoding=[Text.Encoding]::UTF8; iex $wc.DownloadString('https://raw.githubusercontent.com/agentscope-ai/AgentTeams/main/install/agentteams-install.ps1')
```

交互提示要点（对照 `docs/zh-cn/windows-deploy.md`）：
1. 语言 → 中文
2. 安装模式 → `1) 快速开始`（阿里百炼）或 `2) 手动配置`（DeepSeek 等 OpenAI 兼容，Base URL 含 `/v1`）
3. 大模型服务商 / 模型接口 / 模型系列 → 按需选
4. 输入 API Key → 自动测联通（失败先查 key 空格/是否开通 CodingPlan）
5. 网络模式 → `1) 仅本机`
6. 端口域名 → 全部回车用默认值
7. Worker 运行时 → **建议选 `2) QwenPaw`**（Python，~150MB，比 OpenClaw 轻，且与我们方案 B 一致）
8. 等待安装（首次拉取镜像数 GB，走杭州节点，耐心等）

**安装成功标志**：终端输出登录面板 + 浏览器可开 `http://127.0.0.1:18088`。

### 3.2 方式 B：Make 最简安装（已克隆仓库、非交互）

```powershell
# 只需 LLM Key，其余全部默认；会挂载 Docker socket 便于直接创建 Worker
$env:AGENTTEAMS_LLM_API_KEY = "sk-xxx"
make install
```

### 3.3 非交互自动化（CI / 复赛脚本用）

```powershell
$env:AGENTTEAMS_NON_INTERACTIVE = "1"
$env:AGENTTEAMS_LLM_API_KEY = "sk-xxx"
$env:AGENTTEAMS_LLM_PROVIDER = "openai-compat"   # 或 qwen
$env:AGENTTEAMS_DEFAULT_MODEL = "deepseek-v4-flash"  # 或 qwen3.5-plus
.\agentteams-install.ps1
```

---

## 4. 登录 + 创建第一个 Worker（让第一个 agent loop 跑起来）

### 4.1 登录 Element Web

1. 浏览器打开 `http://127.0.0.1:18088/#/login`
2. 用户名 `admin`，密码为安装时自动生成的随机串（查看方式）：
   ```powershell
   Select-String "AGENTTEAMS_ADMIN_PASSWORD" "$env:USERPROFILE\agentteams-manager.env"
   ```
3. 登录后看到与 `manager` 的私聊窗口。

### 4.2 让 Manager 创建 Worker（关键动作）

在 Element Web 给 `manager` 发消息：

```
帮我创建一个名为 alice 的 Worker，负责前端开发任务。runtime 用 qwenpaw。
```

Manager 会自动完成：注册 Matrix 账号 → 在 Higress 建 Consumer → 在 MinIO 建配置 → 建三方房间（你、manager、alice）→ 启动 Worker 容器。

**命令行验证 Worker 已创建**：
```powershell
docker ps | findstr agentteams-worker-alice
docker exec agentteams-controller agt get workers
```

### 4.3 派任务（触发 alice 的 agent loop）

进入 alice 的房间发：

```
alice，请为一个 hello-world 项目创建 README.md，包含项目名称、描述和使用说明。结果保存到共享任务文件夹。
```

**观察 loop 在跑**：房间内你会看到 alice 的进度更新，最终产出结果文件（`shared/tasks/{task-id}/result.md`）。

---

## 5. 命令行全流程（不想用 IM 打字时）

```powershell
# ① 创建 Worker（声明式 CLI，agt 在 controller 容器内）
docker exec agentteams-controller agt create worker --name alice --model qwen3.5-plus --runtime qwenpaw

# ② 列出 Worker
docker exec agentteams-controller agt get workers

# ③ 通过 Make 向 Manager 发任务（仓库根目录）
make replay TASK="请为 hello-world 创建 README，保存到共享任务文件夹"

# ④ 切换某 Worker 运行时
docker exec agentteams-controller agt update worker alice --runtime hermes
```

---

## 6. 最小 Demo 验证清单（跑通即达标）

- [ ] `docker ps | findstr agentteams-controller` 有输出
- [ ] `docker ps | findstr agentteams-manager` 有输出
- [ ] `http://127.0.0.1:18088` 能登录
- [ ] Manager 成功创建 `alice` Worker（房间出现 3 名成员）
- [ ] `docker ps | findstr agentteams-worker-alice` 有输出
- [ ] 给 alice 派任务后，房间内看到进度、结果文件出现在 `shared/tasks/`
- [ ] 结果 `meta.json` 状态更新为 `completed`

---

## 7. 常见故障排查（对应我们的历史教训）

| 现象 | 排查 |
|------|------|
| **安装卡在"等待 Manager Agent 就绪"** | ①WSL2 内存不足：编辑 `%USERPROFILE%\.wslconfig` 写 `[wsl2] memory=8GB` 后重启 Docker ②`docker logs agentteams-controller` ③`docker exec agentteams-manager cat /var/log/agentteams/manager-agent.log` |
| **API 联通性测试失败** | key 是否完整无空格；是否开通对应模型服务（如 CodingPlan）；`https://dashscope.aliyuncs.com` 是否可达 |
| **镜像拉取超时/卡住** | 安装脚本已按时区选杭州节点；可在 Docker Desktop→Settings→Docker Engine 配镜像加速 |
| **端口被占用（18088）** | `netstat -ano | findstr "18088"`；重装时手动配置换端口 |
| **PowerShell 执行闪退** | 先确认 `docker info` 可用再执行安装命令 |
| **⚠️ 版本错位 bug（我们的历史坑）** | 本仓库拉的是 v1.2.0，但 `main` 分支安装脚本可能默认装 latest 镜像。若 Manager/Worker 行为与文档不符，**显式指定版本**：`$env:AGENTTEAMS_VERSION="v1.1.2"`（或与本地源码匹配的 tag）再安装。此前已确认 v1.2.0 与 v1.1.2 安装器/存储契约存在差异，**务必让源码、镜像、安装器三者版本一致**。 |

---

## 8. 与参赛方案的衔接（跑起来之后做什么）

跑通 AgentTeams 平台只是"地基"。要把它变成参赛作品，核心工作在**零代码改造**（写 YAML + Markdown），详见 `design/AGENTTEAMS-INTERNALS.md` §7.1：

| 赛道需求 | 在 AgentTeams 里怎么落地 |
|---------|------------------------|
| 多 Agent 协同（25%） | 用 `Worker.spec.soul/agents` 定义 6 个研发 Agent + `Team` CRD 组织 + 里程碑握手 |
| Skill 工程（25%） | `spec.skills` + `manager/agent/skills/<name>/SKILL.md`（7 个工程 Skill 已设计） |
| PDCA 闭环状态机 | 用 `shared/tasks/{id}/spec→plan→result` + 各 Agent @mention 里程碑 |
| 动态团队（核心创新点） | `agt create/delete worker`（招人/裁员）+ 技能动态加载 |
| 审批与回滚 | Human 在 Matrix 房间全程可见介入 + `channelPolicy` |
| 共享状态 / RAG | `shared/knowledge/` + `memory/` |

> 方案 B（推荐）：**不在 OpenClaw 上重写**，用 **QwenPaw 运行时** + 基于 AgentScope 自写 Manager loop（见 `MANAGER-LOOP-DESIGN.md`）。安装时 Worker 运行时选 `qwenpaw` 即可对接到这条路线。

---

## 9. 下一步建议（时间紧，初赛 8.16 截止）

考虑到初赛只剩几天，且我们已在「跑通平台 + 写代码」之间权衡过：

- **若只为初赛材料**：AgentTeams 平台可作为方案 PPT 的"已具备可执行性"论据，不必强行本地部署完整平台；用 `design/` 现有文档 + demo（MAF/DeepSeek 已验证）支撑即可。
- **若要复赛提交可执行代码包（9.3）**：再按本手册本地部署 AgentTeams，并把第 8 节的设计转成 `src/` 下的 YAML 资源。届时优先用 QwenPaw 运行时 + 非交互安装，减少排障时间。

---

## 10. 关键参考

- 官方快速入门：`references/refs/agent-teams/docs/zh-cn/quickstart.md`
- Windows 部署：`references/refs/agent-teams/docs/zh-cn/windows-deploy.md`
- 架构/FAQ：`references/refs/agent-teams/docs/zh-cn/{architecture,faq}.md`
- 安装脚本：`references/refs/agent-teams/install/agentteams-install.ps1`
- QwenPaw Worker 运行时：`references/refs/agent-teams/qwenpaw/`
