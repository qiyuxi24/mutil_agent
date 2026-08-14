# 研发 Agent 团队工具链设计（TOOLCHAIN）

> GOAI · 赛道三「软件研发全流程协同」· 协同基点 AgentTeams
> 本文定义 6 个职能 Worker 的**真实可执行工具链**，回答「Worker 除了声明式 Skill，还靠什么真正干活」。
> 前置：沙箱执行环境（`SANDBOX-VERIFICATION.md`）已保证 Worker 在隔离容器内安全跑工具。
> 更新日期：2026-08-14

---

## 一、为什么需要"工具链"

Skill 是**指令**（告诉 Agent 做什么、按什么流程做），不是**能力**（Agent 真正调用的函数/脚本/API）。评审维度「工程落地 20%」明确要求：fixer 要能在真实仓库完成「改代码 → 跑测试 → 生成 PR」，tester 要用**确定性工具**当裁判，而非 LLM 自评。

工具链 = 把「指令」落到「可执行能力」的那一层。缺了它，6 个 Worker 只是"会写文档的聊天机器人"，不是"能交付代码的研发团队"。

---

## 二、三层工具链模型

每个 Worker 的能力栈由三层组成，从内到外可靠性递增、安全性递减：

```
┌─────────────────────────────────────────────────────────┐
│ L3 · Skill 可执行 scripts/   —— 确定性任务脚本（补丁检查/测试闸门）  │
│      归属：code-gen / test-generation 的 scripts/ 目录         │
├─────────────────────────────────────────────────────────┤
│ L2 · MCP 服务器              —— 外部工具链经 Higress 网关接入      │
│      归属：Worker.spec.mcpServers → mcporter → 网关 → REST API   │
│      （github / code-scan / test-platform / ci）               │
├─────────────────────────────────────────────────────────┤
│ L1 · copaw 运行时内置工具     —— shell + 文件读写（沙箱已验证）      │
│      归属：所有 Worker 默认，tool_guard/file_guard 保护           │
└─────────────────────────────────────────────────────────┘
```

### L1 · copaw 运行时内置工具（默认，已闭环）

- **能力**：`execute_shell_command`（timeout 默认 60s）、文件读写、git 基础操作。
- **安全性**：沙箱阶段已验证 —— `tool_guard` 拦危险命令（`rm -rf /`、`chmod 777`、`git push --force`、`curl|bash`），`file_guard` 拦敏感文件（`.env`/`providers.json`/`config.json`）。
- **定位**：这是「本地最小能力」，覆盖简单文件操作与本地构建，但**不具备**跨系统真实工具（CI 触发、代码托管 PR、扫描平台、测试平台）。

### L2 · MCP 服务器（外部工具链，核心缺口）

通过阿里官方 `Worker.spec.mcpServers` → `GenerateMcporterConfig` → `mcporter-servers.json` → Higress AI 网关 → REST API 的机制，把外部工具链以 MCP 形式暴露给 Worker（工具调用格式 `<server>.<tool>`）。接入机制详见 §五。

| MCP Server | 类型 | 工具 | 服务对象 | 状态 |
|-----------|------|------|---------|------|
| `github` | 官方内置代理（`mcp-github.yaml` 40+ 工具） | repos/issues/PRs/代码搜索/文件读写 | Aggregator / RootCause / Fixer | 模板官方自带，需注册 |
| `code-scan` | 自建 REST → MCP（`mcp-code-scan.yaml`） | start_scan / get_scan_result / list_open_issues / get_issue_detail | Fixer | 模板已就绪 |
| `test-platform` | 自建 REST → MCP（`mcp-test-platform.yaml`） | 测试执行 / 覆盖率 / 静态分析 | Tester | 模板待补 |
| `ci` | 自建 REST → MCP（可选） | 触发流水线 / 查询构建状态 / 回滚 | Releaser | 可选 |

### L3 · Skill 可执行 scripts/（确定性闸门，核心缺口）

