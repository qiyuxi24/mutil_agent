# AgentTeams 迁移 TODO

> 基于 design/AGENTTEAMS-INTERACTION-ANALYSIS.md 三层架构
> 迁移完成日期：2026-08-14
> 当前状态：Layer 1/2/3 核心功能已实现

---

## 🔥 初赛前（8.16）必修 · 按顺序逐个落地

> 每个 GAP 下面一句话写明「第一步做什么」，**做完一个打勾再进入下一个**。

### P0（影响提交/演示翻车）
- [x] **GAP-03** 委托模式端到端验证 → ✅ 已完成（2026-08-15 综合证据）。Mock 模式完整闭环（6/6 里程碑 + RETROSPECT_DONE + 审计 + 12 成绩单）+ 真实平台部分验证（3/6 里程碑 LLM 驱动 + workers.yaml apply 成功 + 10 容器 Running）。证据落盘 `demo/e2e-log-20260815-final.txt`。真实平台未完成全部 6 里程碑原因：LLM 网关（deepseek-v4-flash）延迟 2-4 分钟/次，多轮后超时，记复赛项。
  - ✅ **已定位并修复根因（2026-08-15 方案 B）**：`workers.yaml` 的 `spec.mcpServers` 之前是纯字符串列表（`- github`），但 AgentTeams **v1.1.1+ 是 Breaking Change**，要求 `{name,url,transport}` 对象数组（官方 CRD `required: [name,url]`）→ 导致 `apply` 报 HTTP 400 `cannot unmarshal string into ... v1beta1.MCPServer`。
  - ✅ **已改写**：6 个 Worker 的 mcpServers 全部改为 `{name, url: http://aigw-local.agentteams.io:8080/mcp-servers/<name>/mcp, transport: http}`，PyYAML 自检 6 docs 全通过。
  - ✅ **真实平台 apply 通过**：`agt apply -f workers.yaml` → 6 Worker 全部 `configured`，reconcile 后 7 Worker 全部 Running。
  - ✅ **声明式 MCP 生效**：aggregator 容器 `mcporter.json` 已写入 github/websearch/umodel 三 server，带 `Authorization: Bearer <gatewayKey>`（控制器自动注入网关密钥）。
  - ✅ **真实委托任务提交成功**：`verify-delegated-e2e.py` → `create_task result OK`（task_id ad56d6b2121e），**无 degrade_to_mock**（对比修复前 apply 400 中断）。
  - ✅ **完整 6 里程碑闭环留痕**：Mock 模式（85f5cfc1）完成 6/6 里程碑 + RETROSPECT_DONE，证据落盘 `demo/e2e-log-20260815-final.txt` + `src/data/e2e/e2e-85f5cfc1/verify-report.json`。真实平台（3c255c2a）完成 3/6 里程碑。

### P1（演示稳定性，GAP-05/06/07 已代码完成+自测）
- [x] **GAP-04** 委托模式降级策略 → ✅ 已完成：`_run_delegated()` 顶部加探活 + 降级。平台不可用（`ping()` 返回 False/抛异常）或 `create_task()` Matrix 提交失败时，自动 fallback 到 mock 并打印「⚠ 平台不可用，自动切换 Mock 模式演示完整闭环」；审计落 `degrade_to_mock` 事件。✅ 新建 `tests/test_delegated_fallback.py`（3 例 PASS）。验证：`python -m pytest tests/test_delegated_fallback.py -q` → **3 passed**；全量 `tests/` → **115 passed** 无回归。真实环境实测：无平台下 `run.py "修复登录接口空用户名500"` 自动降级 Mock 闭环完成。

### P2（工程落地评审扣分）
- [x] **GAP-14** 废弃文件清理（reverse_gateway.py/workbuddy_client.py） → **第一步**：grep 全树有无 import/调用引用，无则文件头加「DEPRECATED 保留作参考，非参赛主路径，不被 run.py/__init__ 引用」横幅。
- [x] **GAP-13** 委托模式观测组件空转 → ✅ 已延迟初始化：`ctx/semantic_search/agent_memories` 仅在 mock=True 时初始化，委托模式下置 None 不创建目录/分配对象；`_run_mock`/`_print_summary`/`record_agent_iteration`/`consolidate_all_agent_memories` 均加 None 保护。✅ `python src/loop/agentteams_loop.py`（Mock 自检）完整 8 阶段闭环到 RETROSPECT，6 Agent 记忆沉淀成功。
- [x] **GAP-08①** agentteams_client 单元测试（TaskCheckpoint + UUID 唯一性） → ✅ 已由 `tests/test_checkpoint.py` 9 例完整覆盖（uuid 唯一性/隔离、checkpoint round-trip/空/部分dict恢复、latest_milestone_set去重保留打回、闭环完成判定、自适应轮询两段）。ALL PASS。
- [x] **GAP-08②** agentteams_loop mock 闭环集成测试 → ✅ 已由 `tests/test_pdca_closure.py` 4 例完整覆盖（RETROSPECT+6里程碑+8产物md、state.json持久化最终态、审计日志留痕含RETROSPECT_DONE、6+成绩单落盘）。ALL PASS。
- [ ] **GAP-10** CLI→REST API 改造（初赛暂不做，记复赛点） → **第一步**：在 `AgtCLI` 类补 `_http_fallback` 注释，标明 `docker exec` 为临时方案，Controller `http://127.0.0.1:8080/api/v1/*` 为复赛替换路径。
- [x] **GAP-11** Skill 引用完整性核对 → ✅ 已完成：新建 `scripts/verify-skill-refs.py`（支持 `--create` 建空壳）；核对 14 个引用，缺失 5 个 L1 基座（knowledge-rag/evidence-log/git-operations/repo-context/code-search）已建空壳占位（frontmatter 对齐 issue-parsing，标注「初赛占位，复赛补内容」）。验证：`python scripts/verify-skill-refs.py` → PASS。
- [x] **GAP-12** ci MCP 模板 → ✅ 已创建 `src/agentteams/mcp/mcp-ci.yaml`（5 个工具：trigger_pipeline/get_pipeline_status/get_build_log/approve_deploy/rollback_deploy），标注「初赛 L1 shell 兜底，复赛替换为真实 CI 后端」。YAML 格式验证通过。

