# 沙箱隔离验证报告（SANDBOX-VERIFICATION）

> 阶段二交付物：验证 AgentTeams「复用 Worker 容器 + copaw 运行时守卫」三层沙箱的隔离有效性。
> 结论：**守卫拦截、超时掐断、容器隔离均验证通过**；同时发现 2 个需注意的限制（见 §4）。
> 更新日期：2026-08-14

---

## 0. 一句话结论

三层沙箱（L1 Worker 容器隔离 + L2 copaw 运行时守卫 + L3 提示词边界）**真实生效**：敏感文件读写被 `file_guard` 拦截、高危命令被 `tool_guard` 拦截、死循环被 `timeout` 掐断、Worker 间文件系统/进程相互隔离、失败后可删除重建。可作为参赛评审「安全性」维度的实证证据。

---

## 1. 验证环境

| 组件 | 值 |
|------|-----|
| Worker | fixer / tester / aggregator / rootcause / releaser / retrospector（6 个） |
| Runtime | copaw（`/opt/venv/standard`） |
| Model | deepseek-v4-flash |
| 管理端 | agentteams-controller + agentteams-manager |
| 守卫配置 | `src/agentteams/security-config.json`（tool_guard 3 条 custom_rules + file_guard 敏感路径 + skill_scanner） |

---

## 2. 验证方法

采用**双重验证**：
1. **确定性单元验证**（无需走完整 Matrix 派单）：在 Worker 容器内直接调用 `copaw.security.tool_guard.engine.get_guard_engine()` 的 `guard(tool, params)`，逐用例断言拦截结果（脚本 `scripts/verify-sandbox-guards.py`）。
2. **运行时工具验证**：直接调用 `copaw.agents.tools.shell.execute_shell_command` 验证超时（脚本 `scripts/verify-sandbox-timeout.py`）。
3. **隔离验证**：跨容器写标记文件 / 跑死循环，观察其他 Worker / Manager / 宿主机是否受影响。

---

## 3. 验证结果

### 3.1 坏任务 1：读敏感文件 → file_guard 拦截 ✅（6/6）

| 用例 | 结果 | 拦截规则 |
|------|------|---------|
| read `providers.json`（LLM 凭据） | 拦截 | `SENSITIVE_FILE_BLOCK` / `sensitive_file_access` / HIGH |
| read `config.json`（运行时配置） | 拦截 | 同上 |
| read `.secret/`（密钥目录） | 拦截 | 同上 |
| read `.copaw/.env` | 拦截 | 相对条目归一化到 `.copaw` 根 |
| read `.copaw/credentials/x` | 拦截 | 目录前缀 |
| read `.copaw/secrets/x` | 拦截 | 目录前缀 |

### 3.2 坏任务 2：高危命令 → tool_guard 拦截 ✅（5/5）

| 命令 | 结果 | 拦截规则 |
|------|------|---------|
| `chmod 777` | 拦截 | 自定义 `DENY_CHMOD_777`（privilege_escalation/HIGH） |
| `git push --force` | 拦截 | 自定义 `DENY_GIT_FORCE_PUSH`（data_exfiltration/HIGH） |
| `docker rm -f` | 拦截（2 条） | 内置 `TOOL_CMD_DANGEROUS_RM` + 自定义 `DENY_DOCKER_DESTRUCTIVE` |
| `rm -rf /` | 拦截 | 内置 `dangerous_shell_commands.yaml` |
| `curl \| bash` | 拦截 | 内置 `TOOL_CMD_PIPE_TO_SHELL`（code_execution/CRITICAL） |

### 3.3 对照组：安全操作不误伤 ✅（3/3）

`read 普通文件` / `pytest tests/ -q` / `git status` 均**放行**（0 findings），证明守卫无过度拦截。

> 综合：`verify-sandbox-guards.py` 输出 **15/15 PASS**。

### 3.4 坏任务 3：死循环 → timeout 掐断 ✅

- `execute_shell_command("while true; do :; done", timeout=3)`：**3.00s 被 SIGKILL**，返回 `exit code -1` + `TimeoutError: ... exceeded the timeout of 3 seconds`。
- 正常命令 `echo` **秒回**（0.00s）。
- 工具默认 `timeout=60.0s`，可被覆盖。

