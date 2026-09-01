# AgentTeams 软件研发全流程协同系统 · TODO（唯一真相源）

> 最近整理：2026-09-01（稳定性评审 + 全文档重整）
> 使用约定：
> 1. 顶部「📋 待办清单」是当前唯一工作入口，按优先级分组；每项附「第一步」。
> 2. 做完一项：`[ ]`→`[x]` 补验证证据，并移入底部「🗄 已完成归档」对应小节。
> 3. GAP 编号连续递增（下一个：GAP-38），不复用旧编号。
> 测试基线：`demo\.venv\Scripts\python.exe -m pytest tests/ -q` → **387 passed + 12 skipped**（2026-08-31）。

---

## 🧭 产品化路线（2026-09-01 定调）

> 方向：**先自用 → 优化组件并拓展开源 → 以后再评估商业化**。下方待办按此路线组织。
> 定位收窄：软件研发垂类的 AI 工作伙伴，不做通用全能方向。

### 阶段一 · 稳定自用（当前）
- 目标：在自用机上长跑接受真实任务、交付真实产物。
- 对应：P0 + P1 全部（GAP-24/28/30、GAP-26 收尾、GAP-31/32/33/34/27）。
- 自用场景降权项：多用户、Dashboard 增强（GAP-22）、容器化分发（GAP-21）。

### 阶段二 · 组件化与开源拓展
- 目标：把与 AgentTeams 解耦的零依赖组件抽成独立包/仓库，开源前完成清理。
- 候选组件（多为纯标准库 + 完整测试）：
  - **门禁家族**（最具传播力）：evidence-check / injection-scan / review-gate / acceptance-gate / stall-detection（fail-closed，133 例测试）
  - **稳定运行**：watchdog（队列/重试/卡死检测）+ checkpoint/delegation 续跑模式（16 例）
  - **记忆**：AgentMemoryRegistry 三段式契约（10 例）
  - **协同**：dispatch-contract 声明式派发契约（27 例）
  - **交付/治理**：doc-gen（Word/PDF）/ evaluation（成绩单+治理命令）
- 开源前置清理：
  - [ ] **GAP-37** 剔除逆向资产：`workbuddy_client.py` / `reverse_gateway.py`（违反第三方条款，开源红线，先于 GAP-36 的清退）。
  - [ ] 参赛材料移出公开仓库（提交包 / 初赛 PPT / 500字简介 / demo 证据），改放私有目录。
  - [ ] LICENSE（建议 Apache-2.0）+ 英文 README + 最小可跑示例 + CI 绿。
  - [ ] 抽包时保持核心零厂商绑定（不硬编码 AgentTeams/DeepSeek），给商业化留许可空间。

### 阶段三 · 商业化（后评估）
- 前提：阶段二组件获社区验证与反馈后再启动。
- 候选方向：研发闭环垂类方案 / AgentTeams 生态企业落地件。
- 红线：不依赖逆向接口、许可保持宽松、核心不硬绑厂商。

---

## 📋 待办清单

### 🔴 P0 · 稳定底线（直接影响"可复现 / 不丢数据"）

- [ ] **GAP-24** 核心改动未提交 + 提交包过期 → **第一步**：`git add -A` + `git commit`，跑打包脚本重生成提交包。
  - ⚠️ 2026-09-01 实测 `git status`：**40+ 文件未提交**，含 `workers.yaml` / `agentteams_client.py` / `agentteams_loop.py` / 多个 `SOUL.md` / skill 清单 / `.gitignore`。「能跑的系统」主要存在于本地工作区而非版本库，误操作即丢失。`提交包/` 仍是 8.16 初赛版。
- [ ] **GAP-28** 依赖无锁定，环境不可复现（新）→ **第一步**：从 `demo\.venv` 导出 `requirements.lock.txt`（pip freeze），CI 改用 lock 安装。
  - 现状：`requirements.txt` 全 `>=` 开区间；已实测 agentscope 2.0.6 与 mcp 1.29.0 冲突（GAP-01 记录）；LoongSuite 需 `agentscope==2.0.6 + loongsuite==0.8.0` 但未写入依赖清单。"必须用 demo\.venv 跑"即环境漂移症状。
