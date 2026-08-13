# TODO — 待办清单

> GOAI 大赛 · 赛道三「软件研发全流程协同」（协同基点：AgentTeams）
> 本文件是**待办唯一真相源**。`PLAN.md` 是「计划」（做什么+为什么），本文件是「待办」（还剩什么，详细到可执行）。
> 维护方式：完成一项勾掉 `[x]` 并注明日期；新增待办加到底部「新增」区或对应分组。

---

## 关键节点

| 阶段 | 截止 | 剩余 | 对应待办分组 |
|------|------|------|-------------|
| 初赛 | **2026-08-16** | 3 天 | P0 |
| 复赛 | 2026-09-03 | 21 天 | P1 |
| 决赛 | 2026-09-22 | 40 天 | P3 |

---

## 立即执行（今天 8.13）

> 保命项：把散落本地的全部参赛成果入库，防丢失。

- [ ] **git 保底提交**：新增根 `.gitignore`（忽略 `.codebuddy/` IDE 工作记忆 + `mattpocock-skills/` 第三方参考）+ 提交 `README.md` + `software-dev-fullflow/`（`references/` `data/` 已被子 `.gitignore` 排除）

---

## P0 · 初赛材料（8.16 截止，最紧迫）

> 来源：PLAN 第 8 项。初赛只交方案、不强制部署。评审看「场景价值 25% + 多Agent协同 25% + Skill工程 25%」的设计说服力。

- [ ] **作品简介**（500 字内；参考 `GOAI-QA-ESSENTIALS.md` 的 FAQ 精华）
  - 必须覆盖 5 点：
    1. 一句话定位：用 AgentTeams 造「软件研发多 Agent 团队」，把缺陷/需求→修复→发布→复盘做成 PDCA 闭环
    2. 核心创新点：动态招人/裁员（AI 公司式）+ 成员评价体系（贡献度+合格度，业界少见）
    3. 技术栈：AgentTeams + AgentScope + DeepSeek
    4. 闭环链路：缺陷聚合 → 根因定位 → 修复 → 测试验证 → 发布 → 复盘沉淀
    5. 评审亮点：确定性状态机 + 全程可审计 + Skill 三层体系
  - 验收：≤500 字、通篇无 MAF 字样、对齐 5 个评审维度

- [ ] **方案 PPT 素材**（结构 / 图表 / 数据）
  - 建议页结构（10+ 页）：痛点 → 方案定位 → 架构图 → 6 角色映射表 → PDCA 状态机图 → Skill 三层图 → 成员评价体系 → Demo 截图 → 动态团队创新点 → 行业可复制性
  - 需备图表素材（3 张核心图）：
    1. PDCA 8 状态流转图（含打回/回滚路径，见 `design/PDCA-CLOSED-LOOP.md`）
    2. 6 Worker 角色映射表（见 `agents/AGENT-IDENTITY.md`）
    3. Skill 三层体系图 L0-L3（见 `skills/SKILL-LIST.md`）
  - 验收：≥10 页结构 + 3 张核心图可直接复用

---

## P1 · 复赛核心（9.3 截止）：AgentTeams 闭环打通 + 工程真实性补强

> 来源：PLAN 第 7 项 + `src/AGENTTEAMS-MIGRATION.md` + 对标大厂差距清单（Devin/Codex/QoderWork）。
> 现状：Manager default 在跑，6 个研发 Worker 已创建并 Running，但**闭环未在 AgentTeams 上跑通**；
> 且 `src/loop` 的验证闸门是 LLM 自评、fixer 不操作真实仓库，与业界顶级产品有硬差距。

### A. AgentTeams 闭环真跑通（多Agent协同 25%）

- [ ] **验证 Manager 驱动 6 Worker 跑通 PDCA 闭环**
  - 路径：Element Web 给 Manager 发任务 → aggregator→rootcause→fixer→tester→releaser→retrospector 接力
  - 验收：一条缺陷从输入到 `RETROSPECT_DONE` 完整流转，Matrix 房间可见 6 个里程碑握手词
- [ ] **Skill 挂载**：`push-worker-skills.sh` 推送核心 Skill + `spec.skills` 声明（已编排 `ASSIGNMENT-MATRIX.md`，未实际挂载）
- [ ] **（可选）组建 Team**：视评审需要，用 team-leader-agent 模板建 Team（若 Manager 直驱 Worker 已够则跳过）
- [ ] **可观测/RAG 在 AgentTeams 落地**：Matrix 房间留痕（Trace）+ MinIO `shared/knowledge/`（RAG 知识库，design 已设计）

### B. 工程真实性补强（工程落地 20%，对标大厂差距）

- [ ] **确定性验证闸门**：把 `manager.py::_verify` 从「LLM 判断 PASS/FAIL」改为「真跑测试/编译/静态分析」当裁判（对齐 Ralph 反压主张）
  - 验收：tester 收到修复后实际执行 pytest/编译，PASS/FAIL 由确定性工具产出，非 LLM 自评
- [ ] **真实工具执行层（MCP）**：给 fixer 接 git clone / 改文件 / 编译 / 跑测试 / 提 PR 的真实工具（当前只输出 diff 文本）
  - 验收：fixer 能在真实仓库完成「改代码 → 跑测试 → 生成 PR」
- [ ] **Skill 可执行化**：给 7 个核心 Skill 补可执行 `scripts/`（当前只有 SKILL.md 指令）
  - 验收：至少 `code-gen` / `test-generation` 有真实可执行脚本
- [ ] **（可选）独立 Code Reviewer Worker**：把 reviewer 从 fixer 内部子代理提升为独立门禁 Worker（对应大厂 Code Review 硬门禁）

### C. 复赛提交材料

- [ ] **更新版方案**：PLAN / 设计文档同步到最新实现
- [ ] **AgentTeams 代码包**：`workers.yaml` + SOUL + skills 打包
- [ ] **Demo/视频**（复用 P3）

---

## P2 · KPI 系统收尾（成员评价体系）

> 来源：`design/AGENT-EVALUATION.md` §3.3 / §7。轻量方案已落地，剩精确方案与真实执行。

- [ ] **精确方案「替换基线法」**：C3 精确反事实（替换产出物为基线、重跑下游），当前只落地轻量采纳分
- [ ] **治理命令真正执行**：`coach` / `demote_or_fire` 目前只打印 `agt` 命令，未在 AgentTeams 环境实际调用

---

## P3 · Demo 演示（决赛 9.22）

> 来源：PLAN 第 9 项。

- [ ] **演示脚本**：端到端跑一个「缺陷 → 修复 → 测试 → 发布 → 复盘」完整案例（选一个有代表性的真实缺陷）
- [ ] **录屏视频**：含 AgentTeams Element Web 发任务 → 6 Worker 接力 → 评价报告全流程

---

## 新增（临时/待归类）

> 新产生的待办先放这里，归类后上移。

（暂无）
