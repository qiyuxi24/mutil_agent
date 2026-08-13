---
name: manage-skill
description: 编排与管理项目 Skills 中央仓库（worker-skills/）的全生命周期：新增、分配、回收、同步到各职能 Worker。触发词：skill、技能、管理skill、编排skill、skill工程、新建skill、分配skill、回收skill。由 Manager 持有，用于集中管理所有 Worker 的 skills。
assign_when: Manager 需要创建、分配、回收或同步 Worker 的 skills 时
---

# Skill: manage-skill（Manager 集中编排 Skill）

本 Skill 是 Manager 集中管理所有 Worker Skills 的编排能力，**完全对齐比赛官方 AgentTeams 的 skill 管理机制**（官方 `worker-management` skill + `push-worker-skills.sh` + `Worker.spec.skills`）。核心原则：**Skills 由 Manager 统一维护，Worker 不能修改自己的 skills。**

## 输入

- 待管理操作：新增 / 分配 / 回收 / 同步 / 查看，及目标 Skill 名与目标 Worker。
- 现有元数据：`skills/REGISTRY.md`（发现层）、`skills/SKILL-LIST.md`（9 字段评审层）。
- 各职能 Worker 清单（Aggregator / RootCause / Fixer / Tester / Releaser / Retrospector，见 `agents/AGENT-IDENTITY.md`）。

## 执行步骤

1. **定位中央仓库**：本项目 `skills/` 即官方 `worker-skills/` 中央仓库，每个 `<name>/SKILL.md` 是 skill 定义真相源。
2. **新增 Skill**（若为新增）：
   - 创建 `skills/<name>/SKILL.md`，frontmatter **必须**含 `name` + `description` + `assign_when`（官方强制）。
   - 命令式写正文（SOP + Gotchas）；脚本放 `<name>/scripts/`，分场景深度文档放 `<name>/references/`。
   - 命名校验：`^[a-z0-9][a-z0-9-]*$`（小写字母/数字/连字符，以字母或数字开头）。
   - 在 `REGISTRY.md` 登记元数据，在 `SKILL-LIST.md` 补 9 字段。
3. **分配 Skill 给 Worker**（官方方式）：
   ```bash
   bash skills/scripts/push-worker-skills.sh --worker <name> --add-skill <skill-name>
   # 或用 Worker CR spec.skills（YAML）
   #   spec:
   #     skills: [git-operations, repo-context, code-search, code-gen]
   ```
4. **回收 Skill**：
   ```bash
   bash skills/scripts/push-worker-skills.sh --worker <name> --remove-skill <skill-name>
   ```
5. **同步 Skill 更新**（改定义后推给所有持有者）：
   ```bash
   bash skills/scripts/push-worker-skills.sh --skill <skill-name>
   ```
6. **环境变量渲染**（若 SKILL.md 含 `${AGENTTEAMS_*}` 占位）：
   ```bash
   bash skills/scripts/render-skills.sh skills/<name>
   ```
7. **注册 / 同步文档**：更新 `REGISTRY.md` / `SKILL-LIST.md` / `skills/README.md`。

## 输出

- 新增：规范化 `skills/<name>/`（SKILL.md + 可选 scripts/references）+ 已更新注册表/清单。
- 分配/回收：各职能 Worker 的 `Worker.spec.skills` 变更（可审计）。
- 查看：当前各 Worker 的 skill 分配情况。

## 依赖工具

- `skills/scripts/push-worker-skills.sh`（官方：add/remove/按 skill 反查分发）
- `skills/scripts/render-skills.sh`（官方：白名单 envsubst 渲染 `${VAR}`）
- `skills/scripts/agentteams-find-skill.sh`（官方：从 Agent Skills 生态发现技能）
- Worker CR 的 `spec.skills` / `agt create worker --skills` / `agt update worker --skills`

## 失败处理

- skill 命名不规范 → 报告具体违规，修正后重试。
- push 失败 → 检查 `agt` 是否可用、Worker 是否存在，报告关键错误，不静默重试。
- 重复分配同名 skill → push 脚本自动去重（`jq` 判断 index），幂等。

## 安全边界

- **Manager 独占写权限**：Worker 不能修改自己的 skills（local→remote 同步排除 `skills/**`）。
- 只操作 `skills/` 目录与 Worker CR 的 skills 字段，不越权改其他配置。
- 分配/回收通过 Worker CR 记录，可审计；危险操作（回收核心 skill）需确认。

## 里程碑

- 新增完成 → `SKILL_ADDED`（入注册表，可被分配）。
- 分配完成 → `SKILL_ASSIGNED`（挂载到对应 Worker）。
- 回收完成 → `SKILL_REMOVED`（从 Worker.spec.skills 移除）。

## 复用价值

本 Skill 是 Manager 治理 Skill 生态的标准化入口：任何人 / 任何 Agent 新增或调整 Skill 都走同一套官方流程（定义→注册→分配→同步），保证项目 Skill 生态与比赛官方 AgentTeams 机制完全对齐、可审计、可分发。