- [x] **GAP-29** 无配置模板，环境变量散落（新）→ **已完成（2026-09-01）**。
  - 完成内容：建根目录 `.env.example` 统一模板（4 组：平台连接 / Loop 行为 / 部署-LLM / WorkBuddy 注释）。
  - 新增 `src/loop/config.py`（纯 stdlib `.env` 加载器，幂等、不覆盖真实环境变量），`agentteams_client.py` / `agentteams_loop.py` / `run.py` 入口自动读取。
  - `reinstall-agentteams.ps1` 改从 `.env` 读取（含 `Get-Config` 函数），`AGENTTEAMS_ADMIN_PASSWORD` 为空时自动生成并回写 `.env`（去掉硬编码 `AgentTeams2026!`）；`entry-cli.ps1` 优先读 `.env`，controller 容器兜底。
  - 测试：`tests/test_config.py` 11 例（解析 + 注入 + 幂等 + 不覆盖）；`test_pdca_closure` / `test_delegated_fallback` / `test_delegated_resume` 无回归。
- [ ] **GAP-30** `AgtCLI._http_request` shell 拼接注入风险（新）→ **第一步**：去掉 `bash -c` 字符串拼接，JSON 走 `curl -d @-` stdin 传入，token 走 `-e` 环境变量。
  - 现状（`agentteams_client.py` L84-119）：JSON 直接塞 `-d '{data_str}'` 交给 `bash -c`，数据含单引号即破坏命令，恶意内容可构成注入；`Authorization` token 暴露在命令行（`ps` 可见）。

### 🟠 P1 · 长时间运行可靠性

- [ ] **GAP-26 收尾** 守护进程托管化 → **第一步**：Windows 服务（nssm）托管 watchdog + 开机自启。
  - 已有：`src/loop/watchdog.py`（12 例测试通过：队列/重试/超时续跑/STALE 检测/PID）。仍缺：开机自启托管、卡死告警后可选自动重启（现 detect-only）、`--register` 批量导入。
- [ ] **GAP-31** 里程碑检测结构化（新）→ **第一步**：约定 Worker 发结构化里程碑消息（msgtype=m.notice + JSON body），客户端优先解析结构、子串扫描降级为兜底。
  - 现状：`detect_milestones` 靠 `if m_name in msg["content"]` 识别闭环进度——复盘/引用消息提及里程碑词即误触发，LLM 格式漂移（曾出现全角冒号被拒）则漏检。系统状态感知建立在 LLM 自由文本上，长跑最易"悄悄跑偏"。补误触发负例测试。
- [ ] **GAP-32** 引入 logging + 日志轮转（新）→ **第一步**：`src/loop` 以 `logging` 替换 `print`（保留 CLI 展示层），审计/告警日志按大小或日期切分。
  - 现状：`src/loop` 全模块 0 处 logging；`audit.jsonl` / `alerts.log` / iteration_log 只追加不清理，长跑无限膨胀。
- [ ] **GAP-33** Matrix 客户端异步化 + 轮询退避（新）→ **第一步**：`agentteams_matrix.py` 从同步 `urllib` 换 `httpx` 异步。
  - 现状：阻塞式 urllib 跑在 asyncio 轮询循环里，每 10s 阻塞事件循环；每房间抓 100 条、无分页无退避，房间越多轮询越重，性能单调劣化。目标：仅扫绑定房间 + `since` 增量同步。
- [ ] **GAP-34** 降级策略增加"显式失败模式"（新）→ **第一步**：`run.py` 加 `--no-mock-fallback`（或 `MOCK_FALLBACK=off`），生产语义下平台失败即非零退出 + 告警。
  - 现状：平台不可用自动切 mock（GAP-04），对演示是救命，对生产是"失败被静默转化为假装成功"，只能翻审计 `degrade_to_mock` 才察觉。
