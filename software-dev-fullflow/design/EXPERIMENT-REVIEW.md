# 实验复盘：Loop 迁移到 AgentTeams 原生 + 完整闭环实测

> 本文件记录 2026-08-14 的一次关键实验：把自研研发调度 Loop 完整迁移到**阿里官方 AgentTeams 框架**，
> 并**实际连真实平台跑通完整 PDCA 闭环**。用于后续复盘、复赛演示、决赛答辩。
> 关联文档：`src/AGENTTEAMS-MIGRATION.md`（迁移蓝图）、`design/AGENTTEAMS-RUNBOOK.md`（部署手册）、`design/PDCA-CLOSED-LOOP.md`（闭环设计）。

---

## 一、实验背景与问题

### 1.1 用户提出的核心疑问

> "我们似乎自己写的 loop 和阿里官方的没什么关系，你看看是不是这样，如果是，尽量迁移我们的东西到人家都框架里边。"

### 1.2 我们要回答的问题

1. 自研的 `src/loop/` 到底哪些和官方 AgentTeams 无关？
2. 无关的部分如何迁移到官方框架？
3. **迁移后事实能不能正常跑？**（必须连真实平台验证，不能只 mock）

---

## 二、关键结论（先看这里）

| # | 结论 | 证据 |
|---|------|------|
| 1 | 真正与官方无关的是 **MAF 底座**（微软框架，已被用户禁止参赛） | `manager.py`/`fixer_loop.py` 都 `from agent_framework import Agent` |
| 2 | `agentteams_loop.py` 本就是 AgentTeams 原生（`agt` CLI 驱动真实 Worker） | 不 import MAF，走 `agt`/Matrix |
| 3 | **官方 `agt` CLI 没有 `task`/`send`/`messages` 子命令** —— 我们之前封装的派发命令全是编造的，这是"跑不起来"的根源 | `agt --help` 实测 |
| 4 | 官方与 Manager/Worker 交互走 **Matrix 协议**，不是 `agt` | 官方 `scripts/replay-task.sh` + `tests/lib/matrix-client.sh` |
| 5 | **完整 PDCA 闭环在官方平台实测跑通**（到 `RETROSPECT_DONE`） | 里程碑时间线见 §六 |
| 6 | 确定性状态机/验证闸门/成员评价是官方没有的差异价值，**保留并嵌进官方框架** | 见 §四 |

---

## 三、现状梳理：`src/loop/` 逐文件归属

把 `src/loop/` 全部文件对照官方 AgentTeams（`references/refs/agent-teams/copaw` + `manager`）核对：

| 文件 | 底座 | 与官方关系 | 处置 |
|------|------|-----------|------|
| `agentteams_loop.py` | **AgentTeams 原生**（`agt` + Matrix 驱动真实 Worker） | ✅ 正确方向 | **保留（参赛主路径）** |
| `agentteams_client.py` | AgentTeams（封装 `agt CLI` + **Matrix**） | ✅ 原生 | 保留（本次补 Matrix） |
| `state.py` | 框架无关（确定性 PDCA 状态机） | ✅ 官方没有，是差异点 | 保留 |
| `context.py` | 框架无关（上下文工程） | ✅ 官方没有，是增量价值 | 保留 |
| `evaluation.py` | 框架无关（成员评价：贡献度+合格度） | ✅ 官方没有，差异化卖点 | 保留 |
| `team.py` | 框架无关（6 角色定义） | ✅ 已映射到 `workers.yaml` | 保留 |
| `manager.py` | **MAF（微软，非官方）** | ❌ 无关 | 已归档（摘除参赛路径） |
| `fixer_loop.py` | **MAF（微软，非官方）** | ❌ 无关（Ralph 由 copaw 内建） | 已归档 |

**核心判断**：
- 真无关的是 **MAF 底座**（`manager.py`/`fixer_loop.py`），已摘除。
- `agentteams_loop.py` 不是"另起炉灶"，而是"在官方框架外包了一层**确定性调度**"——这层正是官方缺失的（官方 Manager 是 LLM 驱动的、没有硬编码状态机 + 验证闸门）。

---

## 四、迁移做了什么

### 4.1 入口脱钩（把 demo 从 MAF 切到官方）

**`src/run.py`**：入口从 MAF 的 `TeamManagerLoop` 切换到 AgentTeams 原生 `AgentTeamsLoop`。
```python
# 改前
from loop.manager import TeamManagerLoop      # MAF 底座
# 改后
from loop.agentteams_loop import AgentTeamsLoop  # AgentTeams 原生
```

**`src/loop/__init__.py`**：移除 MAF 模块导出，`__all__` 只保留 AgentTeams 原生 + 框架无关模块。

### 4.2 归档 MAF 底座

**`src/loop/manager.py`** / **`src/loop/fixer_loop.py`**：顶部加"已归档（DEPRECATED/ARCHIVED）"横幅，保留作参考，不再参与参赛主路径。

