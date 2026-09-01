# 团队生态重构 + HR 招聘经理（方案 C 完整设计 + TODO）

> ⚠️ **DEPRECATED（2026-08-16）**：本方案（HR 双模式动态团队）已被用户**推翻**。
> 用户明确要求「一套完整班子 + 固定 Leader 编排」，不再有「修复/搭建」双模式割裂。
> **当前真相源**：`design/TEAM-REFACTOR-SINGLE-BANCHANG.md`（一套班子 + Leader）。
> 本文件仅作历史参考（评审叙事、角色对照、场景推演仍可引用），不再作为实施依据。

> GOAI · 赛道三「软件研发全流程协同」· 协同基点 AgentTeams
> 目标：把当前「固定 6 Worker + 单级 PDCA 修复流水线」重构为「**HR 按项目拉人进群 + 双模式团队（修复/搭建）**」，修复团队生态的结构性缺陷与差异。
> 背景：初赛已提交（2026-08-16），本方案面向 **复赛（8.25–9.3 交代码包 + Demo）**。
> 场景驱动：以「带服务器的网站搭建（静态为主 + 少量 POST）」为验收场景（见 §4）。
> 日期：2026-08-16

---

## 0. 结论先行

> 当前 6 角色是**「BugFix 修复流水线」角色，不是「从零搭建」角色**。把「搭建带服务器的网站」扔给现有 `rnd-team` 会暴露 4 类问题：
> ① 无产品/架构设计环节（greenfield 无处做 RCA）；② 无后端/部署/环境角色接 POST 服务器；③ 验证端测不了"真实可访问"；④ 强制走发布/复盘对搭建是负担。
>
> **重构方案 = 引入 HR（招聘经理）作为「团队生态编排者」**，它像真实公司 HR 一样：识别项目类型 → 为项目「拉人进群组」组建合适团队 → 项目结束裁员归档。让团队从「固定 6 人」变成「**按项目动态组建**」——这正是本作品的核心创新点（"AI 公司式动态团队"）的真实落地。

---

## 一、当前团队生态诊断（缺陷与差异清单）

基于 `workers.yaml` / `manager/SOUL.md` / `team-rnd.yaml` / `TOOLCHAIN-PRODUCTION-PLAN.md` / `TODO.md` 的代码级审查：

### 缺陷 D-1：角色模型只覆盖「修复」任务，不覆盖「搭建」任务（最严重）
- 6 个角色 soul 全部围绕「已有代码库的缺陷定位/修复/验证/发布」。
- `rootcause`（根因定位员）对「从零搭建」无对象可定位；`aggregator`（缺陷聚合员）无「产品/设计」能力。
- **缺**：产品/架构设计、后端/服务器、部署/环境三类能力。
- 佐证：`agentteams_loop.py::_run_mock` 的 `mock_outputs` 已硬编码「index.html / style.css / app.js」建站产物，说明团队已隐约想支持建站，但**没有真实能力**。

### 缺陷 D-2：`manager/SOUL.md` 把调度逻辑写死为「6 阶段 PDCA 修复流水线」
- Manager 只知道 6 个修复角色、只认一套里程碑词、只按「聚合→根因→修复→测试→发布→复盘」顺序派单。
- **不知道**：任务类型识别（修复 vs 搭建）、动态招人/裁员、按项目组建团队、跳过发布/复盘。
- → Manager 是生态重构的第一障碍，必须改造为「任务类型感知 + 动态路由」。

### 差异 D-3：Worker 定义双轨不一致
- 真相源 `workers.yaml`（简洁内联 soul/agents/skills/mcpServers）。
- 另有 `workers/<name>/SOUL.md`（更详细的 Ralph 迭代版：含记忆沉淀、五大原则、迭代循环）。
- **两个文件内容不一致**（`workers.yaml` 的 soul 与 `SOUL.md` 详略差异大），评审或部署时易混淆、易不同步。
- → 需明确「单真相源」策略。

### 缺陷 D-4：工具链大量「空壳 / 未启动」（TOOLCHAIN-PRODUCTION-PLAN 已列）
- `git-operations`/`code-search`/`repo-context`/`knowledge-rag`/`evidence-log` 5 个 L1 Skill 是「初赛占位空壳」。
- `code-scan`/`test-platform`/`ci` MCP 后端未启动、未注册 Higress（GAP-15/GAP-20）。
- → 搭建场景的「真实可访问验证」「git 提交」「部署」依赖这些工具，必须补齐或明确兜底。

### 缺陷 D-5：`rnd-team` 固定 6 Worker，无「按项目拉人进群」机制
- `team-rnd.yaml` 写死 1 Leader + 6 Worker，是**单一固定团队**。
- 没有「项目 → 建群 → 选人加入 → 结束拆群」的生命周期。
- 动态招聘只有 `tests/test_e2e_dynamic_hiring.py`（8 例）的**治理逻辑**验证，**没有真实 HR Worker / Team 生命周期落地**。

