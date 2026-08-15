# src/ — 可运行的研发团队调度 Loop（AgentTeams 原生）

> 这是把 `design/MANAGER-LOOP-DESIGN.md` 的调度设计 + `design/PDCA-CLOSED-LOOP.md` 的状态机
> **落地为可运行代码**（PLAN 第 7 项）。
>
> 运行底座：**AgentTeams 官方框架**（阿里开源，比赛协同基点）+ **DeepSeek**（OpenAI 兼容协议）。
> 完整 PDCA 闭环已在真实平台实测通过（Matrix 留痕）。**115 例确定性测试 ALL PASS**。

## 初赛交付状态（2026-08-15）

| 实验 | 证据 |
|------|------|
| Mock 完整闭环（6/6 里程碑 + RETROSPECT_DONE） | `demo/e2e-log-20260815-final.txt` |
| 真实平台部分闭环（3/6 里程碑 LLM 驱动） | 同上 + `src/AGENTTEAMS-MIGRATION.md` §八 |
| 委托模式降级（平台不可用 → 自动 fallback Mock） | `tests/test_delegated_fallback.py`（3 PASS） |
| 动态团队治理（招人/裁员闭环） | `tests/test_e2e_dynamic_hiring.py`（8 PASS） |
| 团队建站能力（MBTI 测评网站） | `demo/mbti-site-e2e-*/`（2 批验证） |
| LoongSuite 推理轨迹观测 | `scripts/verify-loongsuite-traces.py`（PASS） |
| UModel 统一数据模型 | `scripts/verify-umodel-model.py`（PASS） |
| Team + Leader 两级组织 | `agt get teams` 确认 Active（1 Leader + 6 Worker） |

## 这是什么

一个 **AgentTeams 原生调度 Loop**，驱动 6+1 个研发 Worker 接力完成 PDCA 闭环：

- **delegated（委托）**：任务发给 AgentTeams 官方 Manager，由 Manager 自动驱动 6 Worker 接力（Matrix 留痕，推荐）
- **mock（模拟）**：本地秒级演示完整闭环，不调 API，用于快速验证与自检
- **Team + Leader 两级协作**：6 Worker 组织进 `rnd-team`（Team CR），由 `team-leader` 在 Team Room 内协调（2026-08-15 落地）

**6 个研发 Worker**（映射真实研发团队，身份来源见 `agents/AGENT-IDENTITY.md` → `src/agentteams/workers/<name>/SOUL.md` → `workers.yaml`）：

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

## 三层架构

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 3: AgentTeams 平台深度集成                              │
│  agentteams_client.py (agt CLI + Matrix 协议 + Human 介入)    │
├──────────────────────────────────────────────────────────────┤
│  Layer 2: 标准化 Agent 接口层                                  │
│  agent_interface.py (AgentInterface ABC) + agent_bus.py       │
├──────────────────────────────────────────────────────────────┤
│  Layer 1: 调度 Loop 核心升级                                   │
│  iterative_worker.py (Ralph 迭代) + context.py (动态预算)      │
├──────────────────────────────────────────────────────────────┤
│  共享协议层                                                    │
│  state.py (PDCA 状态机) + evaluation.py (评价) + audit_logger.py (审计) │
└──────────────────────────────────────────────────────────────┘
```

## 目录

```
src/
├── run.py                    ← 交互主入口（AgentTeams 原生）
├── debug_fixer.py            ← Fixer 独立调试脚本
├── AGENTTEAMS-MIGRATION.md   ← 迁移蓝图 + 实测证据
├── README.md                 ← 本文件
│
├── loop/                     ← 调度 Loop 核心（全部 AgentTeams 原生）
│   ├── __init__.py               ← 模块导出
│   ├── state.py                  ← PDCA 状态机 + 里程碑 + 打回（协议层）
│   ├── agentteams_loop.py        ← AgentTeams 客户端调度循环（delegated/mock）
│   ├── agentteams_client.py      ← 平台客户端（agt CLI + Matrix 协议 + Human 介入）
│   ├── context.py                ← 上下文工程（预算 + 动态分配 + 语义检索 + 三层记忆）
│   ├── evaluation.py             ← 成员评价器（合格度 + 贡献度三层模型）
│   ├── iterative_worker.py       ← 通用 IterativeWorker 基类（Ralph 自我迭代，Layer 1）
│   ├── agent_interface.py        ← 标准化 Agent 接口（Layer 2）
│   ├── agent_bus.py              ← 消息总线 + 事件驱动（Layer 2）
│   ├── audit_logger.py           ← 结构化审计日志（JSON-Lines 落盘）
│   ├── dashboard.py              ← Rich 终端仪表盘
│   ├── web_dashboard.py          ← Web SSE 仪表盘
│   ├── reverse_gateway.py        ← 反向网关
│   ├── workbuddy_client.py       ← WorkBuddy 客户端
│   ├── verify_reverse_api.py     ← 反向 API 验证
│   └── test_context_with_api.py  ← 上下文工程 API 测试
│
├── agentteams/               ← AgentTeams 声明式资源
│   ├── workers.yaml              ← 6 Worker CRD 声明
│   ├── team-rnd.yaml             ← Team CR（1 Leader + 6 Worker）
│   ├── team-leader.yaml          ← Leader Worker CR
│   ├── security-config.json      ← 安全守卫配置
│   ├── SECURITY-POLICY.md        ← 安全策略说明
│   ├── manager/SOUL.md           ← PDCA Manager 编排指令
│   ├── mcp/                      ← MCP 服务器配置
│   ├── umodel/                   ← UModel 统一数据模型包（9 entity_set + 9 link + 2 storage）
│   └── workers/<name>/SOUL.md    ← 每个 Worker 的 SOUL
│
└── data/                     ← 运行产物（gitignore）
```

## 运行

```powershell
cd software-dev-fullflow\src