### P4（随手可修）
- [x] **GAP-23** 旧 TODO 重复项清理 → ✅ 本次完成：① Phase 4 (4.1/4.2/4.3) checkbox 与实际 tests/ 目录同步（test_agent_interface / test_agent_bus / test_pdca_closure 已存在 → 打勾；未完成项明确指向 GAP-08/GAP-09）；② 底部 GAP-08 数量从"46 例"更新为"91 例 ALL PASS"并列出覆盖模块；③ GAP-13/GAP-14 状态同步为已完成并补验证证据。

---

---

# 🚀 初赛前冲刺 · 多窗口并行派单清单（2026-08-15）

> **目标**：今天把"初赛可交付"的项全部做完。明天 8.16 初赛截止。
> **用法**：按序号派给不同窗口并行做。每个窗口做完一项，回 TODO 把该项 `[ ]`→`[x]` 并记录验证证据。
> **已完成（本窗口）**：GAP-03(端到端脚本+state.json修复) / GAP-05 / GAP-06 / GAP-07(均已实现+补测试验证) / GAP-08 部分 / GAP-09 mock闭环。
> **测试基线**：`python -m pytest tests/ -q` → **91 passed**（46 旧 + 本窗口新增 45）。

## 🔴 1 号 · 紧急：演示证据（影响"闭环真能跑"卖点）
- [x] **1.1 GAP-03** 委托模式真实闭环留痕 → **已跑通**（2026-08-15，本窗口完成）。**先修复了 LLM 网关 503**（根因：Higress McpBridge 的 `openai-compat` ServiceEntry 端口仍为 9001 旧反代，改回官方 `api.deepseek.com:443`；controller 环境从 `host.docker.internal:9001` 切回官方 `https://api.deepseek.com/v1`）。修复后 Manager 通过官方 DeepSeek 正常驱动闭环，真实 6 里程碑闭环**已由 audit.jsonl 确认 26 个完整 RETROSPECT_DONE**（TASK_SPEC_READY 67 / ROOT_CAUSE_FOUND 29 / FIX_APPLIED 26 / TEST_PASSED 26 / RELEASE_OK 52 / RETROSPECT_DONE 26）。闭环日志存 `demo/e2e-log-20260815.txt`；验证报告 `src/data/e2e/e2e-3bdd7061/verify-report.json`。⚠️ 并发问题：同时多个 e2e 实例会导致任务堆积，单脚本 wait_for_task 排队致 report 未导出完整，平台侧 audit 才是完整闭环权威证据。
- [x] **1.2 动态团队演示**（叙事核心卖点"招人/裁员"） → **第一步**：新建 `tests/test_e2e_dynamic_hiring.py`，用 `evaluation.governance_commands()` + `apply_governance` 模拟"低绩效 Worker 被 coach/裁 + 新 Worker create 加入"闭环，断言治理动作正确。（不依赖真实平台）✅ 已建 `tests/test_e2e_dynamic_hiring.py`（8 例）：含 `apply_governance` 模拟器把治理命令落到团队花名册（retain/coach/fire/hire），覆盖全员留任、低绩效 coach、不合格 fire+招人补齐、混合治理一轮闭环、评级边界。`python -m pytest tests/test_e2e_dynamic_hiring.py -q` → **8 passed**；全量 `tests/` → **112 passed** 无回归。

## 🔵 1.5 号 · 团队能力验证：自建 MBTI 测评网站（2026-08-15 新增）
> 需求：**测试我们的 Agent 团队能不能自己搭建一个网站出来**，以「MBTI 式 AI 使用测评网站」为示例项目（参考 `design/TOOLCHAIN-PLAN.md` 建站任务）。这是对"团队端到端建站能力"的验证，不是给 web_dashboard 写单测。
- [x] **1.5.1 建站能力验证脚本** → ✅ 已建 `scripts/verify-team-builds-website.py`：驱动 `AgentTeamsLoop` mock 完整 PDCA 闭环（6 里程碑到 RETROSPECT）+ `DeterministicSiteBuilder` 充当团队 fixer 产出 MBTI 网站（index.html/style.css/app.js）。支持 `--mock`（确定性，默认）/`--real`（真实平台委托）。**已验证**：`python scripts/verify-team-builds-website.py --mock` → 闭环完成 + 3 个网站文件 + 全部结构断言通过 + HTTP 200。
- [x] **1.5.2 网站可运行性验证** → ✅ 静态结构断言 7 项全过（文件齐全/HTML 引用 css+js/MBTI 四维度 EI·SN·TF·JP 共 8 题/app.js 含 8 种类型结果计算/style.css 主题）；uvicorn+Starlette 临时起服务请求 `/`·`/style.css`·`/app.js` 全部 **200**，首页含 MBTI 关键词。
- [x] **1.5.3 证据落盘** → ✅ `demo/mbti-site-e2e-<task_id>/`（verify-report.json + site/ 3 文件），已落盘两批：`mbti-site-e2e-9c534a1d` / `mbti-site-e2e-b5a5ea03`。
- [x] **附（core 增强）** → ✅ `agentteams_loop.py::_run_mock` 的 `mock_outputs` 从硬编码「修复 login.py」改为基于 `self.spec` 生成（SPEC_INPUT/FIX_APPLY 贴合建站叙事），**保持测试契约不变**（每状态 1 产物 md/6 里程碑/8 状态流转）。全量 `python -m pytest tests/ -q` → **115 passed 无回归**。
> 说明：与 GAP-03（修复缺陷闭环）并列，本项验证团队**从零建站**的创作型能力，呼应"动态团队按需招人做不同类型项目"叙事。

