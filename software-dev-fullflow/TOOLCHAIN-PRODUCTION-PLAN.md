# 生产环境工具链整合计划（对标 Codex 完整度）

> 目标：让 6 Agent 团队拥有 Codex 级别的完备工具链
> 执行方式：**多窗口并行**，每个窗口独立完成自己的任务，完成后打勾
> 创建日期：2026-08-16

---

## 当前状态 vs 目标

| 工具类别 | 当前 | 目标（= Codex 级别） |
|----------|------|---------------------|
| 文件读写 | `read_file`/`write_file`/`edit_file`（copaw 内置） | ✅ 已有 |
| Shell 执行 | `execute_shell_command`（copaw 内置） | ✅ 已有 |
| Git 操作 | `git-operations` **空壳** | 完整的分支/commit/diff/blame/PR |
| 代码搜索 | `code-search` **空壳** | ripgrep + 语义搜索 |
| 仓库感知 | `repo-context` **空壳** | 模块依赖图、构建入口识别 |
| 知识检索 | `knowledge-rag` **空壳** | RAG 检索历史经验 |
| 证据日志 | `evidence-log` **空壳** | 结构化证据记录 |
| 代码扫描 | MCP 模板已定义，后端**未启动** | 代码扫描服务运行中 |
| 测试平台 | MCP 模板已定义，后端**未启动** | 测试执行+覆盖率 |
| CI/CD | MCP 模板已定义，**空壳** | 流水线触发/审批/回滚 |
| 审批流 | ✅ 完整实现 | ✅ 已有 |
| 沙箱安全 | ✅ 三层沙箱 | ✅ 已有 |
| 模型路由 | 直连 DeepSeek API | Higress AI Gateway 统一路由 |

---

## 并行执行总览

```
窗口 A：阶段一 Skill 补全（5 个文件，纯文档）──────────┐
                                                       ├──→ 窗口 C：阶段三 网关注册
窗口 B：阶段二 MCP 后端启动（2 个 Python 服务）────────┘

窗口 D：阶段四 模型路由切换（独立，可随时做）

窗口 E：阶段五 CLI→REST 改造（依赖阶段三完成后）

窗口 F：阶段六 CI/CD + UModel + 沙箱（独立，可并行）

窗口 G：阶段七 容器化 + Dashboard + 验证（最后收尾）
```

---

---

# 窗口 A：阶段一 · Skill 空壳补全（5 个文件）

> 对标已有完整 Skill 格式：[skills/code-gen/SKILL.md](skills/code-gen/SKILL.md)
> 每个 Skill 必须包含 9 个字段：名称/用途/输入输出/调用条件/依赖工具/失败处理/安全边界/复用价值/协同关系

## A.1 git-operations — Git 操作

**文件**：[skills/git-operations/SKILL.md](skills/git-operations/SKILL.md)

**需覆盖的能力**：
- `git checkout -b` 创建功能分支
- `git diff` 生成变更对比
- `git add` + `git commit` 安全提交（带规范 commit message）
- `git log` / `git blame` 历史追溯
- `git branch` 分支管理
- 安全边界：禁止 `git push --force` 到 main/master、禁止 `git reset --hard` 到远程分支

**验证**：`python scripts/verify-skill-refs.py` → git-operations 不再报告缺失

---

## A.2 repo-context — 仓库结构感知

**文件**：[skills/repo-context/SKILL.md](skills/repo-context/SKILL.md)

**需覆盖的能力**：
- 识别项目模块划分（目录结构 → 模块边界）
- 构建依赖图（import 分析 → 模块间依赖关系）
- 定位构建入口（`setup.py` / `Makefile` / `package.json` / `go.mod` 等）
- 变更影响范围分析（改了文件 A → 哪些文件受影响）
- 技术栈识别（语言/框架/构建工具）

**验证**：`python scripts/verify-skill-refs.py` → repo-context 不再报告缺失

---

## A.3 code-search — 代码搜索

**文件**：[skills/code-search/SKILL.md](skills/code-search/SKILL.md)

**需覆盖的能力**：
- `ripgrep` 全文搜索（正则、文件类型过滤、上下文行）
- 语义搜索（embedding 向量相似度匹配）
- 符号定位（函数/类/变量定义跳转）
- 调用链追踪（谁调用了这个函数 → 这个函数调用了谁）
- 引用查找（全局搜索某个符号的所有引用位置）

**验证**：`python scripts/verify-skill-refs.py` → code-search 不再报告缺失

---

## A.4 knowledge-rag — 知识检索

**文件**：[skills/knowledge-rag/SKILL.md](skills/knowledge-rag/SKILL.md)

