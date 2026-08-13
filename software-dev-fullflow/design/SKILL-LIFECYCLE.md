# Skill 生命周期机制设计（SKILL-LIFECYCLE）

> GOAI · 赛道三「软件研发全流程协同」· Skill 动态分配 / 发现 / 治理机制
> 核心回答：**Skill 不是写死的，而是可被注册表发现、按需分配/回收、版本化、质量门控的能力包**，支撑「AI 公司式动态 Agent 团队」。
> 依据：`references/theory/SKILL-REGISTRY-RESEARCH.md`（5 来源调研）。
> 更新日期：2026-08-12

---

## 一、设计目标

让 Skill 具备**与动态团队同等的"活"的生命周期**——能招（分配）、能裁（回收）、能升级（版本）、能复用（跨项目）、能治理（审批/权限/审计）。对齐官方"Skill 工程体系与生态复用 25%"评审点。

---

## 二、生命周期总览

```
        ┌─────────────────────────────────────────────────────────┐
        │                   注册表 REGISTRY（发现层）               │
        │   shared/skills/registry.json  ← 元数据 Catalog          │
        └─────────────────────────────────────────────────────────┘
              ▲ 发现/检索                 │ 发布/注册(质量门控)
              │                          ▼
        ┌─────────────────────────────────────────────────────────┐
        │                Manager 调度器（Skill 决策中枢）            │
        │  读注册表 → 按任务/团队需求 → 决定分配哪些 Skill 给哪个 Worker│
        └─────────────────────────────────────────────────────────┘
              │ 分配(assign_when匹配)      │ 回收 / 升级 / 审批
              ▼                          ▼
   ┌────────────────────┐   ┌─────────────────────────────────────┐
   │  Worker.spec.skills │   │   治理层（JFrog 式）：审批/签名/权限/审计│
   │  动态挂载 Skill 集  │   └─────────────────────────────────────┘
   └────────────────────┘
```

**关键分离**：注册表（发现）≠ Skill 正文（执行）≠ 分配决策（Manager）。三层解耦，各司其职。

---

## 三、核心机制一：发现（Discovery）—— 对齐 AgentSkills Catalog

**目标**：让 Agent 知道"有哪些 Skill 可用"，不注入全部正文（防上下文膨胀）。

- **Catalog 注入**：会话启动 / 动态团队组建时，把注册表元数据（name+description+依赖）注入 Manager 的 system prompt，格式为 `<agent-skills>` 目录。
- **三层渐进披露**：
  1. **Catalog**：name + description（全部，短小）
  2. **Instructions**：命中任务的 SKILL.md 正文（按需，经 SkillViewer/load_skill 读取）
  3. **Resources**：scripts/references/assets（正文引用且需要时）
- **语义检索增强**（可选，Voyager 式）：当 Skill 数超过阈值（如 >15），用 `knowledge-rag` 做 description 向量 Top-K 检索，只注入最相关的一批，而非全量。对齐 Voyager Top-5（96.5% 准确率）。

---

## 四、核心机制二：分配（Assignment）—— 对齐 OpenClaw 按需 install

**目标**：让 Manager 按项目/任务需求**动态挂载** Skill 给 Worker，支撑招工/裁员。

**分配依据（三个字段）**：
1. `assign_when`（语义条件）：Manager 读注册表，匹配该 Skill 何时该给哪种 Worker。
2. `compatibility`（技术约束）：技术栈/运行时/OS 匹配，确保 Skill 可用。
3. `owner_agent`（默认归属）+ `category`（分层）：默认给固定 Worker，或动态给新 Worker。

**分配流程（对应 Manager 调度工具，见 `design/MANAGER-LOOP-DESIGN.md`）**：
```
Manager 收到任务
  → 拆解需要哪些能力（skill_requirements）
  → 查注册表匹配 assign_when + compatibility 的 Skill
  → 决定：招新 Worker（带 Skill 集） 或 给现有 Worker 追加 Skill
  → 调 PushOnDemandSkills 挂载 → 更新 Worker.spec.skills
```

**动态招工示例**：
- 任务涉及 `Rust` 后端修复 → 注册表匹配 `code-gen`（compatibility: rust）+ L1 基座 → 招募一个 Rust Fixer，挂载 `{code-gen, git-operations, repo-context, code-search}`。
- 任务只涉及 `前端` → 换一套前端 compatibility 的 `code-gen` 变体，另招前端 Fixer。

**回收（裁员）**：
- 任务结束 / 项目换向 → Manager 调 skill 回收，移除 Worker.spec.skills 中不再需要的 Skill，或销毁整个无状态 Worker（对齐"AI 公司裁员"创新点）。

