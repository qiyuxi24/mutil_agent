# Skill → 各职能 Worker 分配矩阵（落成 Worker.spec.skills）

> GOAI · 赛道三「软件研发全流程协同」· Skill 编排（比赛官方 AgentTeams 方式）
> 用比赛官方 `Worker.spec.skills` 把中央仓库（`skills/`）里的每个 Skill 挂载到对应职能 Worker。
> 分配依据：各 Skill frontmatter 的 `assign_when` + `AGENT-IDENTITY.md` 各角色的 `registration.skill_requirements`。
> 更新日期：2026-08-12

---

## 一、分配总览

| 职能 Worker（内部名） | 真实角色 | PDCA | 挂载 Skill（Worker.spec.skills） | 里程碑输出 |
|----------------------|---------|------|--------------------------------|-----------|
| **Aggregator** 缺陷聚合员 | 产品/缺陷管理 | P | `issue-parsing` + L1 基座 | `TASK_SPEC_READY` |
| **RootCause** 根因定位员 | 架构师 | D | `root-cause-analysis`, `impact-analysis` + L1 基座 | `ROOT_CAUSE_FOUND` |
| **Fixer** 修复工程师（可多实例） | 前后端开发 | D | `code-gen` + L1 基座（+ 技术栈变体） | `FIX_APPLIED` |
| **Tester** 测试验证员 | 测试工程师 | C | `test-generation` + L1 基座 | `TEST_PASSED`/`TEST_FAILED` |
| **Releaser** 发布确认员 | 运维/DevOps | A | `release-gate` + L1 基座 | `RELEASE_OK`/`ROLLED_BACK` |
| **Retrospector** 复盘沉淀员 | 数据分析+知识沉淀 | A | `retrospective` + L1 基座 | `RETROSPECT_DONE` |
| **Manager / Team Leader**（协调） | 项目经理 | 全 | `manage-skill`（Skill 编排）+ L3 `collaboration-loop` | 调度闭环 |

> 每个 Worker 自动携带 AgentTeams 内置默认 skill：`file-sync` / `task-progress` / `project-participation` / `mcporter` / `find-skills`（无需手动挂载，Worker 镜像自动分配）。

---

## 二、L2 领域 Skill 分配（官方必查 7 个）

| Skill | 归谁 | assign_when（来自 frontmatter） |
|-------|------|-------------------------------|
| `issue-parsing` | Aggregator | 缺陷聚合员需要接收并结构化多源缺陷/需求输入时 |
| `root-cause-analysis` | RootCause | 根因定位员需要深入代码仓库定位缺陷根因时 |
| `impact-analysis` | RootCause | 根因定位员在定位完成后、修复前评估改动波及范围时 |
| `code-gen` | Fixer（多实例） | 修复工程师需要生成并应用修复补丁时 |
| `test-generation` | Tester | 测试验证员需要对修复结果执行验证闸门判定时 |
| `release-gate` | Releaser | 发布确认员需要对修复结果执行发布门禁与灰度回滚时 |
| `retrospective` | Retrospector | 复盘沉淀员需要在闭环完成后复盘并沉淀知识时 |

---

## 三、L1 基座 Skill 分配（跨 Agent 共享）

L1 基座被 L2 领域 Skill 依赖，跨多个 Worker 复用：

| Skill | 持有者（Worker.spec.skills） |
|-------|----------------------------|
| `git-operations` | RootCause（查 blame/历史）、Fixer（分支/补丁） |
| `code-search` | 几乎全部（issue-parsing/root-cause/code-gen/test） |
| `repo-context` | RootCause、impact-analysis、code-gen |
| `knowledge-rag` | issue-parsing（查同类）、root-cause（查历史）、retrospective（写库） |
| `evidence-log` | 全部（执行证据沉淀，可审计） |

---

## 四、落成 Worker CR 的 YAML 示例

以 **Fixer 修复工程师** 为例（其他 Worker 同理，按上表填 `skills`）：

```yaml
apiVersion: agentteams.io/v1beta1
kind: Worker
metadata:
  name: fixer-go
spec:
  model: qwen3.5-plus
  runtime: openclaw
  soul: |-
    你是一个 AI Agent。你是团队的"修复工程师"，对应真实团队的前后端开发。
    基于根因定位报告生成修复方案并编码执行，提交可验证的代码改动。
    写完代码不自评，由测试验证员用确定性工具当裁判。
  agents: |-
    每次会话先读 SOUL.md；输入 root-cause.md + impact-analysis 清单；
    写 plan.md → 编码实现 → 单元测试 → 提 PR；提交前必须过编译/类型检查/静态分析；
    完成后 @mention 测试验证员并发 FIX_APPLIED。
  skills:                        # ★ Skill 挂载（本文件分配的 L2 + L1）
    - code-gen
    - git-operations
    - repo-context
    - code-search
    - evidence-log
  state: Running
```