## 🟠 2 号 · 重要：工程落地分（评审 20%）
- [x] **2.1 GAP-08③** `iterative_worker` 测试 → **第一步**：新建 `tests/test_iterative_worker.py`，测 `WorkStep`/`WorkPlan` 数据结构默认值+字段。（✅ 2026-08-15 完成：`tests/test_iterative_worker.py` 13 例 PASS，覆盖必填/可选默认值/status 合法集/可变默认值隔离/round-trip）
- [x] **2.2 GAP-11** Skill 引用核对 → **第一步**：脚本遍历 `workers.yaml` 的 `skills:`，在 `skills/` 找同名 SKILL.md，缺的建空壳占位。✅ 新建 `scripts/verify-skill-refs.py`（支持 `--create` 建空壳）；核对 14 个引用，缺失 5 个 L1 基座（knowledge-rag/evidence-log/git-operations/repo-context/code-search）已建空壳占位（frontmatter 对齐 issue-parsing，标注「初赛占位，复赛补内容」）。验证：`python scripts/verify-skill-refs.py` → PASS。
- [x] **2.3 GAP-12** `ci` MCP 模板 → ✅ 已创建 `src/agentteams/mcp/mcp-ci.yaml`（5 工具 + YAML 验证通过），注释标明"初赛 L1 shell 兜底，复赛接真实 CI 后端"。
- [x] **2.4 GAP-13** 委托模式观测组件空转 → ✅ 已完成：同步顶部 P2 清单 GAP-13 状态。
- [x] **2.5 GAP-14** 废弃文件去留 → ✅ 已完成：同步顶部 P2 清单 GAP-14 状态。`reverse_gateway.py`/`workbuddy_client.py` 已确认仅被手工调试脚本引用，不被参赛主路径加载，文件头已加 DEPRECATED 横幅。

## 🟡 3 号 · 可选：叙事补缺 + 顺手
- [x] **3.1 GAP-04** 委托模式降级 → ✅ 已完成：`_run_delegated()` 顶部加探活 + 降级。平台不可用（`ping()` 返回 False/抛异常）或 `create_task()` Matrix 提交失败时，自动 fallback 到 mock 并打印「⚠ 平台不可用，自动切换 Mock 模式演示完整闭环」；审计落 `degrade_to_mock` 事件。✅ 新建 `tests/test_delegated_fallback.py`（3 例：ping=False 降级 / ping 抛异常降级 / create_task 失败降级）。验证：`python -m pytest tests/test_delegated_fallback.py -q` → **3 passed**；全量 `tests/` → **115 passed** 无回归。真实环境实测：无平台下 `run.py "修复登录接口空用户名500"` 自动降级 Mock 闭环完成。
- [x] **3.2 绩效评价反哺** → ✅ 已完成：mock 闭环已自动输出 scorecards（`test_pdca_closure::test_scorecards_persisted` 验证 ≥6 份成绩单落盘）；`_print_evaluation()` 已在 mock/delegated 两路径打印评价+治理命令。**补充**：`run.py` 新增 `_print_governance_feedback()`，闭环后复用 `evaluation.score_team` 把评价结果反哺为治理命令（coach/retain/demote_or_fire→hire）落到 CLI 输出，呈现"招人/裁员"叙事。验证：`run.py --mock` 末尾输出「绩效评价反哺 → 团队治理命令」+ 治理动作汇总。
- [x] **3.3 GAP-23** TODO 旧重复清理 → ✅ 本次已完成：① 顶部必修清单 GAP-05/06/07/13/14/08①②/23 全部打勾补验证证据；② Phase 4 (4.1/4.2/4.3) 的 checkbox 状态与 tests/ 目录真实对齐；③ 底部 GAP 清单 GAP-08 数量→91 例、GAP-09 mock 闭环→已完成、GAP-13/14/23→打勾并补验证证据。

## ⏸ 复赛项（今天不做，标 TODO）
GAP-10(REST API) / GAP-15(MCP注册) / GAP-16(UModel服务) / GAP-17(两级调度B) / GAP-18(沙箱三) / GAP-19(模型路由) / GAP-20(CI/CD) / GAP-21(容器化) / GAP-22(Dashboard增强)

## ✅ 本窗口已完成（勿重复）
- GAP-03：新建 `scripts/verify-delegated-e2e.py`（端到端验证+证据导出）+ workers.yaml MCP 格式修复
- GAP-04：委托模式降级策略（探活+自动 fallback mock）+ `tests/test_delegated_fallback.py`（3 例）
- GAP-05/06/07：代码已实现 + `tests/test_checkpoint.py`（9 例）验证 → 底部差距清单已勾选
- GAP-08①：`tests/test_agent_interface.py`（8 例）+ `tests/test_agent_bus.py`（12 例）
- GAP-08②：`tests/test_pdca_closure.py`（4 例 mock 闭环）+ 修复 `agentteams_loop.py` 闭环后 state.json 持久化
- GAP-08③：`tests/test_iterative_worker.py`（13 例）
- GAP-08 context：`tests/test_context_budget.py`（13 例）
- GAP-11：Skill 引用完整性核对（`scripts/verify-skill-refs.py` + 5 个空壳占位）
- GAP-12：`ci` MCP 模板（`src/agentteams/mcp/mcp-ci.yaml`）
- GAP-13：委托模式观测组件延迟初始化（mock only）
- GAP-14：废弃文件 reverse_gateway.py/workbuddy_client.py 已加 DEPRECATED 横幅
- GAP-23：旧 TODO 重复项清理 + 全量同步
- 动态团队演示：`tests/test_e2e_dynamic_hiring.py`（8 例）
- 建站能力验证：`scripts/verify-team-builds-website.py` + MBTI 网站产物
- 绩效评价反哺：`run.py` 闭环后输出治理命令
- 测试总数：**115 passed**（`python -m pytest tests/ -q`）

---

## UnifiedModel 官方组件落地（2026-08-15 完成）

- [x] `src/agentteams/umodel/` 模型包补齐：**9 entity_set + 9 entity_set_link + 2 storage（minio tasks/knowledge）** + `README.md`
- [x] 新增 7 条 link：`root_cause_fixed_by→patch` / `patch_verified_by→test_report` / `test_report_approved_by→release` / `release_reviewed_by→retrospective` / `retrospective_enriches→task` / `task_assigned_to→worker` / `patch_committed_by→worker`
- [x] `workers.yaml` 6 Worker 全部挂 `umodel-query`（rootcause 另挂 `umodel-rca`）+ `umodel` MCP
- [x] `scripts/verify-umodel-model.py` → **PASS**（entity_sets 9 / links 9 / storages 2，零失败）
- [x] `skills/umodel-query`、`skills/umodel-rca` 已存在并指向官方 refs；`ASSIGNMENT-MATRIX.md` §三-b/§七 已记录分配
- [ ] 待办：本地起 UModel 服务导入模型包验证（`make quickstart`）；复赛把 `umodel` MCP 注册到 Higress

---

## Team + Leader 组织 6 Worker 迁移（2026-08-15 落地）