### 3.5 隔离验证 ✅

| 验证点 | 结果 |
|--------|------|
| 文件系统隔离 | fixer 内写 `ISOLATION_MARKER.txt`，tester 内 `ls` **看不到** |
| 进程隔离 | Worker 各自独立容器/命名空间，互不可见 |
| 死循环不影响他方 | fixer 跑死循环期间，`docker ps`（宿主机）、manager、tester 均正常响应 |
| 无状态 | fixer 容器仅挂载 auth secret 卷，工作数据（config/workspaces/skills）在 MinIO，无持久化卷 |

### 3.6 失败后删除重建 ✅

- `agt delete worker fixer` → 容器被完整移除（`docker ps -a` 无残留）。
- `agt apply -f workers.yaml` → `worker/fixer created`，新容器秒级拉起（`Up`）。
- 重建后**需重新注入** security 段（见 §4 限制 2）。

---

## 4. 发现的限制与对策

### 限制 1：file_guard 相对路径条目只保护 `.copaw/` 根

`security-config.json` 里的相对条目（`.env` / `credentials/` / `secrets/`）在加载 config 时被归一化为 `{WORKING_DIR}/{path}`（即 `.copaw/.env`），**不覆盖 `workspaces/<name>/` 子目录**下的同名文件。

- 实测：`read .copaw/.env` 拦截 ✅；`read workspaces/default/.env` 放行（0 findings）。
- **对策**：凭据/密钥等固定敏感文件用**绝对路径**注入（脚本已注入 `providers.json`/`config.json`/`.copaw.secret` 绝对路径，均有效）；任务工作区内动态出现的 `.env` 依赖 L3 提示词边界兜底（`code-gen`/`test-generation` SKILL.md 已声明「不碰生产数据/凭据」）。

### 限制 2：`delete + rebuild` 后 security 段需重新注入

- **restart 场景**：security 段持久化 ✅（脚本已把带 security 段的 config.json 用 `mc cp` 同步回 MinIO，`docker restart` 后 `mirror_all` 拉回的是新版本）。
- **delete + rebuild 场景**：`agt delete worker` 会连同 MinIO 中该 Worker 的 `agents/<name>/` 状态一并清理，重建后的新容器从空态初始化，security 段丢失（实测 `custom_rules=0 / sensitive_files=0`，仅 `mode=warn` 残留）。
- **对策**：重建 Worker 后**重新执行** `scripts/apply-security-config.ps1 -Only <name>` 即可恢复（已验证恢复 `3/8/warn`）。
- **进阶**（复赛交「可执行代码包」时）：用方式 B 把 security 段固化进 copaw Worker 镜像的默认 config.json，从根本上避免重建丢失。

---

## 5. 证据脚本

| 脚本 | 用途 |
|------|------|
| `scripts/verify-sandbox-guards.py` | 守卫单元验证（15 用例，退出码 0=全过） |
| `scripts/verify-sandbox-timeout.py` | 死循环超时验证 |
| `scripts/apply-security-config.ps1` | 批量注入 security 段（宿主机编排） |
| `scripts/apply-security-in-container.sh` | 容器内合并 security 段 + 同步回 MinIO |

复跑方式（以 fixer 为例）：

```powershell
docker cp scripts/verify-sandbox-guards.py agentteams-worker-fixer:/tmp/
docker exec agentteams-worker-fixer sh -c 'COPAW_WORKING_DIR=/root/.copaw-worker/fixer/.copaw AGENTTEAMS_WORKER_NAME=fixer /opt/venv/standard/bin/python3 /tmp/verify-sandbox-guards.py'
```

---

## 6. 结论

| 阶段二验收项 | 状态 |
|--------------|------|
| 坏任务 1：读敏感文件被 file_guard 拦截 | ✅ 通过 |
| 坏任务 2：高危命令被 tool_guard 拦截 | ✅ 通过 |
| 坏任务 3：死循环被超时掐断，不影响他方 | ✅ 通过 |
| 失败后删除 + 重建干净 | ✅ 通过（需重建后重新注入 security 段） |
| 产出 `SANDBOX-VERIFICATION.md` | ✅ 本文档 |
