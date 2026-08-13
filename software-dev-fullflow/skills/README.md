# Skills 工程编排（比赛官方 AgentTeams 方式）

> GOAI · 赛道三「软件研发全流程协同」· Skill 工程体系 —— **用比赛官方（AgentTeams）的标准方式编排 skill 管理**
> 更新日期：2026-08-12

本目录是项目的 Skill 工程体系，**完全对齐比赛官方 AgentTeams 的 Skill 机制**（协同基点）。核心原则：**Skill 由 Manager 集中管理，Worker 通过 `Worker.spec.skills` 挂载**，Skill 不是写死的，而是可被注册表发现、按需分配/回收的能力包。

---

## 一、比赛官方的 Skill 定义（权威依据）

比赛官方 AgentTeams 的 Skill 机制（源码：`references/refs/agent-teams/`）：

- **载体**：目录 + `SKILL.md` + 可选 `scripts/` / `references/` / `assets/`。
- **frontmatter**：`name` + `description`（Worker 版额外必填 **`assign_when`**）。
- **执行**：纯提示词注入指令集（Agent 读 SKILL.md 正文后遵指令执行），脚本用 `scripts/`。
- **触发路由**：`description` 里的自然语言触发词决定"何时加载该技能"。
- **挂载**：`Worker.spec.skills`（CR 规范）→ `agt create worker --skills` / `agt update worker --skills`。
- **Manager 集中管理**：Worker 不能修改自己的 skills（local→remote 同步排除 `skills/**`）。

> 官方文档：`references/refs/agent-teams/manager/agent/worker-skills/README.md`
> 官方管理脚本：`references/refs/agent-teams/manager/agent/skills/worker-management/`

---

## 二、目录结构（对齐官方 worker-skills 中央仓库）

```
skills/                        ← 本项目中央仓库（= 官方 worker-skills/）
├── README.md                  ← 本文件：skill 管理手册
├── SKILL-LIST.md              ← Skill 清单主文档（赛道 9 字段评审重点）
├── REGISTRY.md                ← Skill 注册表（发现层 / Catalog，OpenClaw 式）
├── ASSIGNMENT-MATRIX.md       ← skill → 各职能 Worker 分配真相源（Worker.spec.skills）
├── scripts/                   ← 官方管理脚本（比赛官方原版）
│   ├── push-worker-skills.sh  ← 分配/回收/同步 Skill 到 Worker.spec.skills
│   ├── render-skills.sh       ← ${AGENTTEAMS_*} 白名单 envsubst 渲染
│   └── agentteams-find-skill.sh ← 从 Agent Skills 生态发现技能
├── manage-skill/              ← Manager 编排 Skill 的管理 Skill（官方 worker-management 风格）
│   └── SKILL.md
└── <skill-name>/              ← 每个 Skill 一个目录（官方标准结构）
    ├── SKILL.md               ← frontmatter(name+description+assign_when) + 指令正文
    ├── scripts/               ← 可执行脚本（按需，确定性任务）
    ├── references/            ← 分场景深度文档（渐进式披露）
    └── assets/                ← 输出用资源（按需）
```

7 个核心 Skill：`issue-parsing` `root-cause-analysis` `impact-analysis` `code-gen` `test-generation` `release-gate` `retrospective`（另含 `collaboration-loop` L3、5 个 L1 基座、`manage-skill` L0 编排，见 `SKILL-LIST.md`）。

---

## 三、新建 Skill（官方规范）

1. 创建目录 `skills/<name>/`。
2. 编写 `SKILL.md`，**frontmatter 必须**含：
   ```yaml
   ---
   name: <skill-name>          # 小写/数字/连字符，^[a-z0-9][a-z0-9-]*$
   description: <一句话说明>     # 触发路由关键词，决定何时加载
   assign_when: <什么样的 Worker 应拥有此 skill>  # Manager 据此自动分配
   ---
   ```
3. 正文用命令式（动词开头）写 SOP + Gotchas；脚本放 `scripts/`，深度文档放 `references/`。
4. 在 `REGISTRY.md` 登记元数据；在 `SKILL-LIST.md` 补 9 字段；在 `ASSIGNMENT-MATRIX.md` 登记分配。

---

## 四、分配 Skill 到 Worker（官方方式）

```bash
# 给指定 Worker 追加 skill
bash skills/scripts/push-worker-skills.sh --worker <name> --add-skill <skill-name>

# 按 skill 反查所有持有者并同步更新（改定义后）
bash skills/scripts/push-worker-skills.sh --skill <skill-name>

# 从 Worker.spec.skills 移除 skill（回收）
bash skills/scripts/push-worker-skills.sh --worker <name> --remove-skill <skill-name>

# 查看当前分配
agt get workers -o json | jq '.workers[] | {name, skills}'
```

> 完整分配映射见 `ASSIGNMENT-MATRIX.md`（含各 Worker CR 的 YAML 示例）。

---

## 五、环境变量渲染（官方 render-skills）

若 SKILL.md 含 `${AGENTTEAMS_*}` 占位符，用官方白名单脚本渲染后再交 Agent 读：

```bash
bash skills/scripts/render-skills.sh skills/<name>
```

> 白名单变量见脚本内 `VARS`（`AGENTTEAMS_MATRIX_URL`/`AGENTTEAMS_AI_GATEWAY_URL`/`AGENTTEAMS_DEFAULT_MODEL` 等），未在名单内的 `${var}`（如 `${task_id}`）不会被替换，防误渲染。

---

## 六、渐进式披露（三层加载）

| 层 | 内容 | 时机 | 落点 |
|----|------|------|------|
| **Catalog（发现）** | 全部 Skill 的 `name` + `description` | 会话启动 / 动态组队 | 注入 Manager system prompt |
| **Instructions（激活）** | 命中任务的 `SKILL.md` 正文 | Skill 被触发时 | Agent 读取正文遵指令执行 |
| **Resources（执行）** | `scripts/` `references/` `assets/` | 正文引用且需要时 | 按需读取 / 执行脚本 |

> 原则：`SKILL.md` 保持精简（只放核心 SOP），详细 schema / 对照表 / 模板放 `references/`，脚本放 `scripts/`。

---

## 七、三层编排关系（官方框架 × 注册表 × 评审）

```
官方 AgentTeams 脚本（push/render/find）  →  管「skill 如何分配/同步到 Worker」
REGISTRY.md（Catalog 层）                 →  管「运行时如何发现 / 何时用哪个 Skill」
SKILL-LIST.md（9 字段）                   →  管「赛道评审如何自证（复用价值/安全边界/失败处理）」
ASSIGNMENT-MATRIX.md（分配真相源）        →  管「每个 Skill 挂到哪个 Worker」
manage-skill（管理 Skill）                →  管「以上一切如何被 Manager 集中维护」
```

---

## 八、文档索引

- Skill 清单主文档：`SKILL-LIST.md`
- Skill 注册表（发现层）：`REGISTRY.md`
- Skill → Worker 分配：`ASSIGNMENT-MATRIX.md`
- 生命周期设计：`design/SKILL-LIFECYCLE.md`
- 官方管理脚本：`skills/scripts/`
- 管理 Skill：`manage-skill/SKILL.md`
- 官方 AgentTeams 源码：`references/refs/agent-teams/`