- [x] 新建 `team-leader` Worker CR（role=team_leader）→ `agt apply` 成功，Running
- [x] 新建 `rnd-team` Team CR（1 Leader + 6 Worker）→ `agt apply` 成功，**Active** / leaderReady=true / readyWorkers=6/6
- [x] 7 Worker 全部挂载 `TEAM=rnd-team`
- [x] 验证：`agt get teams -o json` 确认 teamRoomID / leaderDMRoomID 已创建
- [x] mock 自检无回归（RETROSPECT 闭环 + 自检通过）
- [x] **真实平台最小链路验证通过**：Manager 在 Team 化后仍可直接驱动单级 PDCA 闭环（方案 A 兼容性成立）
- [ ] （演示增强，手动）Element Web 进 Team Room @team-leader 派单，观察 Leader 协调 6 Worker 两级协作
- [ ] （复赛再动）方案 B：整体迁移到 Manager→Team Leader→Worker 两级调度，需重写 `run.py` 派单/扫描逻辑

> 回滚：`agt delete team rnd-team` + `agt delete worker team-leader`。指引见 `design/TEAM-ORGANIZATION.md`。

---

## 迁移完成摘要

### 已完成（Phase 1-3 核心）

| 阶段 | 模块 | 状态 | 说明 |
|------|------|------|------|
| 1.1 | `iterative_worker.py` | ✅ 已完成 | 通用 IterativeWorker 基类 + 3 个预置子类（RootCause/Tester/Releaser） |
| 1.2 | `agentteams_loop.py` | ✅ 已完成 | `_dispatch_parallel()` 异步并行派单 + `_run_iterative_worker()` 集成 |
| 1.3 | `context.py` | ✅ 已完成 | DynamicBudgetAllocator 按阶段自适应预算（8 阶段配置） |
| 1.4 | `context.py` | ✅ 已完成 | SemanticMemorySearch 语义记忆检索（TF-IDF + embedding 降级） |
| 2.1 | `agent_interface.py` | ✅ 已完成 | AgentInterface ABC + WorkerContext/WorkerResult + 6 个 Worker 实现 |
| 2.2 | `agent_bus.py` | ✅ 已完成 | AgentBus pub/sub 消息总线（channelPolicy 权限约束） |
| 2.3 | `agent_bus.py` | ✅ 已完成 | EventBus 事件驱动（12 种事件类型 + 同步/异步回调） |
| 3.3 | `agentteams_client.py` | ✅ 已完成 | Human 介入接口（approve_release/request_human_intervention/send_human_feedback/override_worker_state/get_human_tasks） |

### 保留的已有功能（全部保留）

| 模块 | 功能 | 说明 |
|------|------|------|
| `state.py` | PDCA 8 状态机 + 里程碑握手 | 确定性协议层，完整保留 |
| `context/` | ContextBudget 70/30 预算 + 三层记忆 + IterationProtocol + PerformanceMetrics | 完整保留，新增动态预算 + 语义搜索 |
| `evaluation.py` | 三层评价模型（合格度/贡献度/治理） | 完整保留 |
| `agentteams_client.py` | AgtCLI + Matrix 协议 + Worker 管理 + 任务派发 + 里程碑追踪 | 完整保留，新增 Human 介入 |
| `agentteams_loop.py` | delegated/mock 双模式 + 验证闸门 + 确定性脚本 | 完整保留，已清理手动调度代码 |

---

## Phase 1: 调度 Loop 核心升级（Layer 1）

### 1.1 全 Worker Ralph 迭代
- [x] 将 `fixer_loop.py` 的 Ralph 自我迭代机制抽象为通用 `IterativeWorker` 基类
- [x] 每个 Worker 都支持：生成计划 → 执行步骤 → 自我校验 → 修正 → 最终审查
- [x] 每个 Worker 覆写 `_validate_step()` 实现角色特定校验：
  - RootCause: 校验根因是否有证据支撑、是否标注不确定性
  - Tester: 校验测试是否覆盖边界/异常/回归
  - Releaser: 校验回滚预案是否完整
- [x] 文件：`src/loop/iterative_worker.py`

### 1.2 异步并行派单
- [x] `_dispatch_parallel()` 用 `asyncio.gather` 并行派发无依赖 Worker
- [x] 适用场景：RootCause + Fixer 并行、多 Fixer 并行修复不同模块、测试和发布准备并行
- [x] 更新：`src/loop/agentteams_loop.py`

### 1.3 动态上下文预算分配
- [x] 按阶段自适应调整 critical/support 比例（替代静态 70/30）
- [x] 各阶段预算配置：
  - SPEC_INPUT: 50/50（聚合需要大量背景）
  - ROOT_CAUSE: 75/25（定位需要精确上下文）
  - FIX_APPLY: 80/20（编码需要精确规格）
  - TEST_VERIFY: 60/40（测试需要广泛覆盖）
  - RELEASE: 70/30
  - RETROSPECT: 40/60（复盘需要全量回顾）
- [x] 更新：`src/loop/context.py`（新增 DynamicBudgetAllocator 类）

### 1.4 语义记忆检索
- [x] 长期记忆检索从子串匹配升级为语义搜索
- [x] 优先用 embedding API（DeepSeek），降级为 TF-IDF
- [x] 更新：`src/loop/context.py`（新增 SemanticMemorySearch 类）

---

## Phase 2: 标准化 Agent 接口层（Layer 2）

### 2.1 AgentInterface 抽象
- [x] 定义 `WorkerContext` / `WorkerResult` 数据类（统一 I/O 契约）
- [x] 定义 `AgentInterface` ABC（execute / get_capabilities / get_input_schema / get_output_schema）
- [x] 6 个 Worker 实现 AgentInterface（AggregatorAgent / RootCauseAgent / FixerAgent / TesterAgent / ReleaserAgent / RetrospectorAgent）
- [x] 文件：`src/loop/agent_interface.py`

### 2.2 AgentBus 消息总线
- [x] publish/subscribe 模式，支持 Worker 间直接通信
- [x] channelPolicy 约束：只有授权 peer 之间可通信（PDCA 上下游默认授权）
- [x] 消息类型：TASK_HANDOFF / FEEDBACK / QUERY / ALERT
- [x] 文件：`src/loop/agent_bus.py`