- [ ] **GAP-27** 产物交付链路未闭环 → **第一步**：任务闭环后自动收集 `shared/tasks/{id}/` 产物，生成 deliverable 清单（md + json），接入 `wait_for_task` 完成分支。
  - 现状：MBTI 网站是 `DeterministicSiteBuilder` 演示产物，真实 Worker 产物无「自动收集 → 归档 → 交付清单」流程，"直接交付产物"目标缺最后一环。

### 🟡 P2 · 质量门禁与验证体系

- [ ] **GAP-35** 真实平台冒烟测试自动化（新）→ **第一步**：把 `scripts/verify-delegated-e2e.py` 转为带 `@pytest.mark.integration` 的测试（平台未起自动 skip、起着自动跑）。
  - 现状：387 例测试几乎全是确定性 mock 契约，真实平台路径只有人工跑出的审计证据（26 个 `RETROSPECT_DONE`），**测试全绿 ≠ 系统能跑**，中间隔着未自动化验证的 docker/Matrix/LLM 链路。
- [ ] **GAP-36** 静态质量门禁 + 废弃文件清退（新）→ **第一步**：加 ruff（+ 可选 mypy）配置并接一个 CI job。
  - 同步清退：`reverse_gateway.py` / `workbuddy_client.py`（仅手工调试脚本引用，已挂 DEPRECATED 横幅）删除或移出主树；收敛 mock 路径"静默吞异常"的宽 try/except（至少记日志）。
- [ ] **GAP-08/09** 测试覆盖补齐（初赛遗留，复赛档期）：`agentteams_loop` 委托模式里程碑同步、`context` 子模块（memory_tiers/protocol/metrics/manager）、真实平台端到端（→ 并入 GAP-35）。

### 🔵 P3 · 平台能力落地（既有复赛项，逐一推进）

- [ ] **GAP-10** CLI→REST API 改造：`AgtCLI` 的 `docker exec` 为临时方案 → 替换为 Controller `http://127.0.0.1:8080/api/v1/*`。⚠️ 2026-09-01 复查：现"HTTP fallback"实际仍是 `docker exec bash -c "curl ..."`，未脱离容器单点依赖。
- [ ] **F3 / GAP-15** code-scan/test-platform 后端启动 + MCP 真实注册 Higress（`mcp-code-scan.yaml` / `mcp-test-platform.yaml` 已就绪）。
- [ ] **GAP-16** UModel 服务部署：`make quickstart` 起服务 + 导入模型包 + `umodel` MCP 注册 Higress（模型包已备好：9 entity_set / 9 link / 2 storage，自检 PASS）。
- [ ] **GAP-17** 方案 B 两级调度（Manager→Team Leader→Worker）真正实现（当前仅验证兼容性）。
- [ ] **GAP-18** 沙箱阶段三：AgentScope Runtime 沙箱（agentscope-runtime + runtime-sandbox-mcp）。
- [ ] **GAP-19** Model 路由：Worker 统一走 Higress AI Gateway，不持直接 API Key。
- [ ] **GAP-20** CI/CD：自动化构建/测试/部署流水线（现有 `e2e-tests.yml` 只跑测试、且现装无锁依赖）。
- [ ] **GAP-21** Python 客户端容器化：`run.py` + `loop/` 打包 Docker 镜像（当前依赖本地 Python + Docker Desktop + Windows 专用 `.bat`/`.ps1`，Linux 无法等价运行）。
- [ ] **GAP-22** Dashboard 增强（实时推送 / 历史回放）。
- [ ] **LoongSuite 落地 AgentTeams**：切 Worker runtime 到 qwenpaw 或 copaw 手动注入（`AGENTTEAMS_CMS_*` 接阿里云 CMS 2.0）+ 给 Worker 推理轨迹打 `task_id` 关联（复用官方 `task_trace.py`）。

### 🟣 进行中分支（等待外部输入）

