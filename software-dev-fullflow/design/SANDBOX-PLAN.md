# AgentTeams 沙箱执行环境方案与实现计划（SANDBOX-PLAN）

> 目标：回答「研发 Worker（Fixer/Tester）要执行代码、跑测试，需要一个沙箱运行环境，在 AgentTeams 里怎么做」。
> 原则：**优先复用阿里官方已有能力，不重复造轮子，不引入第三方框架。**
> 更新日期：2026-08-13

---

## 0. 一句话结论

> **AgentTeams 本身已经自带两层沙箱**：① 每个 Worker 是独立 Docker 容器（天然隔离、无状态、可销毁重建）；② copaw/qwenpaw 运行时内置 `tool_guard` / `file_guard` / `credential_guard` 安全守卫。
> 所以「沙箱运行环境」的 80% 需求**不用新建，直接复用现有容器 + 把安全守卫配好**即可；剩余 20%（要跑更不可信代码 / 更严格隔离）再考虑接入阿里官方 AgentScope Runtime 沙箱。

---

## 1. 阿里官方文档位置（都在，直接可查）

| 来源 | 链接 / 位置 | 内容 | 状态 |
|------|------------|------|------|
| **AgentScope Runtime 沙箱** | https://runtime.agentscope.io/zh/sandbox/sandbox.html | `agentscope-runtime` 包：`BaseSandbox` / `FilesystemSandbox` / `GuiSandbox` / `BrowserSandbox` / `MobileSandbox` / `TrainingSandbox`；后端 Docker(默认)/BoxLite/K8s/FC/ACK；可 MCP 暴露 | ✅ 已发布，可直接用 |
| AgentScope Runtime 沙箱（Java） | https://java.agentscope.io/v2/zh/docs/harness/sandbox.html | 把 agent 的文件操作和命令执行收进隔离环境 | ✅ 已发布 |
| **AgentTeams 官方沙箱规划** | `references/refs/agent-teams/design/AGENTTEAMS-INTERNALS.md` §7.4 | 「对接 NemoClaw 作为安全沙箱后端」标为**规划中** | ⏳ 未落地 |

> 关键信息：AgentTeams 官方把「沙箱后端」定位为 **NemoClaw**，但当前版本还没实现。所以**现在能用的官方沙箱 = AgentScope Runtime 沙箱**（AgentTeams 是 AgentScope 生态的一环，两者天然兼容）。

---

## 2. AgentTeams 现有沙箱机制盘点（= 我们要「复用」的）

### 2.1 第一层：Worker 容器本身（最硬的隔离）

- 每个 Worker = 一个 Docker 容器 / K8s Pod，由 controller 通过 `Worker Backend` 抽象启动（`AGENTTEAMS-INTERNALS.md` §2）。
- **无状态**：所有配置/记忆存在中央 MinIO，Worker 可随时销毁重建（`worker/README.md`: "Workers are stateless ... can be destroyed and recreated at any time without losing state"）。
- 含义：Fixer/Tester 在容器里编译、跑测试，**天然与宿主机/其他 Worker 隔离**，跑坏了 `docker rm` 重来即可。

### 2.2 第二层：copaw/qwenpaw 运行时内置安全守卫

copaw 的 `config.json`（`references/refs/agent-teams/copaw/src/copaw_worker/templates/config.json`）已内置 `security` 段：

```json
{
  "security": {
    "tool_guard":   { "enabled": true, "guarded_tools": [], "denied_tools": [], "custom_rules": [], "disabled_rules": [] },
    "file_guard":   { "enabled": true, "sensitive_files": [] },
    "skill_scanner":{ "mode": "off", "timeout": 30, "whitelist": [] }
  }
}
```

外加运行时 hook（`copaw/src/copaw_worker/hooks/`）：
- `credential_guard.py` —— 凭据守卫（防 Agent 泄露/硬编码密钥）
- `output_sanitizer.py` —— 工具输出脱敏中间件

> **这些就是现成的沙箱控制面**：通过 `denied_tools` 禁高危工具、`sensitive_files` 保护敏感文件、`custom_rules` 自定义规则——零代码，改配置即可。

---

## 3. 三种方案对比

| 方案 | 做法 | 隔离强度 | 复用成本 | 适用场景 |
|------|------|---------|---------|---------|
| **A. 复用 Worker 容器 + 运行时守卫（推荐，首选）** | 代码执行直接发生在 Worker 容器内；用 `tool_guard`/`file_guard` 加固；跑坏重建容器 | 中（容器级） | **极低（改配置/SKILL.md）** | 编译、跑单测/集成测试、静态分析（参赛 Demo 完全够用） |
| **B. 接入官方 AgentScope Runtime 沙箱** | 用 `agentscope-runtime` 起 `BaseSandbox`，通过 `runtime-sandbox-mcp` 暴露为 MCP，Worker 经 mcporter 调用 | 高（可 gVisor/K8s） | 中（装依赖 + 配 MCP + 拉镜像） | 要跑**不可信/第三方代码**、需更强隔离或弹性伸缩 |
| **C. NemoClaw** | 等 AgentTeams 官方落地 | 高 | 高（需改 Go Controller） | 官方未发布，暂不可用 |

---

## 4. 推荐方案 A 的实现计划（分三阶段）

### 阶段一：复用容器 + 配好安全守卫（半天内可完成）