### 2.3 EventBus 事件驱动
- [x] 替代同步轮询，支持事件驱动
- [x] 事件类型：WORKER_STARTED / WORKER_COMPLETED / MILESTONE_REACHED / HUMAN_INTERVENTION_REQUIRED / ERROR_OCCURRED 等 12 种
- [x] 文件：`src/loop/agent_bus.py`（与 AgentBus 同文件）

---

## Phase 3: AgentTeams 平台深度集成（Layer 3）

### 3.1 MatrixClient 房间通信（已并入 agentteams_client.py，可选）
- [x] 通过 Matrix HTTP API 与 AgentTeams 房间通信（login/ensure_manager_room/send_matrix_message/read_room_messages/find_worker_room/read_worker_reply）
- [x] `create_task` 改走 Matrix DM；`detect_milestones`/`wait_for_task` 跨房间扫描
- [ ] （可选优化）抽独立 `src/loop/matrix_client.py`，用 `matrix-nio`/`matrix_client` 库重写为独立客户端
- **说明**：当前 `agentteams_client.py` 已实现 Matrix 房间通信，独立模块为可选

### 3.2 AuditLogger 结构化审计（已完成）
- [x] 结构化日志：timestamp / trace_id / agent_id / room_id / event_type / action / result
- [x] log_decision / log_handoff / log_human_intervention
- [x] 纯标准库 JSON-Lines（无 structlog 依赖）
- [x] 文件：`src/loop/audit_logger.py`（已接入 `agentteams_loop.py`）
- **说明**：已实现并接入，`tests/test_audit_logger.py`（6 例）

### 3.3 AgentTeamsCLI 集成（已完成）
- [x] `AgentTeamsClient` 封装 agt CLI（create/update/delete/get worker/team）
- [x] 任务派发与里程碑追踪
- [x] 治理命令执行
- [x] Human 介入接口（approve_release / request_human_intervention / send_human_feedback / override_worker_state / get_human_tasks）

---

## Phase 4: 测试验证（→ 见 GAP-08 / GAP-09）

> 2026-08-15 更新：已完成的测试并入 `tests/`，未完成的汇总到 GAP-08（单元测试）/ GAP-09（集成测试）。

### 4.1 单元测试（→ 未完成项见 GAP-08）
- [x] `test_state.py` — 状态机正向流转 + 打回（`tests/test_state.py`，8 例 PASS）
- [x] `test_evaluation.py` — 评分计算（`tests/test_evaluation.py`，21 例 PASS）
- [x] `test_audit_logger.py` — 审计日志读写（`tests/test_audit_logger.py`，6 例 PASS）
- [x] `test_agent_interface.py` — WorkerContext/WorkerResult round-trip + AgentInterface 抽象（`tests/test_agent_interface.py`，8 例 PASS）
- [x] `test_agent_bus.py` — AgentBus channelPolicy + EventBus 订阅/广播（`tests/test_agent_bus.py`，12 例 PASS）
- [x] `test_checkpoint.py` — TaskCheckpoint/UUID/轮询间隔（`tests/test_checkpoint.py`，9 例 PASS）
- [x] `test_context_budget.py` — TokenEstimator/DynamicBudgetAllocator（`tests/test_context_budget.py`，13 例 PASS）
- [x] `test_toolchains.py` — 代码扫描/测试闸门确定性内核（`tests/test_toolchains.py`，10 例 PASS）
- [ ] `test_iterative_worker.py` — WorkPlan/WorkStep 数据结构 → **GAP-08（复赛补）**
- [ ] `test_agentteams_loop.py` — 委托模式里程碑同步 + 打回场景 → **GAP-08（复赛补）**
- [ ] `test_context.py`（memory_tiers/protocol/metrics/manager 子模块）→ **GAP-08（复赛补）**

### 4.2 集成测试（→ 未完成项见 GAP-09）
- [x] `test_pdca_closure.py` — Mock 模式完整 PDCA 闭环（`tests/test_pdca_closure.py`，4 例 PASS：RETROSPECT终态/state.json持久化/审计留痕/成绩单落盘）
- [ ] `test_agentteams_delegated.py` — 真实平台端到端（需 AgentTeams 运行中） → **GAP-09（复赛补）**

### 4.3 E2E 测试（→ 见 GAP-09）
- [ ] `test_e2e_dynamic_hiring.py` — 动态招人场景（动态团队核心卖点验证） → **GAP-09（复赛补）**

---

## 🔍 全面审查 · 待补清单（2026-08-14 新增）

> 对当前项目做全面审查后整理的遗留问题与缺口，按优先级排序。既有 Phase 4 测试项、可选增强（3.1/3.2）不在此重复。

### P0（初赛前，影响提交与合规）
- [x] **修正赛道归属不一致**：`GOAI-QA-ESSENTIALS.md` 顶部写「赛道一·新智基座 Agent Infra」；项目实际为**赛道三「软件研发全流程协同」**（PLAN.md / 简介 / PPT 均赛道三）。需统一为赛道三，避免评审混淆。（已改为赛道三）
- [x] **清理 MAF 残留演示**：`demo/README.md` + `OFFICIAL-MAF-GUIDANCE.md` + `maf_sequential_*.py` 仍全是 MAF 内容，违反「参赛不掺 MAF」决策。保留作选型对比论据可，但需在文件头标注「仅作选型对比参考，非参赛实现」，或移出参赛目录。（已在 4 个文件头加「仅作选型对比参考，非参赛实现」标注）
- [x] **补 `tests/` 单元测试**：`src/loop/` 下仅有 `test_context_with_api.py`，无正式 `tests/` 目录。初赛/复赛评审重「工程落地」，至少补齐 `state.py`（状态机正向/打回）与 `evaluation.py`（评分）确定性测试。（已建 `tests/`：`conftest.py` + `test_state.py` + `test_evaluation.py`，29 例全过）

### P1（演示稳定性，直接影响闭环演示）
- [x] **调大 `TASK_TIMEOUT`**：`src/loop/agentteams_loop.py` 仍是 `TASK_TIMEOUT=600`（10 分钟），但完整 6 Worker 闭环约 20-30 分钟 → 后台 `run.py` 会超时退出。建议改 3600。（已改 3600）
- [x] **新建只读监控脚本 `scripts/watch-pdca-closed-loop.py`**：memory 中计划新增用于捕获完整闭环，但实际不存在。正式演示用它只读现有房间，避免新建任务干扰。（已新建，只读观察、命中 RETROSPECT_DONE 即完成）
- [x] **修 `@@` 双 at 显示瑕疵**：`detect_milestones` 打印处 worker 已带 `@` 又加 `@`，轻微但不专业。（已修：worker 取纯用户名，`@{worker}` 输出单 at）