**飞书 MCP 接入**（胶水层 2026-08-31 已完成，等真实凭据；设计 `design/LARK-MCP-INTEGRATION.md`）
- [ ] **L-1** 用户创建飞书企业自建应用 → 回填 App ID / App Secret（开 im/docx/bitable/task 权限 + 发布版本）。
- [ ] **L-2** `.\scripts\add-feishu-mcp.ps1 -AppId "cli_xxx" -AppSecret "yyy"` 真实注册（lark-mcp SSE + Higress）。
- [ ] **L-3** `docker cp` + `agt apply` 同步 `workers.yaml`（leader/aggregator/rootcause 已挂 feishu）。
- [ ] **L-4** `mcporter list feishu --schema` 验证工具列表。
- [ ] **L-5** 真实调用冒烟（leader 发群消息 / aggregator 读文档）。
- [ ] **L-6**（可选）改用飞书托管 MCP。

**Coordinator 派发契约层**（代码/测试就绪：27 例新测试 + 37 例回归全绿，未部署；设计 `skills/dispatch-contract/`）
- [ ] **C-6** 确认部署路径（默认建议 mock 先行）。
- [ ] **C-7** Mock 验证全链路（validate-brief → 派发 → validate-review，哨兵 fail-closed）。
- [ ] **C-8** 部署到平台（workers.yaml + team-rnd.yaml apply，11 Worker configured）。
- [ ] **C-9** 真实平台验证（coordinator 收派发请求 → 契约 → Leader 执行 → 复审包回传）。
- [ ] **C-10~C-14**（后续）：tester 复审包协议 / 并行切片派发 / 成本维度追踪 / 运行时身份校验 / 角色-模型差异化映射。

---

## 🗄 已完成归档（2026-09-01 整理压缩）

### 2026-08-31 · ARIS 高价值资产迁移（7 批次全部完成）
- 迁入 6 项资产：evidence-check / injection-scan / stall-detection / review-gate / evidence-integrity / acceptance-gate（`src/loop/` + `skills/` + 133 例新测试）。
- 批次 7 集成：`workers.yaml` 挂载 + `agentteams_loop.py` 三处增量接入（全 try/except 不阻断）→ 全量 **387 passed + 12 skipped** 零回归；`verify-skill-refs.py` 29 skill 全 PASS。
- **GAP-25** Loop 层断点续传：`_run_delegated` 循环接续轮询（`MAX_DELEGATE_ROUNDS=6` 可 env 覆盖）+ `delegation.json` 原子写持久化 + `run.py --task-id` 跨进程续跑。验证 `test_delegated_resume.py` 4 例。
- **GAP-26 主体** `src/loop/watchdog.py`（队列/原子写/重试/超时续跑/STALE detect-only/PID）。验证 `test_watchdog.py` 12 例。收尾项见待办。

### 2026-08-16 · 二次重构：一套完整班子 + 固定 Leader
- `AgentMemoryRegistry` + `skills/agent-memory`；`workers.yaml` 重写 9 Worker（后扩至 11）；`AgentBus` request/reply + `skills/team-comm`；`state.py` 泛化（`executor_for` / `stage_participants`）；SITE_READY/BACKEND_READY 里程碑。
- 推翻此前「HR 双模式」方案（`TEAM-ECOSYSTEM-RESTRUCTURE.md` 已标 DEPRECATED，真相源 = `design/TEAM-REFACTOR-SINGLE-BANCHANG.md`）。
- 回归：177 passed（当时）→ 后续累积至 387。

### 2026-08-15~16 · 初赛冲刺（全部完成）
- **GAP-03** 委托模式端到端：Mock 6/6 里程碑 + 真实平台 3/6 里程碑 + workers.yaml MCP 格式修复（v1.1.1 Breaking Change）。证据 `demo/e2e-log-20260815-final.txt`。
- **GAP-04** 委托降级（探活 + fallback mock，`test_delegated_fallback.py` 3 例）；**GAP-05** 里程碑三层过滤；**GAP-06** task_id 唯一化；**GAP-07** checkpoint 断点（`test_checkpoint.py` 9 例）。
- **GAP-11** Skill 引用核对（`verify-skill-refs.py`）；**GAP-12** `mcp-ci.yaml`；**GAP-13** 观测组件延迟初始化；**GAP-14** 废弃文件加横幅；**GAP-23** TODO 清理。
- 动态团队 `test_e2e_dynamic_hiring.py` 15 例；MBTI 建站验证 HTTP 200（`demo/mbti-site-e2e-*`）；绩效评价反哺治理命令。
- 真实平台闭环留痕：audit.jsonl 确认 26 个完整 `RETROSPECT_DONE`。