Skill 的 `scripts/` 目录放**确定性任务脚本**，由 Skill 指令在需要时调用，产出可审计的机器结果（非 LLM 判断）：

| Skill | scripts/ 内容 | 作用 |
|-------|--------------|------|
| `code-gen` | `check-patch-integrity.py` | 补丁完整性静态检查（文件是否存在、语法/类型、diff 一致性） |
| `test-generation` | `verify_test_gate.py` | 确定性测试闸门（跑测试 + 静态检查 + 覆盖率，产出 PASS/FAIL） |

> 这一层直接对齐 TODO「确定性验证闸门」+「Skill 可执行化」两项：把 `manager.py::_verify` 的 LLM 自评替换为真实脚本产出。

---

## 三、6 Worker 工具清单分配矩阵

| Worker | 职责 | L1 内置（默认） | L2 MCP（spec.mcpServers） | L3 脚本（Skill scripts/） |
|--------|------|----------------|--------------------------|--------------------------|
| **Aggregator** 缺陷聚合员 | 聚合多源缺陷/需求 | shell/文件 | `github`（拉 Issue/日志） | —（issue-parsing 无脚本需求） |
| **RootCause** 根因定位员 | RCA + 影响面 | shell/文件 | `github`（代码搜索/读文件/blame） | — |
| **Fixer** 修复工程师 | 编码修复 | shell/文件/git | `github`（分支/PR）+ `code-scan`（提交扫描） | `code-gen/scripts/check-patch-integrity.py` |
| **Tester** 测试验证员 | 质量门禁 | shell/文件 | `test-platform`（跑测试/覆盖率/静态分析） | `test-generation/scripts/verify_test_gate.py` |
| **Releaser** 发布确认员 | 发布/灰度/回滚 | shell/文件 | `ci`（触发流水线/查询状态/回滚，可选） | — |
| **Retrospector** 复盘沉淀员 | 复盘/知识沉淀 | shell/文件 | —（用内置 RAG 工具写知识库） | — |

**分配原则**：
1. **只给"真实要调外部系统"的 Worker 挂 MCP**，避免过度授权（Consumer 授权是 REPLACE，越少越安全）。
2. **Fixer/Tester 是评审硬门禁**，必须挂真实 MCP + 确定性脚本；Aggregator/RootCause 挂 `github` 保证"读真实仓库"；Retrospector 用内置 RAG 即可。
3. **Releaser 的 `ci` 为可选**：初赛无真实 CI 平台时用 L1 shell + `release-gate` skill 兜底，复赛接入真实流水线再补。

---

## 四、工具调用数据流（以 Fixer 提交代码扫描为例）

```
fixer (copaw) 决定调用 code-scan.start_scan
        │
        ▼
mcporter 读取 /root/.copaw-worker/fixer/.copaw/mcporter.json
        │   └─ { mcpServers: { "code-scan": { url, transport, headers:{Authorization:"Bearer <gatewayKey>"} } } }
        ▼
mcporter 向 Higress 网关发请求（携带 Bearer gatewayKey）
        │
        ▼
Higress 网关 → 校验 Consumer 授权（REPLACE 后的 allowTools）
        │
        ▼
转发到真实 REST API（api.scan.example.com/v1/scans，注入 {{.config.accessToken}}）
        │
        ▼
返回扫描任务 ID → fixer 继续 get_scan_result 轮询结果
```

关键点：**真实 API key 只存网关**（`{{.config.accessToken}}`），Worker 容器只持网关 key（`gatewayKey`），凭据不落地 Worker。

---

## 五、MCP 接入机制（对齐官方 setup-mcp-server.sh）

### 5 步流程