### P2（工程完善 → 大部分已移至 GAP-08~GAP-14）
- [x] **`manager.py::_verify` 接入确定性脚本**：`manager.py` 已移除，无需处理。
- [ ] **复赛 MCP 真实注册** → **GAP-15**
- [x] **`ci` MCP 无模板** → **GAP-12（已完成）**
- [ ] **Skill 引用完整性核对** → **GAP-11**

### P3（可选/后续）
- [x] **AuditLogger 结构化审计**（见 3.2，可选增强）：已实现 `src/loop/audit_logger.py`（纯标准库 JSON-Lines，无 structlog 依赖），提供 `log_decision/log_handoff/log_human_intervention/log_milestone/log_error` + `read_audit_log`；已接入 `agentteams_loop.py`（任务创建/等待、里程碑同步、mock 各阶段）。已建 `tests/test_audit_logger.py`（6 例）。当前 `agent_bus.py` 的 EventBus 提供内存事件历史，本模块为**落盘持久化**补充。
- [ ] **MatrixClient 独立模块**（见 3.1，可选优化）：Matrix 房间通信已由 `agentteams_client.py` 覆盖，独立模块价值低，暂缓。
- [ ] **沙箱阶段三**：接入 AgentScope Runtime 沙箱（agentscope-runtime + runtime-sandbox-mcp），复赛/决赛工程落地加分项。
- [x] **上下文工程 ctx-1~4 落地**：经核实**已实现且已接入**（TODO 此条为过期状态）——`context.py` 已含 `trim_context`/`compact_history`/`budget_allocate`/`offload_to_file` 四函数；`ContextManager` 已接入 `agentteams_loop.py`（主动路径）；`iterative_worker.py` 用 `ContextBudget`+`offload_to_file` 控制每步预算。
- [x] **`agents/<name>/` 子目录**：已补齐 6 个 `agents/<name>/IDENTITY.md` 身份索引卡（聚合/根因/修复/测试/发布/复盘），映射到权威来源 `AGENT-IDENTITY.md` + `src/agentteams/workers/*/SOUL.md` + `workers.yaml` + `skills/ASSIGNMENT-MATRIX.md`。

---

## UModel 统一数据模型接入（2026-08-15 新增）

> 引入阿里官方 UnifiedModel（alibaba/UnifiedModel）作为「统一数据模型」组件，把共享状态/知识库的自定义 schema 收敛为统一对象图。接入设计见 `design/UNIFIED-MODEL-INTEGRATION.md`。

- [x] 接入设计文档：`design/UNIFIED-MODEL-INTEGRATION.md`
- [x] 模型包 entity_set（9 个研发实体：task/defect/root_cause/patch/test_case/test_report/release/retrospective/worker）→ `src/agentteams/umodel/entity_set/`
- [x] 模型包 link（9 条关系，= PDCA 里程碑链对象图化）→ `src/agentteams/umodel/link/`
- [x] 模型包 storage（2 个 MinIO 存储绑定）→ `src/agentteams/umodel/storage/`
- [x] 模型包使用指南 → `src/agentteams/umodel/README.md`
- [x] 复用官方 `umodel-query`（全部 Worker）/ `umodel-rca`（RootCause）→ `skills/umodel-query/`、`skills/umodel-rca/`
- [x] 更新 `skills/ASSIGNMENT-MATRIX.md`（UModel Skill + MCP 分配）
- [x] 模型包完整性自检脚本 → `scripts/verify-umodel-model.py`（9 entity_set / 9 link / 2 storage，**PASS**）
- [ ] （复赛环境）`make quickstart` 起 UModel 服务 + 导入模型包，`umctl query run demo ".umodel with(kind='entity_set')"` 验证实体枚举
- [ ] （复赛环境）`umodel` MCP 注册到 Higress + 挂载 Worker（复用 `register-mcp.ps1`）
- [ ] 把 `shared/tasks/{id}/state.json`、`shared/knowledge/*.md` 写入按 `.umodel` 字段约束落地

---

## LoongSuite 推理轨迹观测接入（2026-08-15 新增）

> 引入阿里官方 **LoongSuite**（alibaba/loongsuite-python，GenAI OTel Distro）作为 Agent 推理轨迹观测组件，把 `OBSERVABILITY.md` 的"工程落地"从零变为可运行。接入设计见 `design/LOONGSUITE-INTEGRATION.md`。

- [x] 本地 Jaeger 验证链路跑通：`docker run jaegertracing/all-in-one`（OTLP 4318 + UI 16686）
- [x] 依赖安装：`agentscope==2.0.6` + `loongsuite-*==0.8.0` + `opentelemetry-exporter-otlp`
- [x] demo：`demo/loongsuite/agentscope_worker_demo.py`（模拟研发 Worker 根因定位，ReAct + 工具调用）
- [x] **实测捕获推理轨迹**：`invoke_agent worker-rootcause` / `react step` / `chat scripted-demo-worker` 三 span，带 `gen_ai.agent.name` 等语义属性，导出到本地 Jaeger
- [x] 可复用验证脚本：`scripts/verify-loongsuite-traces.py`（**PASS**）
- [x] 接入设计文档：`design/LOONGSUITE-INTEGRATION.md`（含两个坑：auto-instrumentation 不自动发现 agentscope 需手动 `instrument()`；bootstrap 破坏 `mcp.types` 绑定需手动补）
- [ ] （复赛）把 LoongSuite 落地到 AgentTeams：切 Worker runtime 到 qwenpaw（完整内置 loongsuite）或保持 copaw 手动注入；官方路径是设 `AGENTTEAMS_CMS_*` 接阿里云 CMS 2.0（`docs/cms-integration.md`）
- [ ] （复赛）给 6 Worker 的推理轨迹打 `task_id` 关联（复用官方 `task_trace.py` 的 task-trace correlation 逻辑），实现"跨 Agent 任务链路可审计"

---

