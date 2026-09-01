---
name: repo-context
description: 仓库结构感知：模块划分、依赖图构建、变更影响范围分析、构建入口识别、技术栈检测。触发词：模块、依赖、依赖图、构建入口、技术栈、影响范围、module、dependency、import。
assign_when: 任何 Worker 需要理解项目结构、分析模块依赖、评估变更影响时分配。
---

# Skill: repo-context

感知仓库结构，输出模块边界、依赖关系、构建入口和技术栈信息。为其他 Skill（`code-gen`、`root-cause-analysis`、`impact-analysis`）提供结构化的仓库认知。

## 输入

- 仓库根目录路径（默认当前工作区）
- 可选：关注的模块/文件路径（用于增量分析）
- 可选：分析深度（`full` 全量扫描 / `quick` 入口识别 / `diff` 变更影响）

## 执行步骤

1. **目录结构解析**：扫描顶层目录与关键子目录，识别模块边界（如 `src/`、`packages/`、`cmd/` 等）。
2. **构建入口识别**：定位 `setup.py`、`Makefile`、`package.json`、`go.mod`、`Cargo.toml`、`pom.xml`、`CMakeLists.txt` 等构建入口文件。
3. **技术栈检测**：从构建入口 + 关键文件推断语言/框架/构建工具（Python/Go/Node.js/Rust/Java 等）。
4. **依赖图构建**：
   - 解析各模块的 `import` 语句（Python `import`/`from`、Go `import`、JS `require`/`import` 等）
   - 构建模块间依赖关系图（DAG）
   - 标注循环依赖（`CYCLE` 警告）
5. **变更影响分析**（`diff` 模式）：
   - 输入：变更文件列表
   - 输出：受影响模块、传递依赖链、风险等级（LOW/MEDIUM/HIGH）
6. **产出**：生成 `repo-context.json`，写入 `shared/tasks/{id}/repo.json`

## 输出（REPO_CONTEXT_READY）

```json
{
  "task_id": "T-0001",
  "repo_root": "/workspace",
  "tech_stack": {
    "language": "Python",
    "framework": "FastAPI",
    "build_tool": "pip",
    "package_manager": "pip"
  },
  "modules": [
    {
      "path": "src/worker/",
      "role": "核心业务逻辑",
      "dependencies": ["src/utils/", "src/models/"],
      "imported_by": ["src/api/"]
    }
  ],
  "dependency_graph": {
    "nodes": 5,
    "edges": 8,
    "cycles": []
  },
  "build_entries": ["setup.py", "Makefile"],
  "impact_analysis": {
    "changed_file": "src/worker/task.go",
    "directly_affected": ["src/api/handler.go"],
    "transitive_affected": ["tests/test_worker.go"],
    "risk_level": "MEDIUM"
  },
  "status": "OK"
}
```

## 依赖工具

- L1 基座：`code-search`（定位 import 语句、构建入口文件）
- 外部依赖：无（纯 Python 代码解析，使用 `ast` 标准库）

## 失败处理

- 构建入口未找到 → 标记 `NO_BUILD_ENTRY`，退化为目录结构扫描
- 语言无法识别 → 标记 `UNKNOWN_LANG`，跳过依赖分析，仅输出目录结构
- 循环依赖检测到 → 输出 `CYCLE` 警告，标记 `impact_analysis.risk_level=HIGH`
- 仓库过大（> 10000 文件）→ 自动切换为 `quick` 模式，仅分析入口与一级目录

## 安全边界

- 只读分析，**绝不修改**仓库代码
- 不访问 `.env`、`credentials/`、`providers.json` 等敏感文件
- 产物落盘 `shared/tasks/{id}/repo.json`，可审计

## 复用价值

- 所有需要理解项目结构的 Skill 均依赖本 Skill（`root-cause-analysis`、`impact-analysis`、`code-gen`）
- 依赖图可缓存，同一仓库多次分析时增量更新
- 技术栈检测结果可指导 `code-gen` 选择正确的编译/静态检查工具

## 协同关系

- **上游**：接收 `code-search`（import 搜索结果）作为依赖分析输入
- **下游**：为 `root-cause-analysis`（定位根因所在模块）、`impact-analysis`（影响面评估）、`code-gen`（技术栈选择）提供上下文
- **并行**：与 `code-search` 协同（搜索定位 import → 构建依赖图）

## 里程碑

- 输出：`REPO_CONTEXT_READY`（仓库结构分析完成）
- 若 `NO_BUILD_ENTRY` → 通知 Manager 确认仓库结构