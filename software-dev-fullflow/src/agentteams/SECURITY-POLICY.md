# 沙箱安全策略落地说明（SECURITY-POLICY）

> 配合 `design/SANDBOX-PLAN.md` 阶段一：把「代码执行沙箱」落到 AgentTeams 的可复用机制上。
> 核心原则：**不碰官方源码，复用 Worker 容器 + copaw 运行时守卫 + Skill 提示词边界三层**。
> 更新日期：2026-08-13

---

## 0. 一句话

Worker 的代码执行（Fixer 编译 / Tester 跑测试）**发生在 Worker 自己的 Docker 容器里**，容器天然隔离；容器内部再用 copaw 运行时的 `security` 段（`security-config.json`）+ Skill 安全边界做第二、三层约束。

---

## 1. 三层沙箱安全模型（= 代码执行归属）

| 层 | 机制 | 谁提供 | 我们怎么做 |
|----|------|--------|-----------|
| **L1 容器隔离** | Worker = 独立 Docker 容器，无状态可重建 | AgentTeams 官方 | 复用，不改。跑坏了 `agt delete worker` 重建 |
| **L2 运行时守卫** | copaw `config.json` 的 `security` 段（tool_guard/file_guard/skill_scanner） | CoPaw 运行时 | 注入 `security-config.json` 的 security 段 |
| **L3 提示词边界** | Skill 的「安全边界」段落注入 Agent 上下文 | 我们 | 增强 `code-gen` / `test-generation` 两份 SKILL.md |

**代码执行归属**：
- Fixer（修复工程师）→ 在容器内跑**编译 / 类型检查 / 静态分析**（`code-gen` 的「静态自检」步骤）。
- Tester（测试验证员）→ 在容器内跑**测试金字塔**（`test-generation` 的「隔离环境执行」步骤）。
- 二者产物只写 `shared/tasks/{id}/`，不碰生产数据、不碰全局配置。

---

## 2. `security-config.json` 字段语义

结构与 copaw 运行时 Pydantic 模型（`copaw/src/matrix/config.py` 的 `SecurityConfig`）**逐字段对齐**，已按容器内实际安装的 copaw 包核验：

| 字段 | 含义 | 我们的取值逻辑 |
|------|------|---------------|
| `tool_guard.enabled` | 工具守卫总开关 | `true` |
| `tool_guard.guarded_tools` | 进入守卫扫描范围的工具名；`null` = 用内置高危默认集（`execute_shell_command`/`read_file`/`write_file`/`edit_file`/`append_file`/`send_file_to_user`/`view_text_file`/`write_text_file`） | `null`（复用内置默认） |
| `tool_guard.denied_tools` | **无条件拒绝**（auto_denied，不给审批）的工具名 | 暂空：内置工具均合法，破坏性动作交给 `custom_rules` 命令级拦截 |
| `tool_guard.custom_rules` | 命令级正则规则（`ToolGuardRuleConfig`） | 补内置规则未覆盖的 `chmod 777` / `git push --force` / `docker rm` |
| `file_guard.sensitive_files` | **精确路径 / 目录前缀**匹配（非 glob），相对路径按工作区根解析 | `.env*`、`credentials/`、`secrets/` + 脚本追加的 `providers.json`/`config.json`/`.copaw.secret` 绝对路径 |
| `skill_scanner.mode` | `block`（拦截）/ `warn`（仅告警，默认）/ `off`（关闭） | `warn`（不误伤内置 skill，靠 tool_guard/file_guard 兜底） |
| `skill_scanner.whitelist` | 免扫描信任 skill（`{skill_name, content_hash, added_at}` 对象） | 我们 5 个核心 skill |

### 关键语义（核验结论）

- **`custom_rules` 每个元素**是对象，字段为 `id`（必填）/`tools`/`params`/`category`/`severity`/`patterns`（正则，`re.IGNORECASE`）/`exclude_patterns`/`description`/`remediation`。`category` 取值见 `GuardThreatCategory`（`command_injection`/`privilege_escalation`/`data_exfiltration`/`resource_abuse` 等）；`severity` 取值 `CRITICAL/HIGH/MEDIUM/LOW/INFO/SAFE`。**非法取值会导致该条规则被静默跳过**。
- **`file_guard.sensitive_files` 不支持 glob**：目录用「结尾 `/` 或已存在目录」识别（`Path.is_relative_to` 前缀匹配），文件用精确绝对路径匹配。因此密钥文件用脚本按 Worker 名动态生成绝对路径注入。
- **内置危险命令规则已存在**（`dangerous_shell_commands.yaml`）：已覆盖 `rm`/`mv`/`curl|bash`/`chmod -R 777 /`/`sudo`/`reboot`/`kill` 等，我们的 `custom_rules` 只补缺口。
- **guard 动作流**：`denied_tools` → `auto_denied`（硬拦）；命中规则产生 findings + 有 `session_id` → `needs_approval`（审批流）；`SENSITIVE_FILE_ACCESS` findings 由 `credential_guard` hook 直接 `auto_denied`。`~/.copaw.secret/`（`SECRET_DIR`）为运行时**默认保护目录**，无需手工加。