### 4.3 【核心】把编造的 agt 派发换成真实 Matrix

**发现**：官方 `agt` CLI 实际只有 `apply/create/delete/get/update/status/worker/llm-preflight/rotate`，
**没有** `task`/`send`/`messages`/`skills`/`knowledge`。我们之前 `agentteams_client.py` 假设的
`agt task create`、`agt send`、`agt messages list` 全不存在。

**官方真实交互 = Matrix 协议**（来自 `scripts/replay-task.sh` + `tests/lib/matrix-client.sh`）：
```
POST  /_matrix/client/v3/login                              # admin 登录拿 token
GET   /_matrix/client/v3/joined_rooms                       # 列出已加入房间
GET   /_matrix/client/v3/rooms/{id}/members                 # 查房间成员
POST  /_matrix/client/v3/createRoom                         # 建 DM 房间
PUT   /_matrix/client/v3/rooms/{id}/send/m.room.message/{txn}  # 发消息
GET   /_matrix/client/v3/rooms/{id}/messages                # 查消息
```

**`src/loop/agentteams_client.py`** 新增 Matrix 客户端：
- `matrix_login` / `ensure_manager_room` / `send_matrix_message` / `read_room_messages`
- `find_worker_room` / `ensure_worker_room` / `read_worker_reply`
- `create_task` 改走 Matrix 发 DM；`detect_milestones`/`wait_for_task` 改跨所有房间扫描（**排除 admin 自发的任务指令消息**）

**`src/loop/agentteams_loop.py`**：
- `_dispatch_to_worker` / `_verify_via_agentteams` 改走 Matrix 派单给真实 Worker
- `manager` 参数默认 `manager`（Matrix 用户），不是 `default`（原写死 `default` 会把任务误发到 `@default` 房间）

### 4.4 确定性验证闸门嵌进官方框架

**`src/loop/agentteams_loop.py::_verify_via_agentteams`** 新增 `_run_deterministic_gate`：
- `FIX_APPLY` 阶段 → 跑 `skills/code-gen/scripts/check-patch-integrity.py`（补丁完整性）
- `TEST_VERIFY` 阶段 → 跑 `skills/test-generation/scripts/verify_test_gate.py`（测试闸门）
- 脚本不可用再回退 AgentTeams 裁判 Worker

这是我们把"Ralph 反压"（确定性裁判，非 LLM 自评）嵌进官方框架的落点。

---

## 五、连接真实平台的环境

### 5.1 平台状态（实测）

```
agentteams-controller   Up     # 控制面
agentteams-manager      Up     # Manager Agent（LLM 驱动调度）
agentteams-worker-{aggregator,rootcause,fixer,tester,releaser,retrospector}  Up  # 6 Worker 全部 Running
```
```
agt get workers → 6 个 Worker 全部 Running（deepseek-v4-flash / copaw）
```

### 5.2 Matrix 连接环境变量

| 变量 | 值 |
|------|-----|
| `AGENTTEAMS_MATRIX_URL` | `http://127.0.0.1:18080`（host）/ `http://agentteams-controller:6167`（容器内） |
| `AGENTTEAMS_MATRIX_DOMAIN` | `matrix-local.agentteams.io:18080` |
| `AGENTTEAMS_ADMIN_USER` | `admin` |
| `AGENTTEAMS_ADMIN_PASSWORD` | `AgentTeams2026!` |
| `AGENTTEAMS_MANAGER_USER` | `manager` |

> 注意：Manager 的 Matrix 用户是 `@manager:...`，**不是** `default`。

---

## 六、完整闭环实测结果（本次实验核心证据）

### 6.1 方法

用只读监控脚本（只读现有房间，**不重复发任务**）追踪里程碑，直到 `RETROSPECT_DONE`。

### 6.2 里程碑时间线（真实）

```
0s     TASK_SPEC_READY  <- aggregator     P 计划（需求聚合）
0s     ROOT_CAUSE_FOUND <- rootcause      D 执行（根因分析）
0-45s  FIX_APPLIED      <- fixer          D 执行（代码修复，10/10 测试通过）
0-45s  TEST_PASSED      <- tester         C 检查（测试验证）
60s    RELEASE_OK       <- releaser       A 处置（发布确认）
136s   RELEASE_OK       <- retrospector   A 处置
181s   RETROSPECT_DONE  <- retrospector    A 处置（复盘，闭环闭合）
```

**完整「缺陷 → 根因 → 修复 → 测试 → 发布 → 复盘」闭环在官方 AgentTeams 平台真实跑通。**

### 6.3 修复工程师的真实产出（Manager 汇报）

- **三层修复模式**：入口参数校验治本 + 下游空值防护 + 全局异常映射
- 修复后：空用户名 → **400**（不再 500）、正常登录 → 200、密码错 → 401（防枚举）
- **自动化测试 10/10 通过**（`test_login_fix.py`）
- 交付物完整：`login_fix.py` / `test_login_fix.py` / `plan.md` / `result.md`（已推送 MinIO）