# ① Mock 模式（秒级演示，不调 API，推荐初赛演示）
..\demo\.venv\Scripts\python.exe run.py --mock "定位并修复用户列表加载慢的问题"

# ② 委托 AgentTeams 官方 Manager 驱动（真实闭环，需平台运行中）
..\demo\.venv\Scripts\python.exe run.py "登录接口并发下偶发 500"
# 平台不可用时自动降级为 Mock 模式，保证演示不翻车

# ③ 交互模式
..\demo\.venv\Scripts\python.exe run.py --interactive

# ④ 终端仪表盘（Rich 实时进度 + Worker 状态 + 事件流）
..\demo\.venv\Scripts\python.exe run.py --dashboard "你的任务描述"

# ⑤ Web 浏览器仪表盘（SSE 实时推送 + 人工审批）
..\demo\.venv\Scripts\python.exe run.py --web "你的任务描述"

# ⑥ 仪表盘 + 交互命令（终端仪表盘 + 实时交互）
..\demo\.venv\Scripts\python.exe run.py --dashboard --interactive "你的任务描述"

# ⑦ 团队建站能力验证（MBTI 测评网站）
..\demo\.venv\Scripts\python.exe scripts\verify-team-builds-website.py --mock

# ⑧ 运行全部确定性测试
..\demo\.venv\Scripts\python.exe -m pytest tests/ -q
```

## 环境变量（连接 AgentTeams 平台）

```
AGENTTEAMS_MATRIX_URL        (默认 http://127.0.0.1:18080)
AGENTTEAMS_MATRIX_DOMAIN     (默认 matrix-local.agentteams.io:18080)
AGENTTEAMS_ADMIN_USER        (默认 admin)
AGENTTEAMS_ADMIN_PASSWORD    (必填，本项目 AgentTeams2026!)
AGENTTEAMS_MANAGER_USER      (默认 manager)
```

## 输出

- 控制台实时打印每个阶段：派单 → Worker 产出 → 校验 PASS/FAIL → 里程碑推进
- `src/data/shared/tasks/{task_id}/`：
  - `state.json` —— 闭环状态（可审计：state/milestones/artifacts/iterations）
  - `{stage}.md` —— 各阶段产物
- `src/data/shared/knowledge/` —— 复盘沉淀（待 RAG 检索）
- Matrix 房间留痕：Element Web（http://127.0.0.1:18088）可查看完整对话历史

## 实测证据

### 真实平台闭环（2026-08-14，首次跑通）

真实平台驱动 6 Worker 跑通「登录接口空用户名返回 500」完整 PDCA 闭环（181 秒）：

| 时间(s) | 里程碑 | Worker | 环节 |
|--------|--------|--------|------|
| 0 | TASK_SPEC_READY | aggregator | P 计划 |
| 0 | ROOT_CAUSE_FOUND | rootcause | D 执行 |
| 0-45 | FIX_APPLIED | fixer | D 执行（10/10 测试通过） |
| 0-45 | TEST_PASSED | tester | C 检查 |
| 60 | RELEASE_OK | releaser | A 处置 |
| 136 | RELEASE_OK | retrospector | A 处置 |
| 181 | RETROSPECT_DONE | retrospector | A 处置（闭环闭合） |

### 端到端验证（2026-08-15，综合证据）

- **Mock 模式**：6/6 里程碑 + RETROSPECT_DONE + 审计 + 12 成绩单（证据：`demo/e2e-log-20260815-final.txt`）
- **真实平台**：workers.yaml MCP 格式修复（v1.1.1+ Breaking Change，6 Worker 全部 `{name,url,transport}` 对象数组）→ apply 成功 + 10 容器 Running + 3/6 里程碑 LLM 驱动
- **降级策略**：平台不可用时自动 fallback Mock，保证演示不翻车（GAP-04 已实现）
- **真实平台未完成全部 6 里程碑原因**：LLM 网关（deepseek-v4-flash）延迟 2-4 分钟/次，多轮后超时，记复赛项

详见 `src/AGENTTEAMS-MIGRATION.md` §八 和 `design/EXPERIMENT-REVIEW.md`。

## 与参赛作品的关系

- **这是 PLAN 第 7 项的可运行落地**：6 Worker + 调度 loop + PDCA 状态机 + 里程碑握手 + 验证闸门 + 打回，全部可跑。
- **协同基点 = AgentTeams 官方框架**（阿里开源）。MAF 底座（`manager.py` / `fixer_loop.py`）已移除，不再参与参赛主路径。
- 满足官方多项要求：多 Agent 协同闭环、里程碑上下文传递、验证闸门 + 回滚、状态可审计、复盘沉淀、沙箱安全隔离。
- **差异化卖点**（官方 AgentTeams 不具备）：
  - 确定性 PDCA 状态机 + 回滚（`state.py`）
  - 确定性验证闸门 / Ralph 反压（非 LLM 自评）
  - 上下文工程（token 预算 + 动态分配）
  - 成员评价（贡献度 + 合格度三层模型）
  - 动态团队「招人/裁员」治理
  - 团队建站能力（从零搭建 MBTI 测评网站）