1. **注册 DNS service source**（云模式）/ 本地默认 `aigw-local.agentteams.io`。
2. **替换 YAML 模板凭据**：把 `mcp-<name>.yaml` 里的 `accessToken: ""` 替换为真实值（统一凭据键）。
3. **upsert MCP Server**：`PUT /v1/mcpServer`（type: OPEN_API），生成终结点 `http://{gateway}:8080/mcp-servers/{name}/mcp`。
4. **更新 Manager 配置**：写入 `config/mcporter.json`。
5. **授权 + 同步**：授权所有/指定 Worker（Consumer 授权是 **REPLACE**，include ALL consumers；`allowTools` 做工具级控制）→ 更新各 Worker 的 `mcporter.json` → `mc cp` 推回 MinIO（`${AGENTTEAMS_STORAGE_PREFIX}/agents/{wname}/config/mcporter.json`）→ `agentteams-sync` 触发 Worker 拉取。

### mcporter 配置格式

```json
{
  "mcpServers": {
    "code-scan": {
      "url": "http://aigw-local.agentteams.io:8080/mcp-servers/code-scan/mcp",
      "transport": "http",
      "headers": { "Authorization": "Bearer <gatewayKey>" }
    }
  }
}
```

### 官方机制代码落点（源码索引）

| 机制 | 源码位置 |
|------|---------|
| `Worker.spec.mcpServers` 字段 | `agentteams-controller/api/v1beta1/types.go`（`MCPServer{Name,URL,Transport}`） |
| mcporter 配置生成 | `agentteams-controller/internal/agentconfig/mcporter.go`（`GenerateMcporterConfig`） |
| MCP 管理 skill | `manager/agent/skills/mcp-server-management/`（`SKILL.md` + `setup-mcp-server.sh`） |
| 官方 MCP 模板 | `mcp-server-management/references/mcp-github.yaml`（GitHub 40+ 工具） |

---

## 六、落地状态

| 项 | 状态 |
|----|------|
| 工具链接入胶水层（`src/agentteams/mcp/README.md`） | ✅ 已就绪 |
| `register-mcp.ps1` 一键注册脚本（proxy/yaml/auth 三模式） | ✅ 已就绪 |
| `mcp-code-scan.yaml`（Fixer 代码扫描） | ✅ 已就绪 |
| `mcp-test-platform.yaml`（Tester 测试平台） | ⬜ 待补（本文档配套补齐） |
| `workers.yaml` 全量 `spec.mcpServers` | ⬜ 待补（fixer/tester 已有，其余补 github/ci） |
| `code-gen/scripts/check-patch-integrity.py` | ⬜ 待补 |
| `test-generation/scripts/verify_test_gate.py` | ⬜ 待补 |
| MCP 实际注册到 Higress + 授权 Worker | ⬜ 复赛环境执行（需真实 API key） |

---

## 七、注意事项

- **凭据只存网关**：YAML 里 `accessToken: ""`，真实 key 由脚本注入，**禁止写进 YAML 提交**（与 `mcp-code-scan.yaml` 一致）。
- **授权是 REPLACE**：`allowTools` 做工具级最小授权，避免 Fixer 越权调用 Tester 的测试工具。
- **stdio 不支持**：现有 MCP 只能用 `http`/`sse`，工具链后端必须是 HTTP 可访问的 REST/MCP 服务。
- **MinIO 同步**：授权后必须 `mc cp` 推回 MinIO，否则 Worker restart 时 `mirror_all()` 会用旧配置覆盖（与沙箱阶段 `apply-security-in-container.sh` 教训一致）。
- **云模式（SAE）**：`register-mcp.ps1` 不可用，改走阿里云 AI 网关控制台手动 upsert。

---

## 文档索引

- 沙箱执行环境：`design/SANDBOX-VERIFICATION.md`
- MCP 集成机制（官方）：`design/MCP-INTEGRATION.md`
- 工具链胶水层：`src/agentteams/mcp/README.md`
- Worker 声明：`src/agentteams/workers.yaml`
- 一键注册脚本：`scripts/register-mcp.ps1`
- Skill 分配矩阵：`skills/ASSIGNMENT-MATRIX.md`
- 待办清单：`TODO.md`