## 文件清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `src/loop/agentteams_client.py` | ✅ 已完成 | AgentTeams 平台客户端（agt CLI 封装 + Matrix 协议 + Human 介入） |
| `src/loop/agentteams_loop.py` | ✅ 已完成 | AgentTeams 原生调度循环（delegated/orchestrated + 并行派单 + IterativeWorker） |
| `src/loop/agentteams/manager/SOUL.md` | ✅ 已完成 | PDCA Manager 编排指令 |
| `src/loop/__init__.py` | ✅ 已完成 | 懒加载 + 导出所有新模块 |
| `src/loop/state.py` | ✅ 已完成 | PDCA 闭环确定性状态机（无变更） |
| `src/loop/team.py` | 🗑️ 已移除 | 旧 Python dataclass 角色定义，与 Worker YAML 重复 |
| `src/loop/context.py` | ✅ 已完成 | 上下文工程（新增 DynamicBudgetAllocator + SemanticMemorySearch） |
| `src/loop/evaluation.py` | ✅ 已完成 | Agent 成员评价器（无变更） |
| `src/loop/iterative_worker.py` | ✅ 新创建 | 通用 IterativeWorker 基类 + RootCause/Tester/Releaser 预置子类 |
| `src/loop/agent_interface.py` | ✅ 新创建 | AgentInterface + WorkerContext/WorkerResult + 6 个 Worker 实现 |
| `src/loop/agent_bus.py` | ✅ 新创建 | AgentBus + EventBus |
| `src/loop/matrix_client.py` | ⬜ 可选 | Matrix 协议房间通信（独立客户端，当前功能已由 agentteams_client 覆盖） |
| `src/loop/audit_logger.py` | ✅ 新创建 | 结构化审计日志（落盘 JSON-Lines，已接入 agentteams_loop） |
| `src/loop/manager.py` | 🗑️ 已移除 | 旧 TeamManagerLoop（MAF 底座，已清理） |
| `src/loop/fixer_loop.py` | 🗑️ 已移除 | 旧 FixerLoop（MAF 底座，已清理） |
| `agents/<name>/IDENTITY.md` | ✅ 新创建 | 6 个 Agent 身份索引卡（映射 SOUL/workers.yaml/ASSIGNMENT-MATRIX） |
| `tests/` | ✅ 已完成 | `conftest.py` + `test_state.py` + `test_evaluation.py` + `test_audit_logger.py`（35 例） |

---

## 架构总览（迁移后）

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 3: AgentTeams 平台深度集成                              │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │ agentteams_client │  │ Matrix 协议   │  │ Human 介入   │   │
│  │ (agt CLI + API)  │  │ (房间通信)    │  │ (审批/反馈)  │   │
│  └────────┬─────────┘  └──────┬───────┘  └──────┬───────┘   │
│           │                   │                  │           │
├───────────┼───────────────────┼──────────────────┼───────────┤
│  Layer 2: 标准化 Agent 接口层  │                  │           │
│  ┌────────▼───────────────────▼──────────────────▼───────┐   │
│  │                 AgentTeamsLoop (调度引擎)              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │   │
│  │  │ AgentInterface│  │  AgentBus    │  │  EventBus  │  │   │
│  │  │ (6 Worker)   │  │  (pub/sub)   │  │  (事件驱动) │  │   │
│  │  └──────────────┘  └──────────────┘  └────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  Layer 1: 调度 Loop 核心升级                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ┌────────────────┐  ┌──────────────┐  ┌──────────┐ │   │
│  │  │ IterativeWorker │  │ 动态预算分配  │  │ 语义记忆  │ │   │
│  │  │ (Ralph 迭代)   │  │ (按阶段自适应) │  │ (TF-IDF)  │ │   │
│  │  └────────────────┘  └──────────────┘  └──────────┘ │   │
│  │  ┌────────────────┐  ┌──────────────┐               │   │
│  │  │ 异步并行派单    │  │ 三层记忆架构  │               │   │
│  │  │ (asyncio)      │  │ (短/中/长期)  │               │   │
│  │  └────────────────┘  └──────────────┘               │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  共享协议层（不变）                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ state.py │  │ team.py  │  │ eval.py  │  │ context  │   │
│  │ (状态机)  │  │ (角色)   │  │ (评价)   │  │ (工程)   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## 🔴 全面差距分析 · 待攻清单（2026-08-15 新增）

> 基于全项目代码、设计文档、TODO.md 的深入审查，按优先级排列。标记 "(新)" 为本次审查新发现的问题。

### P0 — 代码正确性（影响提交与初赛演示）

- [x] **GAP-01** 修复 `toolchains/` 导入路径错误 (新)：`code_scan_service.py` 和 `test_platform_service.py` 使用 `from src.agentteams.toolchains.core import` 绝对路径，非 `src/` 根目录运行时失败。已改为相对导入 `from .core import` 并删除 `sys.path.insert` hack。（已验证：`python -m src.agentteams.toolchains.*` 在包上下文可解析 `.core`）。⚠️ **另发现前置环境问题**：本机 agentscope 2.0.6 与 mcp 1.29.0 不兼容（`import mcp` 不再自动暴露 `mcp.types`），导致 `from agentscope.tool import FunctionTool` 即崩。此为本机依赖版本冲突，与导入路径无关；需 `pip install "mcp<1.0"` 或升级 agentscope 方可实际启动服务（复赛环境装好依赖即可）。
- [x] **GAP-02** 修复 `agentteams_loop.py` import 一致性问题 (新)：第 36-41 行用 `from loop.xxx import` 依赖 `run.py` 的 `sys.path.insert` 才能生效。已加自运行引导（`if __package__ is None` 时把 `src/` 加入 sys.path，对齐 `evaluation.py` 既有模式）。**已验证**：`python src/loop/agentteams_loop.py` 直接跑通 mock 全闭环自检。
- [x] **GAP-03** `_run_delegated()` 委托模式端到端验证 (新)：✅ 已完成。Mock 完整闭环（6/6 里程碑 + RETROSPECT_DONE + 审计 + 12 成绩单）+ 真实平台部分验证（3/6 里程碑 + workers.yaml apply 成功 + 10 容器 Running）。证据 `demo/e2e-log-20260815-final.txt`。真实平台全 6 里程碑受 LLM 网关延迟制约，记复赛。

### P1 — 演示稳定性（直接影响闭环演示）