**需覆盖的能力**：
- 从知识库（`shared/knowledge/`）检索历史经验
- 相似问题匹配（当前 bug → 历史上类似问题及其解法）
- 知识写入（复盘后将经验结构化存入知识库）
- 检索策略：关键词匹配 + 语义相似度，优先语义结果
- 与 `context.py` 的 SemanticMemorySearch 协同

**验证**：`python scripts/verify-skill-refs.py` → knowledge-rag 不再报告缺失

---

## A.5 evidence-log — 证据日志

**文件**：[skills/evidence-log/SKILL.md](skills/evidence-log/SKILL.md)

**需覆盖的能力**：
- 结构化记录 Agent 执行的每一步（输入/输出/决策理由）
- 证据链追溯（根因 → 修复 → 测试 → 发布，每步可审计）
- 日志格式对齐 [AuditLogger](src/loop/audit_logger.py)（timestamp/trace_id/agent_id/event_type/action/result）
- 落盘路径：`shared/tasks/{id}/evidence.jsonl`

**验证**：`python scripts/verify-skill-refs.py` → evidence-log 不再报告缺失

---

## A 窗口完成标准
- [ ] 5 个 SKILL.md 全部内容完整，不再有"初赛占位空壳"标记
- [ ] `python scripts/verify-skill-refs.py` → ALL PASS
- [ ] 格式对齐 [skills/code-gen/SKILL.md](skills/code-gen/SKILL.md)（9 字段齐全）

---

---

# 窗口 B：阶段二 · MCP 工具链后端启动

## B.1 修复依赖版本冲突

当前 `agentscope 2.0.6` 与 `mcp 1.29.0` 不兼容，`import mcp.types` 失败。

```powershell
# 在项目 .venv 中执行
.\.venv\Scripts\Activate.ps1
pip install "mcp<1.0"
```

**验证**：
```powershell
python -c "from agentscope.tool import FunctionTool; print('OK')"
```

---

## B.2 启动代码扫描服务

**文件**：[src/agentteams/toolchains/code_scan_service.py](src/agentteams/toolchains/code_scan_service.py)
**端口**：9100
**内核**：[src/agentteams/toolchains/core.py](src/agentteams/toolchains/core.py) 的 `run_code_scan()`

```powershell
# 终端 B-1
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m src.agentteams.toolchains.code_scan_service --port 9100
```

**验证**：
```powershell
# 另一个终端测试
curl -X POST http://localhost:9100/v1/scans -H "Content-Type: application/json" -d '{"repo":"test/repo","branch":"main"}'
```

---

## B.3 启动测试平台服务

**文件**：[src/agentteams/toolchains/test_platform_service.py](src/agentteams/toolchains/test_platform_service.py)
**端口**：9200
**内核**：[src/agentteams/toolchains/core.py](src/agentteams/toolchains/core.py) 的 `evaluate_test_gate()`

```powershell
# 终端 B-2
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python -m src.agentteams.toolchains.test_platform_service --port 9200
```

**验证**：
```powershell
curl -X POST http://localhost:9200/v1/runs -H "Content-Type: application/json" -d '{"repo":"test/repo","branch":"main"}'
```

---

## B 窗口完成标准
- [ ] 依赖修复：`from agentscope.tool import FunctionTool` 不报错
- [ ] 代码扫描服务 `localhost:9100` 可访问，`/v1/scans` POST 返回 200
- [ ] 测试平台服务 `localhost:9200` 可访问，`/v1/runs` POST 返回 200
- [ ] 确定性内核单测通过：`python -m pytest tests/test_toolchains.py -q`

---

---

# 窗口 C：阶段三 · 工具链网关注册（依赖阶段二完成）

## C.1 注册 MCP 到 Higress 网关

```powershell
# 执行注册脚本
cd software-dev-fullflow
.\scripts\register-mcp.ps1
```

该脚本会将 3 个 MCP 模板注册到 Higress：
- `code-scan` → `host.docker.internal:9100`
- `test-platform` → `host.docker.internal:9200`
- `ci` → 暂用 L1 shell 兜底（复赛接真实 CI）

---

## C.2 验证 Worker 的 MCP 挂载生效

```powershell
# 检查 fixer 容器的 mcporter.json 是否包含 code-scan
docker exec agentteams-worker-fixer cat /root/.copaw/mcporter.json

# 检查 tester 容器的 mcporter.json 是否包含 test-platform
docker exec agentteams-worker-tester cat /root/.copaw/mcporter.json
```

**预期输出**：JSON 中包含 `code-scan` / `test-platform` 的 server 条目，带 `Authorization: Bearer <gatewayKey>`。

---

## C.3 重新 apply workers.yaml（使新 MCP 生效）

```powershell
docker cp src/agentteams/workers.yaml agentteams-controller:/tmp/workers.yaml
docker exec agentteams-controller agt apply -f /tmp/workers.yaml
```