---

## 3. 如何把 security 段注入 Worker（3 种方式，按复用程度排序）

### 方式 A：预置 config.json（零改源码，推荐）

bridge.py 的 `_write_config_json` 用 `setdefault` 合并已有 `config.json`，**不会覆盖 `security` 段**。因此只要在 Worker 启动前，把 `security-config.json` 的 `security` 段写进 Worker 工作目录的 `config.json`，即可生效：

```powershell
# 以 fixer Worker 为例（容器名 agentteams-worker-fixer）
# ① 把 security 段合并进容器内的 config.json（路径 .copaw/config.json）
docker exec agentteams-worker-fixer sh -c '
  python3 - <<PY
import json
p="/root/.copaw/config.json"
cfg=json.load(open(p))
cfg["security"]=json.load(open("/tmp/security-config.json"))["security"]
json.dump(cfg, open(p,"w"), indent=2)
PY'
# ② 重启 Worker 容器使配置生效
docker restart agentteams-worker-fixer
```

> 更稳妥：把 `security-config.json` 随 SOUL.md 一样 `docker cp` 进容器再合并。可写成 `scripts/apply-security-config.ps1` 批量执行（对齐已有的 `reinstall-agentteams.ps1` 风格）。

### 方式 B：自定义镜像（打包进 Dockerfile）

在 copaw worker 镜像构建时把 security 段写进默认 `config.json`（改 `references/refs/agent-teams/copaw/Dockerfile` 或镜像层）。适合复赛交「可执行代码包」时固化。

### 方式 C：仅 Skill 提示词边界（最轻，兜底）

不碰 config.json，只靠 L3 的 SKILL.md「安全边界」约束 Agent 行为。**任何情况下都生效**，是前两种的兜底。

---

## 4. 已增强的 Skill 安全边界

- `skills/code-gen/SKILL.md`：编译/静态自检超时上限、失败重试上限、文件系统边界（只写工作区 + `shared/tasks/{id}/`）、危险命令需 Manager 审批。
- `skills/test-generation/SKILL.md`：隔离环境执行细节、超时、不碰生产数据、测试结果落盘为证据。

---

## 5. 验证清单（阶段二）✅ 已完成（2026-08-14）

- [x] 坏任务 1：让 Agent 读 `.env` / `providers.json` → 被 file_guard 拦截（绝对路径凭据 6/6 拦截）
- [x] 坏任务 2：让 Agent 执行 `rm -rf /` / `chmod 777` → 被 tool_guard 拦截（5/5 拦截）
- [x] 坏任务 3：让 Agent 跑死循环 → 被 timeout 掐断（3s），且不影响 Manager / 其他 Worker / 宿主机
- [x] 失败后 `agt delete worker` + 重建 → 干净无残留（重建后需重新注入 security 段）

> 完整验证结果见 `design/SANDBOX-VERIFICATION.md`。

### 两个核验补充（2026-08-14 实测）

1. **file_guard 相对路径条目只保护 `.copaw/` 根**：`.env`/`credentials/`/`secrets/` 相对条目在加载 config 时归一化为 `{WORKING_DIR}/{path}`，**不覆盖 `workspaces/<name>/` 子目录**。故固定凭据（providers.json/config.json/.secret）一律用脚本注入**绝对路径**（已生效）；任务工作区内动态 `.env` 靠 L3 提示词边界兜底。
2. **`delete + rebuild` 后 security 段丢失**：`agt delete worker` 会连同 MinIO 的 `agents/<name>/` 状态一并清理，重建后 security 段回到空态（仅 `mode` 残留）。**restart 场景不受影响**（脚本已 `mc cp` 同步回 MinIO）。重建后需重新执行 `scripts/apply-security-config.ps1 -Only <name>`；复赛交代码包时建议走方式 B（固化进镜像）。