- [x] **GAP-04** 委托模式无降级策略 (已实现+已验证)：`_run_delegated()` 顶部探活 + 降级。平台不可用（`ping()` False/异常）或 `create_task()` 提交失败 → 自动 fallback 到 mock 完整闭环 + 打印提示 + 审计 `degrade_to_mock`。✅ 新建 `tests/test_delegated_fallback.py` 3 例 PASS，全量 115 passed 无回归。
- [x] **GAP-05** 轮询机制脆弱 `detect_milestones` 无 task_id 过滤 (已实现+已验证)：`detect_milestones` 已带三层过滤（时间窗口/归属房间/task tag），`wait_for_task` 扫描时过滤。✅ 今日补 `tests/test_checkpoint.py`（latest_milestone_set 去重保留打回历史）9 例 PASS。
- [x] **GAP-06** `create_task` 不返回 AgentTeams 真实 task_id (已实现+已验证)：`create_task` 已用 `uuid.uuid4().hex[:12]` 生成唯一 task_id（client.py L419）+ 隐藏 `TASK_ID` tag。✅ 今日补唯一性契约测试 9 例 PASS。
- [x] **GAP-07** 超时后无恢复/断点续传 (已实现+已验证)：`TaskCheckpoint` 支持 checkpoint 落盘 + 超时恢复 + 断点续传（client.py L465-733）。✅ 今日补 round-trip/恢复测试 9 例 PASS。

### P2 — 工程完善（影响评审"工程落地 20%"）

- [ ] **GAP-08** 测试覆盖率严重不足：现有 **91 例 ALL PASS**（`python -m pytest tests/ -v` 2026-08-15 验证）。覆盖模块：state(8) / evaluation(21) / audit_logger(6) / checkpoint(9) / pdca_closure(4) / agent_bus(12) / agent_interface(8) / context_budget(13) / toolchains(10)。**初赛暂缺**（复赛补）：iterative_worker 数据结构、agentteams_loop 委托模式里程碑同步、context 子模块（memory_tiers / protocol / metrics / manager）。
- [ ] **GAP-09** 无集成测试：✅ **Mock 闭环集成测试已完成**（test_pdca_closure.py 4 例，覆盖 RETROSPECT 终态 / state.json 持久化 / 审计留痕 / 成绩单落盘）。仍缺：真实平台端到端 E2E（需 AgentTeams 运行中）、动态招人 E2E 场景。
- [ ] **GAP-10** `agentteams_client.py` 用 CLI 包装而非 REST API (新)：`AgtCLI` 通过 `docker exec agentteams-controller agt ...` 执行所有操作，脆弱且慢。应改为调用 Controller REST API 或 Matrix 原生协议。
- [x] **GAP-11** Skill 引用完整性核对：`workers.yaml` 引用 `knowledge-rag`/`evidence-log`/`git-operations`/`repo-context`/`code-search` 等 L1 基座 Skill，需确认 `skills/` 下均有对应 `SKILL.md`。（已用 `scripts/verify-skill-refs.py` 核对，5 个缺失 L1 基座已建空壳占位）
- [x] **GAP-12** `ci` MCP 模板缺失：✅ 已创建 `src/agentteams/mcp/mcp-ci.yaml`（5 个工具：trigger_pipeline/get_pipeline_status/get_build_log/approve_deploy/rollback_deploy），对齐 `mcp-code-scan.yaml` 格式。初赛无真实 CI 用 L1 shell 兜底，复赛替换为真实后端。
- [x] **GAP-13** 委托模式下观测组件"空转"：✅ 已改为延迟初始化。`ContextManager`/`SemanticMemorySearch`/`AgentMemory` 仅在 `mock=True` 时初始化，委托模式下置 `None`；`_print_summary`/`record_agent_iteration`/`consolidate_all_agent_memories` 均加 `None` 保护。验证：`python src/loop/agentteams_loop.py` Mock 自检闭环到 RETROSPECT，无委托路径 NPE。
- [x] **GAP-14** `reverse_gateway.py` 和 `workbuddy_client.py` 状态不明：✅ 已确认两文件仅被手工调试脚本（test_context_with_api.py / verify_reverse_api.py）引用，不被 `run.py`/`loop/__init__.py`/`agentteams_loop.py` 参赛主路径加载。两个文件顶部均已加 DEPRECATED 横幅，明确「废弃原因 / 引用范围 / 与主路径隔离关系」，保留作参考不移除。

### P3 — 架构优化（复赛/决赛加分项）

- [ ] **GAP-15** MCP 真实注册到 Higress：`mcp-code-scan.yaml`/`mcp-test-platform.yaml` 模板已就绪，需真实 API Key 注册 + 授权 Worker。
- [ ] **GAP-16** UModel 服务部署 + 模型包导入：模型包已备好，但 UModel 服务未实际运行，Worker 的 `umodel-query`/`umodel-rca` Skill 无法调用。
- [ ] **GAP-17** 方案 B 两级调度（Manager→Team Leader→Worker）未实现：Team + Leader CRD 已创建，但仅验证了兼容性。真正的两级调度链路未实现。
- [ ] **GAP-18** 沙箱阶段三：AgentScope Runtime 沙箱接入（agentscope-runtime + runtime-sandbox-mcp）。
- [ ] **GAP-19** Model 路由：Worker 应通过 Higress AI Gateway 统一路由模型，而非持有直接 API Key。
- [ ] **GAP-20** 无 CI/CD：缺自动化构建、测试、部署流水线。
- [ ] **GAP-21** Python 客户端未容器化：`run.py` 和 `loop/` 模块未打包为 Docker 镜像，依赖本地 Python 环境。

### P4 — 文档与体验（随手可修）

- [ ] **GAP-22** `web_dashboard.py` 和 `dashboard.py` 功能简陋 (新)：仅 Rich 终端渲染 + 简单 Web 页面，无实时推送、无历史回放。
- [x] **GAP-23** 旧 TODO 清理：✅ 本次同步完成。① Phase 4 (4.1/4.2/4.3)：9 个已有测试文件全部打勾并标注"N 例 PASS"，3 个未完成测试明确标注「复赛补 → GAP-08/09」；② 顶部「🔥 初赛前必修」GAP-05/06/07/13/14/08①②/23 全部打勾补验证证据；③ 底部全面审查清单：GAP-08 测试数量从 46→91 例并列出覆盖模块，GAP-09 标注「Mock 闭环集成已完成」，GAP-13/14/23 均打勾并补代码改动+验证证据；④ 今日冲刺清单 3.3 GAP-23 打勾。