### 2026-08-15 · 组件落地
- **UModel** 模型包（9 entity_set + 9 link + 2 storage）+ `verify-umodel-model.py` PASS + `umodel-query`/`umodel-rca` skill 挂载。服务部署 → 见待办 GAP-16。
- **LoongSuite** 本地 Jaeger 验证链路跑通（`verify-loongsuite-traces.py` PASS，三 span 推理轨迹）+ 接入设计文档。落地 AgentTeams → 见待办。
- **Team + Leader**：`team-rnd.yaml` Active（1 Leader + 8 Worker），`agt get teams` 验证 teamRoomID/leaderDMRoomID。
- 迁移 Phase 1-3：IterativeWorker / 并行派单 / 动态预算 / 语义记忆 / AgentInterface / AgentBus+EventBus / Human 介入 / AuditLogger（35+ 例测试）。

### GAP-01~07/11~14/23/25 处理结果速查

| GAP | 结果 | 证据 |
|-----|------|------|
| 01 | ✅ 修复导入路径（`.core` 相对导入） | 依赖冲突遗留 → GAP-28 |
| 02 | ✅ import 自运行引导 | `python src/loop/agentteams_loop.py` 自检通过 |
| 03 | ✅ 委托模式端到端 | `demo/e2e-log-20260815-final.txt` |
| 04 | ✅ 降级策略 | `test_delegated_fallback.py`；生产语义 → GAP-34 |
| 05 | ✅ 三层过滤 | `test_checkpoint.py`；结构化 → GAP-31 |
| 06 | ✅ task_id 唯一 | `test_checkpoint.py` |
| 07 | ✅ 断点续传 | `test_checkpoint.py` |
| 11 | ✅ Skill 引用核对 | `verify-skill-refs.py` |
| 12 | ✅ ci MCP 模板 | `src/agentteams/mcp/mcp-ci.yaml` |
| 13 | ✅ 观测组件延迟初始化 | mock 自检闭环通过 |
| 14 | ✅ 废弃文件横幅 | 清退 → GAP-36 |
| 23 | ✅ TODO 清理 | 本次 2026-09-01 再次重整 |
| 25 | ✅ Loop 断点续传 | `test_delegated_resume.py` |
| 26 | 🟡 主体完成 | 收尾项见待办 |

### 迁移完成摘要（三层架构）
- Layer 1：`iterative_worker.py` / `_dispatch_parallel` / `DynamicBudgetAllocator` / `SemanticMemorySearch`
- Layer 2：`agent_interface.py`（6 Worker）/ `agent_bus.py`（AgentBus + EventBus）
- Layer 3：`agentteams_client.py`（agt CLI + Matrix + Human 介入）/ `audit_logger.py`
- 文件状态：`manager.py` / `fixer_loop.py` / `team.py` 已移除；`matrix_client.py` 评估后不建（功能已并入）。

---

## 架构总览（迁移后）

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 3: AgentTeams 平台深度集成                              │
│  agentteams_client (agt CLI + API) / Matrix 房间通信 / Human 介入 │
├──────────────────────────────────────────────────────────────┤
│  Layer 2: 标准化 Agent 接口层                                  │
│  AgentTeamsLoop（客户端/观测层）+ AgentInterface + AgentBus/EventBus │
├──────────────────────────────────────────────────────────────┤
│  Layer 1: 调度 Loop 核心                                       │
│  IterativeWorker(Ralph) / 动态预算 / 语义记忆 / 并行派单 / 三层记忆 │
├──────────────────────────────────────────────────────────────┤
│  共享协议层：state.py(状态机) / evaluation(评价) / context(工程)   │
├──────────────────────────────────────────────────────────────┤
│  稳定运行件：watchdog / checkpoint+delegation / audit / gates    │
└──────────────────────────────────────────────────────────────┘
```
