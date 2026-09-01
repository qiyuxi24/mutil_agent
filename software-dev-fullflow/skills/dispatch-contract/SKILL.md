---
name: dispatch-contract
description: >-
  派发契约化 Skill：把 Leader 的派单升级为「可验收契约」。含派发包七要素模板、
  派发哨兵 fail-closed 校验、独立复审包协议、角色-模型映射。供 Coordinator 协同
  路由员在 Leader 派单后切片/拆包/校验/组织复审时使用。触发：派发、派单、切片、
  契约、哨兵、dispatch、brief、复审包、路由、协调。
assign_when: >-
  协同路由员（Coordinator）需要把大任务切成独立切片、生成结构化派发包、校验派发
  质量（缺验收标准即拒）、或组织独立复审时分配。
---

# dispatch-contract — 派发契约 Skill

> 借鉴来源：`references/oil-oil/codex-team-mode`（三角色子 Agent / 派发哨兵 / 派发包七要素 / 独立复审协议），
> 适配声明见 `references/ADAPTATION-NOTES.md`。本 Skill 由 **Coordinator**（协同路由员）使用，
> 是 Leader 编排的派发契约层，**不改变** PDCA 状态机与现有 Worker 行为。

## 1. 本 Skill 解决什么

Leader 现在用自然语言派单，信息密度低、验收标准不前置。本 Skill 把派单变成**可验收契约**：

1. **切片**：把 Leader 的大任务切成独立无依赖切片（并行潜力）。
2. **派发包**：每个切片生成「七要素派发包」。
3. **哨兵校验**：缺验收标准（checks/outcome）的派发一律拒绝（fail-closed）。
4. **独立复审包**：组织复审时强制"一个风险 + 精确证据 + 已通过检查 + 停止条件"。

## 2. 执行步骤

### 步骤 1：读取声明式配置

```bash
# 角色-模型映射表（三角色理念，声明式）
python skills/dispatch-contract/scripts/dispatch_cli.py role-map --json

# 派发包 schema（七要素必填项）
python skills/dispatch-contract/scripts/dispatch_cli.py schema
```

### 步骤 2：生成派发包模板

```bash
python skills/dispatch-contract/scripts/dispatch_cli.py template-brief \
  --outcome "修复登录接口空用户名返回 500" \
  --target "fixer" \
  --scope "仅后端鉴权逻辑，不动前端" \
  --checks '["pytest tests/test_login.py::test_empty_username -q"]' \
  --stop-when "测试通过或 3 轮尝试后" \
  --returns "shared/tasks/{id}/fix/patch.diff + brief.md"
```

生成后落盘为 `shared/tasks/{id}/dispatch/{n}-brief.yaml`，作为派发契约副本（审计用）。

### 步骤 3：哨兵校验（fail-closed）

**任何派发前必须先过哨兵**：

```bash
python skills/dispatch-contract/scripts/dispatch_cli.py validate-brief brief.json
```

- 通过 → `PASS`，可派发。
- 缺 `outcome` / `checks`（空）/ `stop_when` / 未知 target → `BLOCKED`（退出码 2），附缺失字段清单。
- **BLOCKED 的派发禁止发出**，返回给 Leader 补齐契约。

### 步骤 4：派发 + 记录

- 派发时在 `AgentMessage.metadata.brief` 附带七要素（`team-comm` 的 request 支持携带）。
- 契约副本落盘 `shared/tasks/{id}/dispatch/`，供复盘与审计。

### 步骤 5：组织独立复审

```bash
python skills/dispatch-contract/scripts/dispatch_cli.py validate-review review.json
```

复审包必须含：
- `risk`：一个具体的未解决风险
- `evidence`：精确证据（文件/行号/日志片段）
- `passed_checks`：已通过的检查清单
- `stop_when`：本轮有界停止条件

缺任一 → 拒绝（"无有效复审包 = 可避免的路由"），不进入评审。

## 3. 失败处理

| 场景 | 处理 |
|------|------|
| 哨兵 BLOCKED | 不派发，附缺失字段清单返回 Leader 补齐 |
| 切片冲突（两切片改同一文件） | 拆为串行，标记 `sequential` |
| 复审包不完整 | 拒绝复审，要求补齐 risk/evidence |
| CLI 不可用 | 按 `references/DISPATCH-BRIEF-SCHEMA.md` 手工核对七要素 |

## 4. 安全边界

- 只做派发契约的**生成与校验**，不代执行员工工作、不写员工产出。
- 不修改现有 `state.py` / `agent_bus.py` / `workers.yaml` 既有 Worker 的行为。
- 契约与证据落盘可审计（`shared/tasks/{id}/dispatch/`）。

## 5. 参考资料

- `references/DISPATCH-BRIEF-SCHEMA.md`：七要素 schema（声明式）
- `references/ROLE-MODEL-MAP.md`：角色-模型映射（三角色理念）
- `references/SENTINEL-RULES.md`：哨兵 fail-closed 规则
- `references/REVIEW-PACKAGE.md`：独立复审包协议
- `references/ADAPTATION-NOTES.md`：从 oil-oil 借鉴的适配说明与不照搬项
- 脚本：`scripts/dispatch_cli.py`（纯标准库，零第三方依赖）