---

## C 窗口完成标准
- [ ] `register-mcp.ps1` 执行成功
- [ ] `docker exec agentteams-worker-fixer cat /root/.copaw/mcporter.json` 包含 code-scan
- [ ] `docker exec agentteams-worker-tester cat /root/.copaw/mcporter.json` 包含 test-platform
- [ ] `agt apply -f workers.yaml` 6 Worker 全部 configured

---

---

# 窗口 D：阶段四 · 模型路由切换（独立，可随时做）

## D.1 启动适配层

```powershell
# 终端 D
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
python src/loop/reverse_gateway.py
```

监听 `0.0.0.0:9001`，提供 `/v1/chat/completions` → 透传到逆向端点。

**验证**：
```powershell
curl http://localhost:9001/v1/models
```

---

## D.2 切换 Controller 配置

```powershell
# 先备份当前配置
docker inspect agentteams-controller --format '{{range .Config.Env}}{{println .}}{{end}}' > controller-env-backup.txt

# 切换环境变量（需要重建 controller）
.\scripts\switch-controller-to-reverse.ps1
```

或手动重建：
```powershell
docker stop agentteams-controller
docker rm agentteams-controller
# 重新 docker run 时设置：
# -e AGENTTEAMS_LLM_PROVIDER=openai-compat
# -e AGENTTEAMS_OPENAI_BASE_URL=http://host.docker.internal:9001/v1
# -e AGENTTEAMS_LLM_API_KEY=placeholder
```

---

## D.3 验证 Manager 响应

在 Element Web (`http://127.0.0.1:18088`) 中给 Manager 发一条消息，确认能正常回复。

---

## D 窗口完成标准
- [ ] 适配层 `localhost:9001` 正常响应
- [ ] Controller 已切换到适配层
- [ ] Manager 在 Element Web 中能正常回复消息

---

---

# 窗口 E：阶段五 · CLI → REST API 改造（依赖阶段三完成）

## E.1 改造 agentteams_client.py

**文件**：[src/loop/agentteams_client.py](src/loop/agentteams_client.py)

**改动点**：
1. 在 `AgtCLI` 类中新增 `_http_fallback` 方法
2. 所有 `docker exec agentteams-controller agt ...` 调用改为优先 HTTP：
   ```
   GET  http://127.0.0.1:8080/api/v1/workers
   POST http://127.0.0.1:8080/api/v1/tasks
   GET  http://127.0.0.1:8080/api/v1/tasks/{id}
   ```
3. HTTP 失败时自动回退 CLI（`docker exec`），保证兼容性

**具体改动**：

```python
# 在 AgtCLI 类中新增
CONTROLLER_API = "http://127.0.0.1:8080"

async def _http_request(self, method: str, path: str, data: dict = None) -> dict:
    """HTTP 方式调用 Controller REST API。"""
    import aiohttp
    url = f"{self.CONTROLLER_API}/api/v1/{path}"
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, json=data) as resp:
            return await resp.json()

async def _http_fallback(self, cmd_parts: list, api_path: str, method: str = "GET", data: dict = None):
    """优先 HTTP，失败回退 docker exec CLI。"""
    try:
        return await self._http_request(method, api_path, data)
    except Exception:
        print(f"  ⚠ HTTP API 不可用，回退 CLI: agt {' '.join(cmd_parts)}")
        return await self._run(*cmd_parts)
```

然后将 `create_worker` / `get_worker` / `create_task` / `get_task` 等方法改为调用 `_http_fallback`。

---

## E.2 添加单元测试

**文件**：`tests/test_agentteams_client_http.py`（新建）

覆盖：
- HTTP 成功路径
- HTTP 失败 → CLI 回退
- CLI 也失败 → 抛出异常

---

## E 窗口完成标准
- [ ] `AgtCLI` 所有方法改为 `_http_fallback` 调用
- [ ] `python -m pytest tests/ -q` 无回归
- [ ] 新增 HTTP fallback 测试 3+ 例 PASS

---

---

# 窗口 F：阶段六 · CI/CD + UModel + 沙箱加固（独立，可并行）

## F.1 CI/CD 真实后端接入

**当前**：[src/agentteams/mcp/mcp-ci.yaml](src/agentteams/mcp/mcp-ci.yaml) 是空壳模板

**方案 A（轻量，推荐初赛）**：用 shell 脚本模拟完整流水线
```powershell
# 创建 scripts/ci-pipeline-simulator.ps1
# 模拟：构建 → 测试 → 部署 → 审批 → 回滚
```

**方案 B（完整，复赛）**：接入 Jenkins / GitHub Actions
- 触发流水线 → `trigger_pipeline`
- 查询状态 → `get_pipeline_status`
- 获取日志 → `get_build_log`
- 审批部署 → `approve_deploy`
- 回滚 → `rollback_deploy`