1. **明确「代码执行」归属**：Fixer 在容器内跑编译/类型检查（`code-gen` 的「静态自检」步骤），Tester 在容器内跑测试金字塔（`test-generation` 的「隔离环境执行」步骤）。
2. **加固运行时守卫**（改 copaw 的 `config.json` 模板）：
   - `tool_guard.denied_tools`：列入高危/越权工具（如直接删库、改权限、访问宿主的工具）。
   - `file_guard.sensitive_files`：列入 `.env`、`credentials/`、密钥路径，禁止 Agent 读写。
   - `skill_scanner.mode` 按需从 `off` 打开（扫描 skill 内脚本是否有危险调用）。
3. **约束 skill 安全边界**（改 `skills/code-gen/SKILL.md`、`skills/test-generation/SKILL.md`）：
   - 明确「只在自己容器工作区 + `shared/tasks/{id}/` 内读写，不碰生产数据/凭据」。
   - 明确「编译/测试超时上限、失败重试上限、危险命令需 Manager 审批」。

> **阶段一已完成（2026-08-13）**，产出物：
> - `src/agentteams/security-config.json` —— 声明式安全策略（tool_guard/file_guard/skill_scanner）
> - `src/agentteams/SECURITY-POLICY.md` —— 三层沙箱模型 + security 段语义 + 3 种注入方式
> - `scripts/apply-security-config.ps1` + `scripts/apply-security-in-container.sh` —— 批量注入并重启 Worker 容器
> - `skills/code-gen/SKILL.md` + `skills/test-generation/SKILL.md` —— 安全边界增强（沙箱容器、文件边界、超时、危险命令审批）

### 阶段二：验证隔离有效性（1 天）✅ 已完成（2026-08-14）

- 用「故意跑死循环 / 写越界文件 / 读敏感文件」的坏任务，验证：
  - 容器是否只影响自己（不影响 Manager / 其他 Worker / 宿主机）→ ✅ 文件系统/进程隔离，死循环不影响他方；
  - 守卫是否拦下敏感文件读写、高危命令 → ✅ 15/15 守卫用例通过（file_guard 拦敏感文件 + tool_guard 拦 chmod 777/git push --force/docker rm/rm -rf/curl|bash）；
  - 失败后 `agt delete worker` + 重建是否干净 → ✅ 可删除重建；发现重建后需重新注入 security 段（delete 会清 MinIO 状态）。
- 验证结果沉淀为 `design/SANDBOX-VERIFICATION.md`（参赛评审「安全性」证据）。

### 阶段三（可选，进阶）：接入官方 AgentScope Runtime 沙箱

当需要「跑不可信第三方代码 / 更强隔离 / K8s 弹性」时再上，步骤如下：

1. `pip install agentscope-runtime`
2. 拉取基础镜像（阿里云 ACR）：
   ```bash
   docker pull agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/runtime-sandbox-base:latest
   docker tag agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/runtime-sandbox-base:latest agentscope/runtime-sandbox-base:latest
   ```
3. 用 `runtime-sandbox-mcp` 把沙箱暴露成 MCP 服务：
   ```json
   {
     "mcpServers": {
       "sandbox": {
         "command": "uvx",
         "args": ["--from", "agentscope-runtime", "runtime-sandbox-mcp", "--type=base", "--base_url=http://127.0.0.1:8000"]
       }
     }
   }
   ```
4. 把该 MCP 挂到 Fixer/Tester 的 `Worker.spec.mcpServers`（AgentTeams 会写进 `mcporter-servers.json`，Worker 通过 mcporter 调用 `run_ipython_cell` / `run_shell_command` 等工具）。
5. 后端隔离：默认 Docker；要更强可设 `CONTAINER_DEPLOYMENT` 切换 K8s/FC/ACK，或启用 gVisor。

---

## 5. 与现有 assets 的衔接

| 现有产物 | 沙箱计划怎么接 |
|---------|---------------|
| `src/agentteams/workers.yaml`（6 个 Worker，runtime=copaw） | Fixer/Tester 的代码执行落在各自容器；补 `mcpServers`（阶段三） |
| `skills/code-gen/SKILL.md` | 落地「静态自检」= 容器内编译/类型检查；补安全边界 + 超时 |
| `skills/test-generation/SKILL.md` | 落地「隔离环境执行」= Worker 容器（阶段一）或 `BaseSandbox`（阶段三） |
| `design/AGENTTEAMS-INTERNALS.md` | 引用本文作为「沙箱/安全」专项 |

---

## 6. 风险与对策

| 风险 | 对策 |
|------|------|
| Worker 容器隔离不如专用沙箱强（共享 Docker daemon） | 阶段三接 `agentscope-runtime`（可 gVisor/K8s）；现阶段对参赛 Demo 足够 |
| 跑坏容器污染共享 MinIO 状态 | 代码执行产物只写 `shared/tasks/{id}/`，不写全局；`file_guard` 保护敏感路径 |
| 官方 NemoClaw 落地后方案 A/B 被取代 | 方案 A/B 均为「配置 + MCP 接入」，无深度耦合，可平滑迁移 |

---

## 7. 下一步

- [x] 阶段一：改 copaw `config.json` 安全策略 + 两份 SKILL.md 安全边界（已完成，产出见上）
- [x] 阶段二：跑坏任务验证 + 出 `SANDBOX-VERIFICATION.md`（2026-08-14 完成）
- [ ] （可选）阶段三：接 `agentscope-runtime` + MCP，跑通 `BaseSandbox` 最小 demo
