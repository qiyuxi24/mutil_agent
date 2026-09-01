---
name: code-search
description: 代码检索：ripgrep 全文搜索 + 语义搜索，符号定位、调用链追踪、引用查找。触发词：搜索、查找、grep、rg、调用链、引用、符号、定义、search、symbol、caller、callee。
assign_when: 任何 Worker 需要在代码库中搜索特定模式、定位符号定义、追踪调用关系时分配。
---

# Skill: code-search

提供全文搜索（ripgrep）与语义搜索双通道代码检索能力，支持符号定位、调用链追踪和多维度引用查找。是 `root-cause-analysis`、`code-gen` 等 Skill 的核心支撑。

## 输入

- 搜索模式：关键词 / 正则表达式 / 语义描述
- 搜索范围：文件路径 glob / 语言类型 / 函数名 / 类名
- 搜索模式：`fulltext`（ripgrep）/ `semantic`（embedding 向量）/ `symbol`（符号定位）/ `callchain`（调用链）/ `references`（引用查找）
- 上下文行数（`context`）：前后各 N 行

## 执行步骤

1. **模式路由**：根据搜索模式选择执行通道：
   - `fulltext` → ripgrep 正则搜索
   - `semantic` → embedding 向量相似度匹配
   - `symbol` → 定位函数/类/变量定义
   - `callchain` → 追踪调用关系（上行：谁调用了它 / 下行：它调用了谁）
   - `references` → 全局查找某符号的所有引用位置
2. **全文搜索（ripgrep）**：
   - 支持正则表达式、文件类型过滤（`--type py` / `--type go`）
   - 支持上下文行数（`-C N` / `-A N` / `-B N`）
   - 支持排除路径（`--glob '!vendor/**'` / `--glob '!node_modules/**'`）
3. **语义搜索**：
   - 将自然语言查询转为 embedding 向量
   - 在代码库向量索引中检索语义相似代码片段
   - 按相似度排序返回 Top-K 结果
4. **符号定位**：
   - 解析 AST 定位函数/类/变量定义位置
   - 返回文件路径 + 行号 + 签名
5. **调用链追踪**：
   - 上行：搜索所有调用目标函数的调用点
   - 下行：搜索目标函数内部的所有函数调用
   - 递归深度可配置（默认 1 层，最大 3 层）
6. **引用查找**：全局搜索符号的所有引用位置（定义、调用、import、赋值）
7. **产出**：生成 `search-result.json`，写入 `shared/tasks/{id}/search.json`

## 输出（SEARCH_DONE）

```json
{
  "task_id": "T-0001",
  "search_mode": "fulltext|semantic|symbol|callchain|references",
  "query": "processTask",
  "results": [
    {
      "file": "src/worker/task.go",
      "line": 42,
      "context": "func processTask(t *Task) error {",
      "match_type": "definition",
      "score": 1.0
    }
  ],
  "total_matches": 5,
  "status": "OK"
}
```

## 依赖工具

- L1 基座：无（本 Skill 为最底层检索 Skill）
- 外部依赖：ripgrep CLI（Worker 容器内预装）、embedding API（语义搜索通道，可降级）

## 失败处理

- ripgrep 不可用 → 降级为 Python `re` 模块全文搜索，标记 `RG_DEGRADED`
- embedding API 不可用 → 语义搜索降级为 TF-IDF 关键词匹配，标记 `EMBED_DEGRADED`
- 搜索无结果 → 返回空结果集，标记 `NO_MATCHES`，建议扩大搜索范围或调整模式
- 符号定位失败（AST 解析异常）→ 退化为 ripgrep 精确匹配，标记 `AST_DEGRADED`
- 搜索超时（默认 30s）→ 终止并返回部分结果，标记 `TIMEOUT`

## 安全边界

- 只读搜索，**绝不修改**代码文件
- 排除 `.git/`、`node_modules/`、`vendor/`、`__pycache__/` 等非源码目录
- 不搜索 `.env`、`credentials/`、`*.pem` 等敏感文件路径
- 单次搜索文件数上限 10000，防止内存溢出

## 复用价值

- 所有需要代码检索的 Skill 均依赖本 Skill（`root-cause-analysis`、`impact-analysis`、`code-gen`、`repo-context`）
- 全文搜索 + 语义搜索双通道覆盖精确匹配与模糊理解两种场景
- 调用链追踪能力可直接用于 `impact-analysis` 的影响面计算

## 协同关系

- **下游**：为 `root-cause-analysis`（定位根因代码）、`impact-analysis`（评估影响面）、`code-gen`（定位修改上下文）、`repo-context`（依赖分析）提供检索能力
- **并行**：与 `repo-context` 协同（搜索定位 import → 构建依赖图）

## 里程碑

- 输出：`SEARCH_DONE`（搜索完成，结果已写入）
- 若 `NO_MATCHES` → 建议上级 Skill 调整搜索策略