### 缺陷 D-6：搭建场景「验证不到真实可访问」+ 无部署
- Tester 挂 `test-platform`（占位未启动），只能逻辑断言，验不了「站点真能跑、POST 真能通」。
- 无 Deployer/环境搭建角色，站点搭完没有「部署到可访问地址」步骤。

---

## 二、目标架构：HR 编排的「双模式动态团队」

```
用户任务
   │
   ▼
Manager（改造：任务类型识别）
   │  判断：修复任务 OR 搭建任务
   ▼
HR（招聘经理）← 新增核心角色，团队生态编排者
   │  ① 解析任务 → 识别需要的角色/skill 组合
   │  ② 为「本项目」组建 Team（拉人进群组）
   │  ③ 指派 Team Leader 协调
   │  ④ 项目结束 → 裁员归档（经验沉淀）
   ▼
Project Team（按项目动态组建）
   ├─ 修复模式：Aggregator + RootCause + Fixer + Tester（+ 事件 Releaser/Retrospector）
   ├─ 搭建模式：Architect + FrontendFixer + BackendFixer + Deployer + Tester
   └─ 通用：Team Leader 协调
```

### 2.1 双模式团队（对照 MetaGPT/ChatDev/AgentScope）

| 模式 | 适用任务 | 角色流水线 | 参考 |
|------|---------|-----------|------|
| **修复模式**（默认） | 已有代码库的缺陷修复 | Aggregator → RootCause → Fixer → Tester →（事件）Releaser/Retrospector | 现有 6 角色，保留 |
| **搭建模式** | 从零建站/带服务器 | Architect(设计) → FrontendFixer+BackendFixer(编码) → Tester(真实运行验证) → Deployer(部署) | MetaGPT 五角色 + 前后端拆分 + 部署 |

> 依据（网上学习）：MetaGPT「Code = SOP(Team)」用结构化产物交接（PRD/design/task/code）防幻觉漂移；ChatDev「虚拟软件公司」有独立 Reviewer 环节；AgentScope 官方推荐「Supervisor + 专业子Agent」分工。三者共同点 = **按任务类型选角色、角色间结构化契约交接**。

### 2.2 HR（招聘经理）职责边界

对应真实团队 **HRBP + 项目组建者**，**不写代码**，只做「团队生态编排」：

1. **任务解析**：读任务 spec，识别需要的角色/skill（`aggregator` 需要 issue-parsing、搭建需要 `architect`/`backend` 等）。
2. **组建团队**：为项目「拉人进群」——创建/复用 Worker CR + 建 Team，把选定 Worker 拉进本项目群组。
3. **分配 Leader**：指定 Team Leader 协调。
4. **动态招聘/裁员**：按需 `hire_worker`（新增 backend/deployer 等）/ `fire_worker`（项目结束回收）。
5. **经验归档**：项目结束把成员记忆沉淀到知识库，裁员不丢组织记忆。

HR 落成 **AgentTeams Worker CR**（`src/agentteams/hr.yaml`），挂 `team-management` / `project-management` / `dynamic-hiring` skills。

---

## 三、可执行 TODO（按依赖顺序）

> 每项做完打勾。第 1-2 项是纯文档（评审叙事），3-6 是代码落地。

### 🔥 阶段 A：文档与设计（先固化方案，评审叙事）

- [ ] **A1** 本文件（TEAM-ECOSYSTEM-RESTRUCTURE.md）= 方案设计 + 场景推演 + 角色对照表 → ✅ 本文档即交付
- [ ] **A2** 更新 `AGENT-IDENTITY.md`：新增 **HR（招聘经理）** 身份卡（含 soul/职责/动态字段），并标注「6 角色 = 默认模板，非重点；动态编排 = 创新点」
- [ ] **A3** 更新 `skills/ASSIGNMENT-MATRIX.md`：补 HR 的 skill 分配（`team-management`/`project-management`/`dynamic-hiring`）

### 🔧 阶段 B：Manager 重构（解除写死，支持任务类型路由）

- [ ] **B1** 改造 `manager/SOUL.md`：新增「任务类型识别」章节（修复 vs 搭建判断规则）+ 双模式派单准则 + 「动态路由到 HR / 对应 Worker」
- [ ] **B2** `src/loop/agentteams_client.py`：确认 `create_task` 支持把任务**同时发给 HR**（新增 HR 房间/DM 派单路径），或由 Manager 内部先经 HR 解析

### 🧩 阶段 C：新增 HR + 搭建类角色模板（核心）

- [ ] **C1** 新建 `src/agentteams/hr.yaml`：HR Worker CR（soul=招聘经理，skills=team-management/project-management/dynamic-hiring，mcpServers 视需）
- [ ] **C2** 新建搭建类角色 Worker CR（模板）：
  - `architect.yaml`（架构设计：页面架构 + API 路由 + 数据模型，输出 design.md）
  - `backend.yaml`（后端：POST 接口 + 数据存储 + 启动脚本）
  - `deployer.yaml`（部署：起服务到可访问地址 + 可回滚）
