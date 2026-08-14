# 工具链打通：逆向 API key 驱动 AgentTeams 沙箱执行（TOOLCHAIN-PLAN）

> 目标：用**逆向的 CodeBuddy API key** 驱动 AgentTeams，让研发 Agent 团队在**沙箱容器**里完成实际工作（真正写代码文件，而非只出 markdown 报告）。
> 更新日期：2026-08-14

---

## 0. 一句话结论

> AgentTeams 用 Higress AI 网关做 LLM 中转，路径固定为 `/v1/chat/completions`；逆向 CodeBuddy 端点只认 `/v2/chat/completions`（且强制 stream=true + 需要 X-User-Id/X-Domain header）。**二者无法直连，必须在中间加一个 OpenAI 兼容适配层**。适配层已实现并验证通过。

---

## 1. 工具链全景（现状 vs 目标）

```
[用户/需求] → [Manager Loop 调度] → [Agent Teams Worker] → [沙箱容器工具] → [落盘网站文件]
     ↓                  ↓                    ↓                    ↓
 [逆向 API key]   [LLM 接入点: Higress]   [execute_shell_command]   [输出]
  copilot.tencent   → 当前指 DeepSeek        write_file/edit_file
  .com/v2            → 目标指向适配层
```

| 环节 | 现状 | 状态 |
|------|------|:---:|
| 1. 逆向 API key | `src/loop/workbuddy_client.py` 已实现，`.env` 已配好 | ✅ 可用 |
| 2. LLM 接入点 | Controller `AGENTTEAMS_OPENAI_BASE_URL=https://api.deepseek.com/v1`（指向 DeepSeek 官方） | ⚠️ 需切到适配层 |
| 3. 路径/协议 | 逆向端点 `/v2` + stream=true 必须；AgentTeams 网关走 `/v1` | ⚠️ 需适配层桥接 |
| 4. 沙箱工具 | copaw 内置 `execute_shell_command`/`write_file`/`edit_file`，容器内直接执行 | ✅ 无需改 |
| 5. 落盘 | Worker 写 `~/.copaw/workspaces/default`，MinIO 同步 | ✅ 需取回本地 |

---

## 2. 关键断点（已实测确认）

### 2.1 逆向端点特性（`src/loop/verify_reverse_api.py` 实测）

| 测试项 | 结果 |
|--------|------|
| `/v2/chat/completions` + stream=true（基线） | ✅ 200，正常返回 |
| `/v2/chat/completions` + stream=false | ❌ 400 `11101 Non-stream not supported`（stream 必须） |
| `/v1/chat/completions`（任意 header） | ❌ 404 `Route Not Found`（只有 /v2 路由） |
| 认证 | Bearer + `X-User-Id` + `X-Domain`（非纯 Bearer） |

**结论**：逆向端点只暴露 `/v2/chat/completions`，且强制 stream、需自定义 header。AgentTeams 网关（`/v1` + 纯 Bearer）**无法直连**。

### 2.2 AgentTeams LLM 接入机制

- 所有 Manager/Worker 通过 **Higress AI 网关**（数据面 8080）调用 LLM，端点 `AGENTTEAMS_AI_GATEWAY_URL/v1/chat/completions`。
- Controller 通过环境变量配置 provider 上游：
  - `AGENTTEAMS_LLM_PROVIDER=openai-compat`
  - `AGENTTEAMS_OPENAI_BASE_URL=<上游端点>`
  - `AGENTTEAMS_LLM_API_KEY=<上游key>`
- 当前值：`OPENAI_BASE_URL=https://api.deepseek.com/v1`、`DEFAULT_MODEL=deepseek-v4-flash`（DeepSeek 官方）。
- **关键**：`deepseek-v4-flash` 不是 DeepSeek 官方标准模型名（它更像 CodeBuddy 逆向端点支持的模型），但配置如此，需在切到逆向 key 后统一验证。

---

## 3. 打通方案：加 OpenAI 兼容适配层

```
Manager/Worker
   → Higress 网关 (8080)  /v1/chat/completions
   → 适配层 reverse_gateway.py (宿主 9001)
      · 强制 stream=true
      · 注入 X-User-Id/X-Domain header
   → 逆向端点 copilot.tencent.com/v2/chat/completions
```

### 3.1 适配层已实现并验证

- 文件：`src/loop/reverse_gateway.py`（FastAPI，监听 `0.0.0.0:9001`）
- 端点：
  - `GET /v1/models` → 返回逆向端点支持的模型列表
  - `POST /v1/chat/completions` → 透传 SSE 流
- 复用 `workbuddy_client.py` 的 auth 加载逻辑（Bearer + X-User-Id + X-Domain）
- **已验证**：容器内 `host.docker.internal:9001` 可访问；`/v1/chat/completions` 返回标准 OpenAI 兼容 SSE（内容正确透传）。

### 3.2 接入 AgentTeams（改 controller 配置）

Controller 环境变量改为（需重建 controller 容器使配置生效）：
```powershell
$env:AGENTTEAMS_LLM_PROVIDER = "openai-compat"
$env:AGENTTEAMS_OPENAI_BASE_URL = "http://host.docker.internal:9001/v1"  # 指向适配层
$env:AGENTTEAMS_DEFAULT_MODEL = "deepseek-v4-flash"
$env:AGENTTEAMS_LLM_API_KEY = "<任意非空>"   # 适配层不校验，透传逆向凭据
```

> **不重建 controller 的替代方案**：Manager/Worker 的 `custom_providers["agentteams-gateway"].baseUrl` 直接指向 `http://host.docker.internal:9001/v1`（绕过 Higress 网关）。影响面小但需分别改 manager + 每个 worker，且会被 controller 覆盖。

---

## 4. 沙箱执行（团队如何在沙箱里产出文件）

- Worker 容器（如 `agentteams-worker-fixer`）内，copaw 运行时内置原生工具：
  - `execute_shell_command` / `write_file` / `edit_file` / `read_file`
- 工具守卫：`tool_guard` / `file_guard`（见 `SECURITY-POLICY.md`），已加固。
- 文件落盘：`~/.copaw/workspaces/default`（Worker 容器内），经 MinIO 同步到 `agentteams-fs`。
- 取回本地：`docker cp agentteams-worker-<name>:<path> <本地路径>` 或从 MinIO / `C:\Users\34239\agentteams-manager` 取。

---

## 5. 执行清单（打通后跑建站任务）

1. [x] 逆向 key 可用性验证 → `src/loop/verify_reverse_api.py`
2. [x] 适配层实现 + 本地验证 → `src/loop/reverse_gateway.py`
3. [ ] 切换 controller 配置指向适配层（重建 controller，保留数据卷）
4. [ ] 验证 Manager 能用逆向 key 响应（发一条真实消息）
5. [ ] 派「MBTI 式 AI 使用测评网站」建站任务，让 fixer 在沙箱里写文件
6. [ ] 取回网站文件，本地运行看效果

---

## 6. 风险与对策

| 风险 | 对策 |
|------|------|
| 重建 controller 短暂中断 | 数据在 volume + MinIO，无状态可恢复；先保存当前环境变量快照 |
| 逆向端点模型名与 AgentTeams 期望不一致 | 适配层 `MODEL_MAP` 做映射；`DEFAULT_MODEL` 保持 `deepseek-v4-flash` |
| 逆向 key 速率/配额限制 | 团队任务拆小，控制 token；适配层透传 usage |
| `deepseek-v4-flash` 在 DeepSeek 官方不存在（当前配置可疑） | 正好切到逆向 key，由适配层转发到真正支持该模型的逆向端点 |
