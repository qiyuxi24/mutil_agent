---
name: git-operations
description: Git 操作：分支管理/checkout/diff/commit/log/blame，安全提交审计，防误操作保护。触发词：分支、提交、diff、commit、checkout、blame、log、branch。
assign_when: 任何 Worker 需要创建分支、提交代码、追溯历史、生成变更对比时分配。
---

# Skill: git-operations

提供安全、可审计的 Git 操作能力。所有操作在 Worker 沙箱容器内执行，**禁止破坏性命令**，每次提交自动生成规范 commit message 并记录审计日志。

## 输入

- 操作类型：`branch` / `checkout` / `add` / `commit` / `diff` / `log` / `blame` / `status`
- 操作参数：分支名、文件路径、commit message 模板、追溯范围等
- 上下文：当前仓库路径、任务 ID（用于审计关联）

## 执行步骤

1. **安全检查**：校验操作类型，拦截 `push --force`、`reset --hard`、`clean -f`、`branch -D` 等破坏性命令。
2. **分支管理**：
   - `git checkout -b feature/T-XXXX` 创建功能分支
   - `git branch -a` 列出所有分支
   - `git branch -d` 删除本地已合并分支（需确认）
3. **变更提交**：
   - `git add <files>` 精确暂存，**禁止 `git add -A` / `git add .`**（防止误提交敏感文件）
   - `git commit -m "<type>(<scope>): <description>"` 格式提交（feat/fix/docs/test/refactor/ci/chore）
   - 提交前自动检查 `.env`、`credentials/`、`providers.json` 等敏感文件是否在暂存区
4. **变更对比**：
   - `git diff` 生成工作区变更
   - `git diff --stat` 统计变更范围
   - `git diff --staged` 查看暂存区变更
5. **历史追溯**：
   - `git log --oneline -n <N>` 查看近期提交
   - `git blame <file>` 定位每行代码的作者与提交
   - `git show <commit>` 查看特定提交详情
6. **审计记录**：每次操作写入 `evidence-log`（操作类型、参数、结果、时间戳）

## 输出（GIT_OP_DONE）

```json
{
  "task_id": "T-0001",
  "operation": "branch|checkout|commit|diff|log|blame|status",
  "branch": "feature/T-0001",
  "result": {
    "commit_hash": "abc1234",
    "files_changed": 3,
    "additions": 12,
    "deletions": 5,
    "message": "fix(worker): 修复空指针异常"
  },
  "status": "OK|BLOCKED|ERROR"
}
```

## 依赖工具

- L1 基座：`evidence-log`（审计记录）
- 外部依赖：Git CLI（Worker 容器内预装）

## 失败处理

- 合并冲突 → 输出冲突文件列表，标记 `NEEDS_MANUAL_RESOLVE`，通知 Manager
- 分支已存在 → 切换到已有分支，标记 `BRANCH_EXISTS`
- 工作区不干净（有未提交变更）→ 提示先提交或暂存，标记 `DIRTY_WORKTREE`
- 敏感文件检测 → 阻止提交，列出违规文件，标记 `BLOCKED_SENSITIVE`
- Git 操作超时（默认 30s）→ 终止并报 `TIMEOUT`

## 安全边界

- **禁止** `git push --force` 到 main/master 分支
- **禁止** `git reset --hard` 到远程分支
- **禁止** `git clean -f` / `git branch -D`（仅允许 `branch -d` 已合并删除）
- **禁止** `git add -A` / `git add .`（仅允许精确文件暂存）
- 提交前自动扫描 `.env`、`credentials/`、`providers.json`、`*.pem` 等敏感文件，命中则阻断
- 所有操作在 Worker 沙箱容器内执行，不触碰宿主机

## 复用价值

- 所有 Worker 的代码变更流程均依赖本 Skill，是最底层的 L1 基座 Skill
- 安全的 commit message 规范确保团队提交历史一致、可检索
- 防误操作保护机制可复用于任何需要 Git 操作的 Agent 场景

## 协同关系

- **上游**：接收 `code-gen`（修复补丁）、`repo-context`（分支策略）的指令
- **下游**：产出变更记录供 `evidence-log` 审计、`code-search` 追溯
- **并行**：与 `repo-context` 协同（仓库感知提供分支策略，Git 操作执行分支动作）

## 里程碑

- 输出：`GIT_OP_DONE`（操作完成，审计记录已写入）
- 若 `BLOCKED` → 通知 Manager 人工介入审查