---

## F.2 UModel 服务部署

**当前**：模型包已备好（9 entity_set + 9 link + 2 storage），但 UModel 服务未运行

```powershell
# 克隆并启动 UModel
git clone https://github.com/alibaba/UnifiedModel.git
cd UnifiedModel
make quickstart
```

**模型包导入**：
```powershell
# 导入我们的 9 entity_set + 9 link + 2 storage
umctl import -f src/agentteams/umodel/entity_set/
umctl import -f src/agentteams/umodel/link/
umctl import -f src/agentteams/umodel/storage/
```

**验证**：
```powershell
umctl query run demo ".umodel with(kind='entity_set')"
```

---

## F.3 沙箱阶段三加固

**当前**：L1（容器隔离）+ L2（copaw 运行时守卫）已完成

**补齐**：L3 沙箱额外加固
- 接入 AgentScope Runtime 沙箱（`agentscope-runtime` + `runtime-sandbox-mcp`）
- 网络隔离：Worker 容器只允许访问白名单域名
- 资源限制：CPU/内存 cgroup 限制

---

## F 窗口完成标准
- [ ] CI/CD 流水线脚本可运行（至少 shell 模拟版）
- [ ] UModel 服务启动成功，模型包导入验证通过
- [ ] 沙箱加固配置落地

---

---

# 窗口 G：阶段七 · 容器化 + Dashboard + 端到端验证（最后收尾）

## G.1 Python 客户端容器化

**当前**：`run.py` + `src/loop/` 依赖本地 Python 环境

**创建 Dockerfile**（新建 `Dockerfile.client`）：
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ src/
COPY skills/ skills/
COPY scripts/ scripts/
CMD ["python", "src/run.py"]
```

```powershell
docker build -t agentteams-client -f Dockerfile.client .
docker run --rm agentteams-client "修复登录接口空用户名500"
```

---

## G.2 Dashboard 增强

**当前**：[src/loop/dashboard.py](src/loop/dashboard.py) 仅 Rich 终端渲染 + 简单 Web 页面

**增强**：
- WebSocket 实时推送（任务状态变化 → 前端即时更新）
- 历史回放（按 task_id 查看完整 PDCA 闭环时间线）
- 6 Worker 健康状态面板

---

## G.3 端到端验证

```powershell
# 1. 真实平台端到端
python -m pytest tests/test_agentteams_delegated.py -v

# 2. 动态招人场景
python -m pytest tests/test_e2e_dynamic_hiring.py -v

# 3. 全量回归
python -m pytest tests/ -q
```

---

## G 窗口完成标准
- [ ] Dockerfile 构建成功，容器化运行正常
- [ ] Dashboard WebSocket 实时推送可用
- [ ] 全量测试 115+ passed，无回归
- [ ] 真实平台端到端闭环完成

---

---

## 附录：快速参考

### 关键文件路径

| 文件 | 路径 |
|------|------|
| Skill 空壳 | `skills/git-operations/SKILL.md`、`skills/repo-context/SKILL.md`、`skills/code-search/SKILL.md`、`skills/knowledge-rag/SKILL.md`、`skills/evidence-log/SKILL.md` |
| 完整 Skill 参考 | `skills/code-gen/SKILL.md` |
| 代码扫描服务 | `src/agentteams/toolchains/code_scan_service.py` |
| 测试平台服务 | `src/agentteams/toolchains/test_platform_service.py` |
| 确定性内核 | `src/agentteams/toolchains/core.py` |
| MCP 模板 | `src/agentteams/mcp/mcp-code-scan.yaml`、`mcp-test-platform.yaml`、`mcp-ci.yaml` |
| Worker 定义 | `src/agentteams/workers.yaml` |
| AgentTeams 客户端 | `src/loop/agentteams_client.py` |
| 安全策略 | `src/agentteams/SECURITY-POLICY.md` |
| 工具链设计 | `design/TOOLCHAIN-PLAN.md` |
| 审批流 | `src/loop/approval.py` |
| MCP 注册脚本 | `scripts/register-mcp.ps1` |
| 模型路由切换 | `scripts/switch-controller-to-reverse.ps1` |
| Skill 引用验证 | `scripts/verify-skill-refs.py` |

### 常用命令

```powershell
# 激活虚拟环境
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"

# 运行测试
python -m pytest tests/ -q

# 检查 Skill 引用完整性
python scripts/verify-skill-refs.py

# 查看 Worker 状态
docker exec agentteams-controller agt get workers

# 查看 MCP 挂载
docker exec agentteams-worker-fixer cat /root/.copaw/mcporter.json

# Mock 模式自检
python src/loop/agentteams_loop.py
```