- [ ] **C3** 为搭建类角色建 `workers/<name>/SOUL.md`（对齐现有 Ralph 格式，含记忆沉淀）
- [ ] **C4** 建 `skills/` 新 Skill：`site-design`（Architect）、`backend-impl`（Backend）、`deploy-runtime`（Deployer）——非空壳，含可执行 scripts（如起服务/健康检查脚本）

### 🔄 阶段 D：Team 生命周期 = 「按项目拉人进群」

- [ ] **D1** 新增「项目级 Team 生成」机制：HR 按任务动态生成 Team CR（不再是固定 `rnd-team`），`src/agentteams/` 加 `team-template.yaml` + 生成脚本 `scripts/team-by-project.ps1`
- [ ] **D2** 更新 `team-rnd.yaml` 为「修复模式默认模板」，明确搭建模式走 HR 动态组队
- [ ] **D3** 复用 `tests/test_e2e_dynamic_hiring.py`：扩展断言「HR 组建 Team → 拉入 backend/deployer → 结束裁员归档」的完整生命周期

### 🧪 阶段 E：搭建场景端到端验证（验收场景）

- [ ] **E1** 增强 `scripts/verify-team-builds-website.py` 或新建 `verify-builds-post-site.py`：让团队产出**带 POST 接口**的网站（静态页 + `POST /api/submit` + 数据落地）
- [ ] **E2** 真实运行验证：起服务 → curl 静态页 200 + POST 真实请求返回 + 数据入库断言
- [ ] **E3** 补 Tester 的「真实运行验证」能力：给 tester 挂 `deploy-runtime` skill 或起服务验证脚本（解决 D-6）

### 🛠 阶段 F：修复既有生态缺陷（对齐 TOOLCHAIN-PRODUCTION-PLAN）

- [ ] **F1** 统一 Worker 定义单源：明确 `workers.yaml` = 唯一真相源，`workers/<name>/SOUL.md` = 从属详细说明（补注释指向），或反向（SOUL.md 为源 + workers.yaml 引用）——**二选一，消除 D-3**
- [ ] **F2** 补齐 5 个 L1 Skill 空壳（git-operations/code-search/repo-context/knowledge-rag/evidence-log）为真实内容（TOOLCHAIN 窗口 A）
- [ ] **F3** 启动 code-scan/test-platform 后端 + 注册 Higress（TOOLCHAIN 窗口 B/C，GAP-15）——搭建场景真实验证的前置

### ✅ 阶段 G：回归与收尾

- [ ] **G1** 全量回归：`python -m pytest tests/ -q`（基线 156 passed + 12 skipped，必须用 `demo\.venv`）
- [ ] **G2** 更新 TODO.md（见 §五）
- [ ] **G3** 更新 README / 提交包：突出「HR 动态组建团队」+「双模式任务」创新点

---

## 四、验收场景：带 POST 的网站搭建（问题 → 方案对照）

| 场景问题 | 现状会怎样 | 重构后怎样 |
|---------|-----------|-----------|
| 从零搭建无设计环节 | RootCause 空转做无意义 RCA | Architect 产 `design.md`（页面架构 + POST API + 数据模型） |
| POST 服务器无人接 | 全能 Fixer 超载 | Backend 角色专门写 `POST /api/submit` + 数据存储 |
| 验证不到真实可访问 | Tester 只能逻辑断言 | Tester + Deployer 起真实服务，curl 静态 200 + POST 通 + 数据落库 |
| 发布/复盘是负担 | 强制走 RELEASE_OK/RETROSPECT_DONE | 搭建模式按需触发 Deployer 部署，复盘可选 |

**演示叙事**：用户丢「搭一个带 POST 的官网」→ Manager 识别为搭建 → HR 拉起 `architect + frontend + backend + tester + deployer` 组成项目团队 → 产出可访问的站点（静态页 + 真 POST）→ 项目结束 HR 裁员归档经验 → 下一个项目重新组队。

---

## 五、TODO.md 同步

把上述 A-G 阶段条目**追加到 `TODO.md`**（在「复赛项」区新增「团队生态重构 + HR」小节），与现有 GAP 清单并存，标 `(复赛)`。

---

## 六、相关文档索引
- 角色现状：`../src/agentteams/workers.yaml` / `../src/agentteams/manager/SOUL.md` / `../agents/AGENT-IDENTITY.md`
- 团队现状：`../src/agentteams/team-rnd.yaml` / `../src/agentteams/team-leader.yaml` / `design/TEAM-ORGANIZATION.md`
- 工具链待办：`../TOOLCHAIN-PRODUCTION-PLAN.md`
- 场景证据：`../scripts/verify-team-builds-website.py`（已有 MBTI 建站 mock）
- 动态招聘测试：`../tests/test_e2e_dynamic_hiring.py`
- 网上学习：MetaGPT（Code=SOP(Team)）、ChatDev（虚拟软件公司 + Reviewer）、AgentScope（Supervisor+子Agent）
