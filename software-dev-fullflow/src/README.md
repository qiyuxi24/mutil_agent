# src/ — 可运行的研发团队调度 Loop

> 这是把 `design/MANAGER-LOOP-DESIGN.md` 的调度设计 + `design/PDCA-CLOSED-LOOP.md` 的状态机
> **落地为可运行代码**（PLAN 第 7 项"AgentTeams 代码包"的最小可运行版本）。
>
> 运行底座：**MAF**（Microsoft Agent Framework）+ **DeepSeek**（OpenAI 兼容协议），
> 已在 `demo/` 实证跑通。这里用它驱动 6 个研发 Worker 完成一条完整 PDCA 闭环。

## 这是什么

一个 **Manager 调度 Loop**：Manager 不做具体编码/测试，只做调度
`派单 → 收结果 → 验证闸门判断 → 推进/打回里程碑 → 循环`，
驱动 6 个研发 Agent 接力完成「缺陷/需求 → 根因 → 修复 → 测试 → 发布 → 复盘」闭环。

**6 个研发 Worker**（映射真实研发团队，见 `loop/team.py`）：

| Worker | 真实角色 | 里程碑 |
|--------|---------|--------|
| aggregator 缺陷聚合员 | 产品经理+缺陷管理 | TASK_SPEC_READY |
| rootcause 根因定位员 | 架构师(RCA+影响面) | ROOT_CAUSE_FOUND |
| fixer 修复工程师 | 前后端开发 | FIX_APPLIED |
| tester 测试验证员 | 测试(质量门禁) | TEST_PASSED |
| releaser 发布确认员 | 运维/DevOps(灰度+回滚) | RELEASE_OK |
| retrospector 复盘沉淀员 | 数据分析+知识沉淀 | RETROSPECT_DONE |

**闭环状态机**（`loop/state.py`）：
`SPEC_INPUT → SPEC_DECOMPOSE → ROOT_CAUSE → FIX_APPLY → TEST_VERIFY → RELEASE → RELEASE_APPROVE → RETROSPECT`
打回：`TEST_FAILED` / `RELEASE_ROLLED_BACK` → 打回 `FIX_APPLY`（有次数上限防死循环）。

**验证闸门**：不依赖 Agent 自律收敛，由独立裁判 Agent（tester/releaser）做客观 PASS/FAIL 判断。

## 目录

```
src/
├── run.py              ← 交互主入口
├── loop/
│   ├── __init__.py
│   ├── state.py        ← PDCA 状态机 + 里程碑 + 打回
│   ├── team.py         ← 6 个研发 Agent 角色定义
│   └── manager.py      ← Manager 调度 Loop（核心）
└── data/               ← 运行产物（gitignore）：shared/tasks/{id}/ + shared/knowledge/
```

## 环境准备（一次性）

MAF 环境已在 `demo/.venv` 建好（含 DeepSeek 配置）。复用即可：

```powershell
# 确认 demo/.env 有有效 DeepSeek key（已存在则跳过）
cd software-dev-fullflow\demo
notepad .env   # 确认 DEEPSEEK_API_KEY 有效

# 若 .venv 不存在则重建
python -m venv .venv
.\.venv\Scripts\python -m pip install agent-framework-core agent-framework-openai agent-framework-orchestrations python-dotenv
```

## 运行

```powershell
cd software-dev-fullflow\src

# ① 快速演示（推荐，秒级跑完完整 8 阶段闭环，不调 API）
..\demo\.venv\Scripts\python.exe run.py --mock "定位并修复用户列表加载慢的问题"

# ② 真实闭环（调 DeepSeek API，完整 8 阶段约 10-20 分钟，可先看前几阶段）
..\demo\.venv\Scripts\python.exe run.py --stages 3 "登录接口并发下偶发 500"
#   --stages N：只跑前 N 阶段，快速看真实 Agent 效果
#   不带 --stages：跑完整 8 阶段闭环

# ③ 交互模式（输入缺陷/需求描述）
..\demo\.venv\Scripts\python.exe run.py
```

> **网络提示**：已内置绕过系统/环境代理（`httpx.AsyncClient(trust_env=False)`），
> 避免本机代理未启动时出现 `10061 连接被拒`。

## 输出

- 控制台实时打印每个阶段：`派单 → Worker 产出 → 校验 PASS/FAIL → 里程碑推进`
- `src/data/shared/tasks/{task_id}/`：
  - `state.json` —— 闭环状态（可审计：state/milestones/artifacts/iterations）
  - `{stage}.md` —— 各阶段产物
- `src/data/shared/knowledge/` —— 复盘沉淀（待 RAG 检索）

## 与参赛作品的关系

- **这是 PLAAN 第 7 项的可运行落地**：6 Worker + 调度 loop + PDCA 状态机 + 里程碑握手 + 验证闸门 + 打回，全部可跑。
- **MAF 是参考实现**，官方要求的协同基点是 **AgentTeams**。本代码把"调度意图"显式化为
  Manager Loop，后续只需把 `loop/manager.py` 里的 Worker 调用替换为 AgentTeams 的
  `dispatch_task/poll_worker/write_milestone`（对应 `design/MANAGER-LOOP-DESIGN.md` 3.3 工具集）。
- 满足官方多项要求：多 Agent 协同闭环、里程碑上下文传递、验证闸门 + 回滚、状态可审计、复盘沉淀。
