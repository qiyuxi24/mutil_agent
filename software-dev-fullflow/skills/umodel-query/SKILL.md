---
name: umodel-query
description: 通过阿里官方 UModel 统一数据模型查询研发对象图（实体/关系/模型），让 Agent 不再硬编码文件路径而是读统一语义层。触发词：umodel、统一模型、对象图、实体查询、.entity、.topo、.umodel、查任务、查缺陷、查根因、查补丁、查测试、查发布、查复盘。
assign_when: 任意职能 Worker（Aggregator/RootCause/Fixer/Tester/Releaser/Retrospector）需要按统一数据模型读取共享状态或知识库实体、关系、模型元数据时分配。
---

# Skill: umodel-query

用阿里官方 **UModel（Unified Model）** 的 Query Service 读取研发 PDCA 对象图。本 Skill 只做**只读查询**，不做写入与修复。

> 官方技能全文：`references/refs/unified-model/skills/umodel-query/SKILL.md`（本项目为官方技能的封装 + 研发域定制）。

## 输入

- UModel 服务地址（`UMCTL_ADDR`）与 workspace 名。
- 目标实体类型（`dev.task` / `dev.defect` / `dev.root_cause` / `dev.patch` / `dev.test_case` / `dev.test_report` / `dev.release` / `dev.retrospective` / `dev.worker`）。

## 执行步骤

1. **确认工具就绪**：`command -v umctl || go install github.com/alibaba/UnifiedModel/cmd/umctl@latest`；`umctl version`。
2. **确认 workspace**：`umctl workspace list -o json`。
3. **枚举实体类型（读模型本身）**：
   ```bash
   umctl query run <ws> ".umodel with(domain='dev', kind='entity_set')" -o json
   ```
4. **读实体实例**：
   ```bash
   umctl query run <ws> ".entity with(domain='dev', name='dev.task') | limit 20" -o json
   ```
5. **沿关系遍历拓扑**：
   ```bash
   umctl query run <ws> ".topo with(domain='dev', src='dev.task', link='produces')" -o json
   ```
6. **MCP 替代**：连接 `umodel-mcp`，调用 `query_spl_execute`，参数 `{ "workspace": "<ws>", "query": "<同一段 SPL>" }`。

## 输出

返回符合 UModel 列格式的 JSON 记录（`header` + `data` 矩阵，需 zip 成记录）。关键字段：
- 实体：各 entity 的 `id` / `display_name` / `current_state` / `status` 等。
- 关系：`src` / `dest` / `entity_link_type`。
- 模型：EntitySet / Link / Storage 类型清单。

## 依赖工具

- L1：`umctl` CLI（或 MCP `query_spl_execute`）。
- MCP：`umodel`（复赛环境经 Higress 挂载）。

## 失败处理

- `umctl` 未装 → 提示安装（Go 1.22+）或下载 Release 预编译二进制。
- 服务未起 → 提示 `make quickstart`（官方仓库）起本地 UModel + 导入 `src/agentteams/umodel/` 模型包。
- 查询无结果 → 区分"类型不存在"（模型未导入）与"实例为空"（尚未写实体）。

## 安全边界

- **只读**，不写实体、不改 schema。
- 不泄露底层存储凭据（UModel 统一管理数据源连接，Worker 不落地 key）。

## 里程碑

- 无独立里程碑；作为支撑 Skill 为各 Worker 的读取/交接提供统一数据视图。

## 关联 Skill

- `umodel-rca`（模型引导根因分析，基于本 Skill 的读取能力）。
