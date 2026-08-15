# 研发 PDCA 统一数据模型包（`.umodel`）

> 复用阿里官方 **UModel（Unified Model，`alibaba/UnifiedModel`）** 的声明式语法，把研发闭环的
> 共享状态（`shared/tasks/`）与知识库（`shared/knowledge/`）统一成一份 **workspace-scoped 对象图模型包**，
> 让 6 个研发 Worker 通过 `umctl` / `umodel-mcp` 按语义查询，而非各自硬编码文件路径和字段名。
>
> 官方仓库：`references/refs/unified-model/`（README.zh-CN.md）
> 接入方案：`design/UNIFIED-MODEL-INTEGRATION.md`

---

## 一、模型包结构

```
src/agentteams/umodel/
  entity_set/   9 个研发实体类型（EntitySet）
  link/         9 条实体间关系（EntitySetLink，即 PDCA 里程碑握手链的对象图化）
  storage/      2 个存储绑定（S3 兼容对象存储）
  README.md     本指南
```

### entity_set/（实体类型）

| 实体 | 对应项目概念 | 产出方 |
|------|-------------|--------|
| `dev.task` | 共享任务（映射 `shared/tasks/{id}/state.json`） | Manager/Leader |
| `dev.defect` | 缺陷 | Aggregator |
| `dev.root_cause` | 根因分析 | RootCause |
| `dev.patch` | 修复补丁 | Fixer |
| `dev.test_case` | 测试用例 | Tester |
| `dev.test_report` | 测试报告 | Tester |
| `dev.release` | 发布确认 | Releaser |
| `dev.retrospective` | 复盘沉淀（知识库条目） | Retrospector |
| `dev.worker` | Agent 成员 | Manager |

### link/（关系链 = 里程碑握手链）

```
dev.task ──produces──> dev.defect
dev.defect ──analyzed_by──> dev.root_cause
dev.root_cause ──fixed_by──> dev.patch
dev.patch ──verified_by──> dev.test_report        (含 dev.test_case 集合)
dev.test_report ──approved_by──> dev.release
dev.release ──reviewed_by──> dev.retrospective
dev.retrospective ──enriches──> dev.task          (沉淀反哺新任务)
dev.task ──assigned_to──> dev.worker
dev.patch ──committed_by──> dev.worker
```

这条链正好对应 `design/PDCA-CLOSED-LOOP.md` 的里程碑握手
（`ROOT_CAUSE_FOUND → FIX_APPLIED → TEST_PASSED → RELEASE_OK → RETROSPECT_DONE`）。

### storage/（数据源绑定）

| Storage | kind | 绑定路径 |
|---------|------|---------|
| `dev.minio.tasks` | minio | `shared/tasks/` 对象存储 |
| `dev.minio.knowledge` | minio | `shared/knowledge/` 对象存储 |

---

## 二、校验模型包

宿主机执行：

```bash
python scripts/verify-umodel-model.py
```

输出 JSON 摘要，退出码 0 = 全部符合预期（entity_set 9 / link 9 / storage 2）。

---

## 三、导入与查询（UModel Query Service）

### 1. 起本地 UModel 服务（官方仓库）

```bash
cd references/refs/unified-model
make quickstart QUICKSTART_SAMPLE=examples/quickstart-multidomain
```

### 2. 导入本模型包到 workspace `demo`

将本目录 `entity_set/` / `link/` / `storage/` 的 YAML 导入 UModel workspace（具体导入方式见官方
`examples/quickstart-multidomain/deploy/`）。

### 3. 用 `umctl` 查询

```bash
# 枚举实体类型
umctl query run demo ".umodel with(domain='dev', kind='entity_set')" -o json

# 读任务实例
umctl query run demo ".entity with(domain='dev', name='dev.task') | limit 20" -o json

# 沿关系遍历（任务→缺陷）
umctl query run demo ".topo with(domain='dev', src='dev.task', link='produces')" -o json
```

### 4. MCP 替代（复赛环境）

`umodel-mcp` 提供 `query_spl_execute` 工具，经 AgentTeams `Worker.spec.mcpServers` 挂载后，
Worker 用 `mcporter call umodel query_spl_execute '{"workspace":"demo","query":"<SPL>"}'` 查询。
凭据只存网关（复用 `scripts/register-mcp.ps1`）。

---

## 四、Agent 技能复用

| Skill | 挂到 | 用途 |
|-------|------|------|
| `umodel-query` | 所有 Worker | 只读实体/关系/模型 |
| `umodel-rca` | RootCause | 模型引导根因分析 |

> 官方技能全文见 `references/refs/unified-model/skills/`；项目封装见 `skills/umodel-query/`、`skills/umodel-rca/`。

---

## 五、安全边界

- Worker 只读查询，不直接写存储凭据；真实数据源连接由 UModel 统一管理。
- 底层文件仍落 MinIO（`shared/tasks/`、`shared/knowledge/`），UModel 提供统一 schema 视图，二者互补。
- 涉及敏感信息的实体（安全漏洞等）按 `skills/` 与沙箱策略脱敏。

---

## 六、文档索引

- 接入方案：`design/UNIFIED-MODEL-INTEGRATION.md`
- 官方仓库：`references/refs/unified-model/`
- 共享状态/知识库现状：`design/RAG-MEMORY.md`
- 里程碑握手：`design/PDCA-CLOSED-LOOP.md`
- 工具链 MCP 接入：`design/MCP-INTEGRATION.md`
