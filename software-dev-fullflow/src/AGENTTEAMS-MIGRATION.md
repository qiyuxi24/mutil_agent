# AgentTeams 迁移蓝图：现状梳理 + 迁移路径

> 目的：梳理「已实现的东西」vs「AgentTeams 平台真实能力」，给出从 `src/loop`（MAF 参考实现）
> 迁移到 **AgentTeams（比赛官方协同基点）** 的完整路径。
> 日期：2026-08-13
> 
> **2026-08-14 更新**：已完成问题1修复 —— `agentteams_loop.py` 已从"调度引擎"降级为"Python 客户端"。
> 删除了 `_run_orchestrated()` 模式（手动 Worker 调度、验证闸门、阶段控制），
> 现在只保留 `_run_delegated()`（委托 AgentTeams Manager）和 `_run_mock()`（本地演示）。
> 详见 [问题分析报告](#) 和 `agentteams_loop.py` 文件头注释。

---

## 一、现状：我们实际实现了什么

### 1.1 已实现（可复用）

| 模块 | 位置 | 内容 | 可迁移性 |
|------|------|------|---------|
| **PDCA 状态机** | `src/loop/state.py` | 8 状态 + 6 里程碑 + 打回逻辑，确定性状态图 | ✅ 核心逻辑可复用（作为 Team/Worker 的协作协议） |
| **6 个研发 Agent 定义** | `src/loop/team.py` | aggregator/rootcause/fixer/tester/releaser/retrospector 的 soul + guidelines | ✅ **直接迁移**成 AgentTeams Worker 的 `soul` + `agents` 字段 |
| **Manager 调度循环** | `src/loop/manager.py` | 派单→验证→推进/打回（MAF 底座） | ⚠️ 概念可映射到 AgentTeams（Manager/Team Leader 委派），但机制不同，需重写为 AgentTeams 方式 |
| **Skill 工程体系** | `skills/` | 7 个核心 Skill（9 字段）+ 注册表 + 分配矩阵 | ✅ 挂载到 AgentTeams Worker（`push-worker-skills.sh`） |
| **可运行 demo** | `demo/` + `src/run.py` | MAF 端到端跑通 + mock 秒级演示 | ⚠️ MAF 底座，演示用；AgentTeams 上需重新跑 |

### 1.2 AgentTeams 平台当前实际状态（已探测）

```
agt get managers → default / Running / deepseek-v4-flash / copaw   ✅ Manager 已就绪
agt get workers  → No workers found                                ⚠️ 0 个研发 Worker
agt get teams    → No teams found                                  ⚠️ 0 个团队
skills           → 通过 Worker spec.skills 挂载（非独立资源）
```

**结论**：AgentTeams 平台**只部署了空壳**（Manager default 在跑），**还没有任何研发 Worker / Team / Skill**。

---

## 二、关键差异：src/loop vs AgentTeams

| 维度 | `src/loop`（MAF 参考实现） | AgentTeams（官方） |
|------|---------------------------|-------------------|
| Agent 形态 | Python 对象（`AgentRole` dataclass） | 声明式 **Worker CR**（YAML，soul/agents/skills 字段） |
| 协同机制 | 代码循环（`TeamManagerLoop.run()`） | **Matrix 房间 + @mention 委派**（Manager→Leader→Worker） |
| 调度者 | Manager 代码循环 | AgentTeams **Manager Agent**（LLM 驱动，自动匹配 Team） |
| 状态机 | `state.py` 确定性状态图 | 靠 Worker/Team 的协作上下文 + HEARTBEAT |
| 里程碑 | 代码 `advance()` | Matrix 房间 @mention 里程碑词 |
| Skill | 纯提示词注入（前端 demo） | **Manager 集中管理**，`push-worker-skills.sh` 分发 |

---

## 三、迁移路径（官方方式）

### 第 1 步：生成 6 个研发 Worker 的 SOUL.md / AGENTS.md

把 `src/loop/team.py` 的每个 `AgentRole` 转成 AgentTeams Worker：

- `soul` → `spec.soul`（SOUL.md）
- `guidelines` → `spec.agents`（AGENTS.md）
- `expected_milestone` / `handoff_to` → 写入 `agents` 里的交接协议（@mention 下一个 Worker）

用 `agt create worker --name X --soul-file ... --skills ...` 逐个创建。

### 第 2 步：挂载 Skill

把 `skills/` 的 7 个核心 Skill 用官方 `push-worker-skills.sh` 推送到各 Worker 的 MinIO 空间，
并在 `spec.skills` 声明。参照 `skills/ASSIGNMENT-MATRIX.md` 的分配。

### 第 3 步：组建 Team（PDCA 闭环团队）

用 `agt create team` 建一个研发团队：
- Leader：用 Manager 的 team-leader-agent 模板（自动获得 team-coordination / task-management skills）
- 成员：6 个研发 Worker（或精简为核心 4 角色：aggregator/fixer/tester/releaser）

### 第 4 步：跑通闭环 Demo

- 在 Element Web 给 Manager 发任务 → Manager 自动匹配 Team → Leader 拆解 → Worker 接力
- 里程碑词在 Matrix 房间流转（对齐 `state.py` 的 6 里程碑协议）

---

## 四、差距与待补

| 项 | 状态 | 待做 |
|----|------|------|
| 6 个研发 Worker | ⚠️ 未创建 | 生成 SOUL.md + `agt create worker` |
| Team | ⚠️ 未创建 | `agt create team` 组建研发团队 |
| Skill 挂载 | ⚠️ 已编排未挂载 | `push-worker-skills.sh` 推送 + spec.skills |
| PDCA 闭环在 AgentTeams 跑通 | ❌ 未验证 | 端到端跑一个缺陷→发布→复盘 |
| 可观测（Trace/Metrics） | ⚠️ 设计中 | AgentTeams 用 Matrix 房间留痕 + 状态文件 |
| RAG 记忆 | ⚠️ 设计中 | AgentTeams 用 MinIO shared/knowledge + MEMORY.md |

---

## 五、迁移进度（2026-08-13 更新）

### ✅ 已完成：6 个研发 Worker 创建成功

- `src/agentteams/workers/<name>/SOUL.md` × 6
- `src/agentteams/workers.yaml`（6 Worker CRD 声明）
- 全部 6 个 Worker 进入 **Running**（deepseek-v4-flash / copaw），容器 `agentteams-worker-*` 全部 Up
- 验证：`agt get workers` → 6 个 Running

### ⏳ 进行中：Team 结构与闭环验证

**关键决策**：AgentTeams 的独立 Worker 可直接被 Manager 派单（groupAllowFrom 含 Manager）。
我们的 PDCA 闭环是**流水线接力**（aggregator→rootcause→fixer→tester→releaser→retrospector），
**不需要强行组建 Team**——Manager 可直接驱动 6 个独立 Worker 接力。

待办：
1. 验证 Manager 能否给 Worker 派单（Element Web 发任务 → Manager → Worker）
2. 视评审需要补建 Team（用 team-leader-agent 模板）

---

## 六、结论

- **已实现的核心资产**：PDCA 状态机设计 + 6 个 Agent 定义 + Skill 体系 —— **都可迁移**。
- **AgentTeams 平台就绪**（Manager default 在跑），**6 个研发 Worker 已全部创建并 Running**。
- **下一步最关键**：验证 Manager 驱动 6 个 Worker 跑通 PDCA 闭环（Element Web 发任务）。

---

## 七、Loop 迁移结论（2026-08-14 更新，回答「自己写的 loop 和官方无关？」）

### 结论：部分有关、部分无关。真正无关的是 MAF 底座，已摘除；已 AgentTeams 原生的保留。

把 `src/loop/` 逐文件对官方 AgentTeams（`references/refs/agent-teams/copaw` + `manager`）核对后：

| 文件 | 底座 | 与官方关系 | 处置 |
|------|------|-----------|------|
| `agentteams_loop.py` | **AgentTeams 原生**（`agt` CLI 驱动真实 Worker） | ✅ 正确方向 | **保留（参赛主路径）** |
| `agentteams_client.py` | AgentTeams（封装 `agt CLI`） | ✅ 原生 | 保留 |
| `state.py` | 框架无关（确定性状态机） | ✅ 官方没有，是我们的差异点 | 保留 |
| `context.py` | 框架无关（上下文工程） | ✅ 官方没有，是增量价值 | 保留 |
| `evaluation.py` | 框架无关（成员评价） | ✅ 官方没有，差异化卖点 | 保留 |
| `team.py` | 框架无关（角色定义） | ✅ 已映射到 `workers.yaml` | 保留 |
| `manager.py` | **MAF（微软，非官方）** | ❌ **无关** | **已归档**（摘除参赛路径） |
| `fixer_loop.py` | **MAF（微软，非官方）** | ❌ **无关** | **已归档**（Ralph 由 copaw 内建） |

### 关键事实

1. **真正无关的是 MAF 底座**：`manager.py`（TeamManagerLoop）+ `fixer_loop.py`（FixerLoop）都 `from agent_framework import Agent`（微软框架，用户已禁止）。这俩是"自己写了一套调度"，确实和阿里官方没关系。
2. **`agentteams_loop.py` 其实已经是原生的**：它不 import MAF，delegated 模式委托给官方 Manager，orchestrated 模式用 `agt send` 驱动真实 Worker。**它不是"另起炉灶"，而是"包了一层确定性调度"**——这正是我们的价值（官方 Manager 是 LLM 驱动的、没有硬编码状态机+验证闸门）。
3. **真正该迁移的是「确定性反压」层**：已把 `verify_test_gate.py` / `check-patch-integrity.py` 接入 `AgentTeamsLoop._verify_via_agentteams`，让 tester/releaser 阶段先用**确定性脚本**当裁判（Ralph 反压），脚本不可用时再交 AgentTeams 裁判 Worker 兜底。

### 本次代码变更（2026-08-14）

- **`src/run.py`**：入口从 MAF 的 `TeamManagerLoop` 切换到 AgentTeams 原生 `AgentTeamsLoop`（默认 delegated，支持 `--mode orchestrated` / `--mock`）。**这是"脱钩"的关键**——现在能跑起来的 demo 是官方框架的。
- **`src/loop/__init__.py`**：移除 MAF 模块导出，`__all__` 只保留 AgentTeams 原生 + 框架无关模块。
- **`src/loop/agentteams_loop.py`**：`_verify_via_agentteams` 新增 `_run_deterministic_gate`，确定性脚本当裁判（FIX_APPLY→补丁完整性、TEST_VERIFY→测试闸门）。
- **`src/loop/manager.py` / `fixer_loop.py`**：顶部加「已归档」横幅，保留作参考，不再参与参赛主路径。

### 参赛路径（现在）
```
run.py → AgentTeamsLoop
   ├─ delegated（默认）：AgentTeams Manager 驱动 6 Worker 接力（Matrix 留痕）
   └─ orchestrated：Python 控制流水线 + 确定性验证闸门（差异点）
          每个阶段 → Matrix 给真实 Worker → 确定性脚本/裁判 Worker 判定 → state.py 推进
```

---

## 八、关键发现：`agt` CLI 没有 task/send/messages，必须走 Matrix（2026-08-14 实测）

> 这是"完整迁移后事实能不能正常跑"的核心卡点。实测官方 `agt` CLI 后确认：

### 真实 `agt` 命令集（docker exec agentteams-controller agt --help）
```
apply / create(human|manager|team|worker) / delete / get(humans|managers|teams|workers)
update / status / worker(ensure-ready|report-ready|sleep|status|wake)
llm-preflight / rotate / completion / version
```
**没有** `task` / `send` / `messages` / `skills` / `knowledge` 子命令。

### 我们之前写的（编造的命令，跑不通）
- `agentteams_client.py` 假设 `agt task create`、`agt send`、`agt messages list` → **全不存在**
- `agentteams_loop.py` 的 orchestrated 用 `agt send --worker ...` → **全不存在**

### 官方真实交互：Matrix 协议（replay-task.sh）
官方 `scripts/replay-task.sh` + `tests/lib/matrix-client.sh` 证明：向 Manager/Worker 发任务、查回复，全部走 Matrix：
- `POST /_matrix/client/v3/login`（admin 登录拿 token）
- `POST /_matrix/client/v3/createRoom`（建 DM 房间）
- `PUT /rooms/{id}/send/m.room.message/{txn}`（发消息）
- `GET /rooms/{id}/messages`（查消息）
- 找与 @manager 的 DM 房间 → 发任务 → 轮询 Manager 回复

### 已完成的 Matrix 迁移（本次）
- **`agentteams_client.py`**：新增 `matrix_login` / `ensure_manager_room` / `send_matrix_message` / `read_room_messages` / `find_worker_room` / `ensure_worker_room` / `read_worker_reply`；`create_task` 改走 Matrix 发 DM；`detect_milestones`/`wait_for_task` 改跨所有房间扫描（排除 admin 自发的任务指令消息）。
- **`agentteams_loop.py`**：`_dispatch_to_worker` / `_verify_via_agentteams` 改走 Matrix 派单给真实 Worker；`manager` 参数默认 `manager`（Matrix 用户），不是 `default`。
- 保留真实存在的 `agt get workers` / `create worker` 等调用。

### 环境变量（连接 Matrix）
```
AGENTTEAMS_MATRIX_URL        (默认 http://127.0.0.1:18080)
AGENTTEAMS_MATRIX_DOMAIN     (默认 matrix-local.agentteams.io:18080)
AGENTTEAMS_ADMIN_USER        (默认 admin)
AGENTTEAMS_ADMIN_PASSWORD    (必填，本项目 AgentTeams2026!)
AGENTTEAMS_MANAGER_USER      (默认 manager)
```

### 实测验证（连真实平台）
1. `ping: True`（agt get managers 通）
2. Matrix login 成功（token 32 位）
3. `ensure_manager_room` 找到/创建与 @manager 的 DM
4. `create_task` 把 PDCA 任务发到 manager DM 房间 ✓
5. **官方 Manager 收到并理解任务**：回复"set up the multi-worker pipeline... All six workers exist and are running"
6. Manager 建 6 个三方房间（admin+manager+worker）、注册 6 个 task、写 state.json、同步 MinIO
7. **里程碑出现 `TASK_SPEC_READY <- @manager`**（第一个阶段完成）

> 完整 6 Worker 闭环是长流程（deepseek-v4-flash 每次调用 2-4 分钟，全流程约 20-30 分钟）。
> 后台 `run.py --mode delegated` 会持续轮询直到 `RETROSPECT_DONE` 或超时。

### ✅ 完整闭环实测通过（2026-08-14，里程碑全部出现）

监控脚本（只读现有房间，不重复发任务）捕捉到**完整 PDCA 闭环闭合**：

| 时间(s) | 里程碑 | Worker | 环节 |
|--------|--------|--------|------|
| 0 | TASK_SPEC_READY | aggregator | P 计划 |
| 0 | ROOT_CAUSE_FOUND | rootcause | D 执行 |
| 0-45 | FIX_APPLIED | fixer | D 执行（10/10 测试通过） |
| 0-45 | TEST_PASSED | tester | C 检查 |
| 60 | **RELEASE_OK** | releaser | A 处置（发布确认） |
| 136 | RELEASE_OK | retrospector | A 处置 |
| 181 | **RETROSPECT_DONE** | retrospector | A 处置（复盘，闭环闭合） |

**结论：`run.py --mode delegated` 委托给官方 AgentTeams Manager，驱动 6 Worker 接力，完整 PDCA 闭环真实跑通。**

修复工程师真实产出（Manager 汇报）：
- 三层修复：入口参数校验治本 + 下游空值防护 + 全局异常映射
- 修复后空用户名→400（不再 500）；**自动化测试 10/10 通过**
- 交付 login_fix.py / test_login_fix.py / plan.md / result.md 到 MinIO

> 已知：`run.py` 的 `wait_for_task` 默认 `TASK_TIMEOUT=600`（10 分钟），若闭环超过 10 分钟会超时返回（但 Manager 仍在后台推进，可再跑一次监控捕获）。`detect_milestones` 打印处有 `@@` 双 at 的显示小瑕疵（worker 已带 @，打印又加 @），不影响功能。

> 参考：AgentTeams 声明式资源管理 → `references/refs/agent-teams/docs/zh-cn/declarative-resource-management.md`

---

## 九、最小验证通过：真实平台跑得怎么样（2026-08-14，决定"以后就用 AgentTeams"）

### 验证方法：`scripts/verify-agentteams-min.py`（最小链路，可复用）

只验证「平台连通 → Manager 收到任务并开始推进」，不做完整闭环（deepseek-v4-flash 单次 2-4 分钟，全流程 20-30 分钟）：
1. `agt get managers` → exit=0，Manager default Running
2. Matrix 登录成功（admin / AgentTeams2026!）
3. 动态找到 Manager DM 房间 `!rWJbhh3Nl2NtRQWNrc:matrix-local.agentteams.io:18080`
4. 向房间发 PDCA 任务
5. 短轮询观察 Manager 响应

### 实测结果（10 秒内 Manager 响应，且房间已有完整闭环留痕）

| 检查项 | 结果 |
|--------|------|
| 平台 8 容器（controller/manager/6 worker） | ✅ 全部 Up |
| `agt get managers` | ✅ default / Running / deepseek-v4-flash / copaw |
| `agt get workers` | ✅ 6 个全部 Running |
| Matrix 登录 + Manager DM | ✅ 成功 |
| Manager 收到任务并响应 | ✅ 10s 内响应 |
| **房间留痕（真实平台已跑过的闭环）** | ✅ **TASK_SPEC_READY → ROOT_CAUSE_FOUND → FIX_APPLIED → TEST_PASSED(39用例) → RELEASE_OK(18项) → RETROSPECT_DONE** |
| 完整闭环证据 | ✅ 主链 Chain C（proj-20260814-081950）「登录接口空用户名500」**六阶段全部完成，PDCA 闭环成功关闭**；Chain B 亦接近闭环 |

### 决定性结论
> **真实 AgentTeams 平台驱动 6 Worker 接力，完整 PDCA 闭环确已跑通并留痕。**
> 之前记录的「完整闭环实测通过」在平台房间里有实证（Manager 汇报了 6 阶段全完成的总结）。
> **决策：以后统一用阿里官方 AgentTeams 框架作为协同基点**，不再引入第三方编排。

### 运行方式（宿主）
```
cd software-dev-fullflow\scripts
..\demo\.venv\Scripts\python.exe verify-agentteams-min.py
$env:VERIFY_WAIT_SECS=300   # 可加长等待窗口（可选）
```