---

## 五、核心机制三：治理（Governance）—— 对齐 JFrog 全生命周期

**目标**：安全可审计，防供应链攻击与过度权限。

| 机制 | 落地 |
|------|------|
| **审批** | 新 Skill / 高风险 Skill 入注册表前，需 Manager 或人工审批（Human-in-the-loop） |
| **签名验证** | 对批准的 Skill 做签名，加载前校验完整性（防篡改/供应链） |
| **最小权限** | Skill 只在工具层获取最小权限，危险操作（改权限/删数据/外发）需二次确认；`allowed-tools` 约束 |
| **审计** | 记录 Skill 的发现/分配/激活/资源读取/失败原因（对齐 AgentSkills 观测环节 + JFrog 血缘追踪） |
| **降级** | 受信 Skill 不可用时，降级为本地内置或禁用以防未审查 Skill 顶替 |

**安全边界原则**（对齐调研）：**Skill 不承担权限系统职责**，权限由 Harness/工具层实施（最小权限、路径限制、审批、超时、审计）。Skill 只是"指令集"。

---

## 六、核心机制四：质量门控与版本（Quality & Version）

**目标**：保证 Skill 质量与可复用，防退化。

- **入册门槛（evals）**：新 Skill 入注册表前必须通过 4 类评测——正向触发 / 负向不触发 / 边界条件 / 异常输入（对齐 AgentSkills + Anthropic 规范）。
- **确定性验证优先**：Skill 的关键产出用确定性工具验证（test-generation 跑测试、release-gate 跑门禁），不依赖 LLM 自评（对齐 Voyager"确定性验证器 > LLM-as-Judge"）。
- **语义化版本**：`MAJOR.MINOR.PATCH`。`description` 变更视为 MAJOR（直接影响触发召回），需回归测试。
- **沉淀门控**：只有验证过的经验才由 `retrospective` 沉淀入知识库（对齐 Voyager"非所有尝试都沉淀"）。

---

## 七、与动态 Agent 团队创新点的衔接

> 这是作品核心创新点（"AI 公司式动态团队"）的 Skill 支撑：

| 团队动作 | Skill 生命周期响应 |
|---------|-------------------|
| **招人** | Manager 读注册表 → 按需求选配 Skill → 新 Worker 挂载（PushOnDemandSkills） |
| **裁员** | 移除 Worker.spec.skills 不需要的 Skill / 销毁无状态 Worker |
| **换技术栈** | 替换 compatibility 匹配的 code-gen 等 Skill 变体 |
| **能力升级** | Skill 版本升级（SemVer）+ 质量门控，团队"越用越强" |
| **跨项目复用** | 注册表作共享资源（shared/skills/registry.json），新项目/团队复用已验证 Skill |

---

## 八、落成 AgentTeams 资源（与 `design/AGENTTEAMS-INTERNALS.md` 对齐）

| 机制 | AgentTeams 落地 |
|------|----------------|
| 注册表 | `shared/skills/registry.json`（MinIO 共享状态） |
| Catalog 注入 | Manager system prompt 的 `<agent-skills>` 块 |
| 分配 | `PushOnDemandSkills` / `push-worker-skills.sh` / `Worker.spec.skills` |
| 远程共享 | `pushRemoteSkills`（nacos:// 源拉取） |
| 回收 | 更新 Worker.spec.skills / 销毁 Worker |
| 治理/审计 | Higress 权限 + 记录 Trace/Log |

---

## 九、评审亮点自检

1. **回答"Skill 不是写死"**：注册表（发现）与正文（执行）分离，Manager 动态分配/回收，三层渐进披露。
2. **5 来源证据**：AgentSkills 规范（三层加载）/ OpenClaw（skill.json+按需 install）/ JFrog（治理）/ Anthropic（生态组装）/ Voyager（检索+质量门控）。
3. **对齐官方**：Skill 作为"任务能力抽象层"，9 字段全覆盖；评审"Skill 工程体系与生态复用"重点全命中。
4. **支撑创新点**：动态招工/裁员/换栈/升级/复用，是"AI 公司式动态团队"的 Skill 底座。
5. **安全可审计**：审批/签名/最小权限/审计/降级，对齐工程落地 20% 权重。

---

## 文档索引
- 调研依据：`references/theory/SKILL-REGISTRY-RESEARCH.md`
- 总注册表：`skills/REGISTRY.md`
- Skill 清单：`skills/SKILL-LIST.md`
- 调度 loop：`design/MANAGER-LOOP-DESIGN.md`
- AgentTeams 内部：`design/AGENTTEAMS-INTERNALS.md`