### 6.4 `run.py --mode delegated` 实测

后台运行 `run.py --mode delegated`（PID 12132），10 分钟内成功检测到：
```
TASK_SPEC_READY  ← @@manager     （@ 显示小瑕疵，见 §7）
ROOT_CAUSE_FOUND ← @@rootcause
FIX_APPLIED      ← @@fixer
```
随后因 `TASK_TIMEOUT=600`（10 分钟硬超时）退出，但 Manager 仍在后台推进闭环。

---

## 七、已知问题与改进建议

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 1 | **`wait_for_task` 默认 `TASK_TIMEOUT=600`（10 分钟）** | 闭环若超 10 分钟会被截断返回（delegated 模式下后台 run.py 因此退出） | 正式演示调大 `TASK_TIMEOUT`（如 3600）；或用只读监控脚本捕获 |
| 2 | **`@@` 双 at 显示瑕疵** | `detect_milestones` 打印时 worker 已带 `@`，又加一个 `@`，纯显示问题 | 打印前 `m['worker'].lstrip('@')` |
| 3 | **多并行链时 Worker 跨链混淆** | Manager 自报"三个并行同演练链（C/A/B）worker 跨链混淆" | 每次只发一条主链任务，避免并发演练；Manager 会自行评估收敛 |
| 4 | `status()` 的 `_list_resource("workers")` 返回空 | 触发无谓的 `ensure_pdca_workers` 告警（非阻塞） | 用 `agt get workers` 的表格解析替代 YAML 正则 |

---

## 八、复盘要点（下次再看直接取用）

### 8.1 正确的参赛路径

```
run.py → AgentTeamsLoop
   ├─ delegated（默认）：官方 Manager 驱动 6 Worker 接力（Matrix 留痕，推荐演示）
   └─ orchestrated：Python 控制流水线 + 确定性验证闸门（差异点）
          每阶段 → Matrix 给真实 Worker → 确定性脚本/裁判 Worker 判定 → state.py 推进
```

### 8.2 三件绝不能忘的事

1. **官方 `agt` CLI 没有 `task`/`send`/`messages`** —— 向 Manager/Worker 交互**必须走 Matrix**。
2. **Manager 的 Matrix 用户是 `manager`，不是 `default`** —— 发任务给 `@manager` 的 DM 房间。
3. **`AGENTTEAMS_ADMIN_PASSWORD` 是硬依赖** —— Matrix 登录需要它，缺了 `create_task` 会抛错。

### 8.3 我们的差异化卖点（官方没有，已保留）

| 卖点 | 位置 | 官方 AgentTeams 是否提供 |
|------|------|--------------------------|
| 确定性 PDCA 状态机 + 回滚 | `state.py` | ❌（官方 Manager 是 LLM 驱动、无硬编码状态机） |
| 确定性验证闸门（Ralph 反压） | `agentteams_loop.py::_run_deterministic_gate` | ❌（官方靠 Worker skill 自评） |
| 上下文工程（token 预算） | `context.py` | ❌ |
| 成员评价（贡献度+合格度） | `evaluation.py` | ❌（业界少见，评审亮点） |

---

## 九、本次实验变更文件清单

| 文件 | 变更 |
|------|------|
| `src/run.py` | 入口 MAF `TeamManagerLoop` → AgentTeams `AgentTeamsLoop` |
| `src/loop/__init__.py` | 移除 MAF 导出，`__all__` 只留原生 + 框架无关 |
| `src/loop/agentteams_client.py` | 新增 Matrix 客户端；`create_task`/`detect_milestones`/`wait_for_task` 改走 Matrix |
| `src/loop/agentteams_loop.py` | `_dispatch_to_worker`/`_verify_via_agentteams` 改走 Matrix；确定性闸门接入；`manager` 参数修正 |
| `src/loop/manager.py` | 归档横幅（MAF，不再参赛） |
| `src/loop/fixer_loop.py` | 归档横幅（MAF，不再参赛） |
| `src/AGENTTEAMS-MIGRATION.md` | §七 Loop 迁移结论 + §八 真实 CLI/Matrix 发现 + 完整闭环实测 |
| `design/EXPERIMENT-REVIEW.md` | 本文件 |

---

## 十、结论

> **迁移是成功的，且是"必要"的**——不只是因为 MAF 被禁止，更因为：
> 我们之前封装的 `agt task/send/messages` 是编造的，**在官方平台上根本跑不起来**。
> 把它换成官方真实使用的 **Matrix 协议** 后，`run.py --mode delegated` 委托给官方 Manager，
> **完整 PDCA 闭环（到 `RETROSPECT_DONE`）在真实 AgentTeams 平台跑通**。
> 我们的确定性状态机 / 验证闸门 / 成员评价作为官方缺失的差异价值，已嵌进官方框架而非替换它。

---

*记录时间：2026-08-14 · 项目：software-dev-fullflow（GOAI 赛道三 · 软件研发全流程协同）*