> `skills` 字段即官方 `Worker.spec.skills`。L1 基座按需挂载，L2 领域按 `assign_when` 匹配该 Worker 角色。

---

## 五、动态团队下的 Skill 分配（官方 PushOnDemand）

比赛官方支持动态分配，对齐作品"AI 公司式动态团队"创新点：

```bash
# 官方脚本：给指定 Worker 追加 skill
bash skills/scripts/push-worker-skills.sh --worker fixer-go --add-skill code-gen

# 官方脚本：按 skill 反查所有持有者并同步更新
bash skills/scripts/push-worker-skills.sh --skill code-gen

# 官方脚本：从 Worker.spec.skills 移除 skill（回收）
bash skills/scripts/push-worker-skills.sh --worker fixer-go --remove-skill code-gen
```

**动态场景**：
- 项目引入 `Rust` 后端 → 招募 Rust Fixer，挂载 `code-gen`(rust 变体) + L1 基座。
- 跨领域任务（如安全审计）→ 临时招募 Security Agent，挂载对应安全 skill，任务结束即回收。
- Skill 回收 → 移除 `Worker.spec.skills` 中的项，Worker 无状态，可随时重建。

---

## 六、Skill 管理编排总图（官方三层）

```
skills/  ← 中央仓库（worker-skills/，Manager 唯一维护）
├── <name>/SKILL.md        ← Skill 定义（frontmatter: name+description+assign_when）
├── <name>/scripts/        ← 可执行脚本（官方工具）
├── <name>/references/     ← 分场景深度文档（渐进式披露）
├── scripts/               ← 官方管理脚本（push/render/find）
│   ├── push-worker-skills.sh    → Worker.spec.skills 分配/回收/同步
│   ├── render-skills.sh         → ${AGENTTEAMS_*} 环境变量渲染
│   └── agentteams-find-skill.sh → 从生态发现技能
├── ASSIGNMENT-MATRIX.md   ← 本文件：skill→Worker 分配真相源
├── REGISTRY.md            ← 发现层（元数据 Catalog）
└── SKILL-LIST.md          ← 评审层（官方 9 字段）
```

Manager 通过 `manage-skill` + `skills/scripts/` 集中编排：**定义 → 注册 → 分配 → 同步 → 回收**，完全对齐比赛官方 AgentTeams。

---

## 七、工具链（MCP + scripts）分配

> 工具链三层设计（copaw 内置 + MCP + Skill scripts）详见 `design/TOOLCHAIN.md`。
> 本矩阵记录「哪个 Worker 挂哪个 MCP / 哪个 Skill 带哪个可执行脚本」，是 `workers.yaml` 中 `spec.mcpServers` 的真相源。

| Worker | spec.mcpServers | 用途 | Skill scripts（可执行） |
|--------|----------------|------|------------------------|
| Aggregator | `github` | 拉真实 Issue/需求 | — |
| RootCause | `github` | 读真实仓库代码/搜索/blame | — |
| Fixer | `github` + `code-scan` | 分支/PR + 代码扫描 | `code-gen/scripts/check-patch-integrity.py` |
| Tester | `test-platform` | 跑测试/覆盖率/静态分析 | `test-generation/scripts/verify_test_gate.py` |
| Releaser | `ci`（可选） | 触发发布/回滚流水线 | — |
| Retrospector | —（内置 RAG） | 写知识库 | — |

> 接入机制：`scripts/register-mcp.ps1`（复用官方 `setup-mcp-server.sh`/`setup-mcp-proxy.sh`）→ Higress 网关 upsert → Consumer 授权（REPLACE）→ `mc cp` 推 MinIO → Worker `mcporter` 拉取。详见 `src/agentteams/mcp/README.md`。
> MCP 模板：`src/agentteams/mcp/mcp-code-scan.yaml`（Fixer）、`mcp-test-platform.yaml`（Tester）；`github` 用官方内置 `mcp-github.yaml`。

---

## 文档索引
- Skill 清单（9 字段）：`SKILL-LIST.md`
- Skill 注册表（发现层）：`REGISTRY.md`
- 官方管理脚本：`skills/scripts/`
- Agent 身份与动态团队：`agents/AGENT-IDENTITY.md`
- AgentTeams 落地机制：`design/AGENTTEAMS-INTERNALS.md`
- Skill 生命周期机制：`design/SKILL-LIFECYCLE.md`
- 工具链三层设计：`design/TOOLCHAIN.md`
- MCP 接入胶水层：`src/agentteams/mcp/README.md`
