# 操作手册 · 软件研发全流程协同 Agent 团队

> GOAI 世界人工智能开源大赛 · 赛道三「软件研发全流程协同」
> 本文档教你**怎么启动、怎么交互、怎么看结果**。项目只有**两个入口**：命令行 + Web 端，全部**点击即用**。
> 配套：架构总览见 `README.md`；还剩什么见 `TODO.md`。

---

## 0. 两个入口速览

| 入口 | 启动方式（双击） | 干什么 |
|------|----------------|--------|
| **① 命令行** | `启动-命令行.bat` | 官方 `agt CLI` 管理 Worker/Team + Matrix 派单 |
| **② Web 端** | `启动-Web端.bat` | 官方 AgentTeams Dashboard 可视化（自动开浏览器） |

也可以双击根目录 **`start.bat`** 弹出菜单选择。

---

## 1. 快速上手（双击即用）

1. 确保 **Docker Desktop 已启动**、AgentTeams 平台已部署（controller 等容器 Up）。
2. **双击 `启动-Web端.bat`** → 自动打开浏览器 `http://127.0.0.1:13000`，登录 `admin / AgentTeams2026!`。
3. **双击 `启动-命令行.bat`** → 进入命令行交互 Shell：
   ```
   agt> status      # 查看平台 / Worker / Team 状态
   agt> submit 修复登录接口空用户名500
   agt> q           # 退出
   ```

> **没有真实平台？** 需先部署：`scripts\reinstall-agentteams.ps1`（需 DeepSeek key）。
> 平台未运行时入口会提示"平台未运行"并给出指引，不会崩溃。

---

## 2. 命令行入口（①）

进入后是一个交互 Shell，提示符 `agt>`，支持：

| 命令 | 别名 | 作用 |
|------|------|------|
| `status` | — | 平台状态 + 7 Worker + Team 一览 |
| `workers` | `w` | 查看 Worker 表（名称/阶段/模型/团队/运行时） |
| `teams` | `t` | 查看 Team（Leader / 成员 / 就绪度） |
| `submit <任务>` | `run`/`task` | 通过 Matrix 给 Manager 派一个 PDCA 任务 |
| `apply` | — | 应用 `src/agentteams/workers.yaml`（批量管理 Worker） |
| `help` | `h` | 显示帮助 |
| `q` | `quit`/`exit` | 退出 |

也可以**带参一次执行**（不进交互）：
```powershell
powershell -ExecutionPolicy Bypass -File scripts\entry-cli.ps1 status
powershell -ExecutionPolicy Bypass -File scripts\entry-cli.ps1 submit "修复登录接口空用户名500"
```

**提交任务**：`submit` 通过 Matrix 给 @manager 发消息（官方派单方式），Manager 调度 6 个研发 Worker 接力完成 PDCA 闭环。

---

## 3. Web 端入口（②）

启动后浏览器打开 **`http://127.0.0.1:13000`**，登录 `admin / AgentTeams2026!`。

- 可视化查看 Worker / Team / Human / Manager / Matrix。
- 支持启停 Worker、查看状态，评审演示更直观。
- 停止：`powershell -ExecutionPolicy Bypass -File scripts\entry-web.ps1 -Stop`

---

## 4. 底层产物（怎么看结果）

所有运行产物写入 `src/data/`（已 gitignore）：

```
src/data/shared/
├── tasks/<task_id>/          ← 每个任务 8 个阶段产物 md
│   ├── state.json
│   ├── spec_input.md ... retrospect.md
├── agents/<name>/scorecard.json  ← 6 份绩效成绩单
└── audit/audit.jsonl             ← 结构化审计日志
```

闭环后命令行入口 / Python 客户端会打印**团队评价报告**（合格分/贡献分/评级）+ **治理命令**（retain/coach/fire→hire，即"招人/裁员"叙事卖点）。

---

## 5. 测试 / 自检

```powershell
cd software-dev-fullflow
demo\.venv\Scripts\python.exe -m pytest tests/ -q
# 期望: 156 passed, 12 skipped（Playwright 浏览器未装则 12 skipped）
```

> **必须用 `demo\.venv`**：系统 Python 缺 `pytest-asyncio`，会收集失败。

---

## 6. 常见问题（FAQ）

| 现象 | 原因 / 处理 |
|------|------------|
| 双击 bat 报"平台未运行" | Docker Desktop 未启动或平台未部署。先启动 Docker，再 `reinstall-agentteams.ps1` |
| Dashboard 打不开 13000 | 确认 `agentteams-dashboard` 容器 Up；`entry-web.ps1 -NoBrowser` 查看报错 |
| `submit` 派单失败 | 确认平台在线 + `AGENTTEAMS_ADMIN_PASSWORD`（脚本会自动从 controller 读取） |
| 系统 `python -m pytest` 报 `'asyncio' not found` | 用 `demo\.venv\Scripts\python.exe` |
| 12 个浏览器测试跳过 | 未装 Playwright，可选 `demo\.venv\Scripts\python.exe -m playwright install chromium` |

---

## 7. 一键速查（Cheat Sheet）

```powershell
# 两个入口（双击即用）
启动-命令行.bat    # 或 start.bat → 1
启动-Web端.bat     # 或 start.bat → 2

# 命令行入口常用（带参执行）
powershell -ExecutionPolicy Bypass -File scripts\entry-cli.ps1 status
powershell -ExecutionPolicy Bypass -File scripts\entry-cli.ps1 submit "任务描述"

# Web 入口
powershell -ExecutionPolicy Bypass -File scripts\entry-web.ps1        # 启动 + 开浏览器
powershell -ExecutionPolicy Bypass -File scripts\entry-web.ps1 -Stop  # 停止

# 测试
demo\.venv\Scripts\python.exe -m pytest tests/ -q   # 156 passed
```

---

> 操作手册如有出入，以 `scripts/entry-cli.ps1`、`scripts/entry-web.ps1` 与 `README.md` 为准。
