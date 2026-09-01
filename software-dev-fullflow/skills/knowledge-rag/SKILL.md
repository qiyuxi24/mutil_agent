---
name: knowledge-rag
description: 知识库检索与写入：查历史经验教训、已修复缺陷、失败模式，写入结构化复盘知识。触发词：经验、知识库、检索、RAG、历史、教训、相似问题、knowledge、retrieve、recall。
assign_when: 任何 Worker 需要检索历史经验、匹配相似问题、沉淀知识时分配。
---

# Skill: knowledge-rag

从知识库（`shared/knowledge/`）检索历史经验与教训，将复盘结果结构化写入知识库，实现组织记忆复用。与 `context.py` 的 `SemanticMemorySearch` 协同，提供关键词 + 语义双通道检索。

## 输入

- 检索操作：查询文本（bug 描述、错误日志、模块名）
- 写入操作：复盘产物（问题描述、根因、解法、验证结果、教训）
- 检索策略：`keyword`（关键词匹配）/ `semantic`（语义相似度）/ `hybrid`（混合，优先语义）
- 检索范围：`patterns`（失败模式）/ `fixes`（修复方案）/ `tests`（测试策略）/ `all`（全部类别）

## 执行步骤

1. **检索通道选择**：
   - `keyword`：对查询文本分词，在知识库 Markdown/JSON 文件中做关键词匹配
   - `semantic`：调用 `SemanticMemorySearch`（`context.py`），做 embedding 向量相似度检索
   - `hybrid`：先语义检索 Top-K，再用关键词过滤精确匹配
2. **相似问题匹配**：
   - 对检索结果按相关度排序
   - 提取匹配项的：问题描述、根因、修复方案、验证方法、经验教训
   - 标记相似度（`score`：0.0-1.0）
3. **知识写入**：
   - 输入：复盘产物（`retrospective` 产出）
   - 结构化：问题→根因→解法→验证→教训 五段式
   - 写入路径：`shared/knowledge/{category}/{timestamp}_{slug}.md`
   - 更新索引：写入后更新知识库索引文件
4. **产出**：生成 `knowledge-result.json`（检索结果）或更新知识库索引

## 输出（KNOWLEDGE_RETRIEVED / KNOWLEDGE_WRITTEN）

```json
{
  "task_id": "T-0001",
  "operation": "retrieve|write",
  "query": "空指针异常 processTask",
  "results": [
    {
      "id": "K-0042",
      "title": "processTask 空指针修复",
      "category": "fixes",
      "root_cause": "未校验输入参数",
      "solution": "在函数入口增加 nil 校验",
      "lessons": "外部输入接口必须做防御性校验",
      "score": 0.92
    }
  ],
  "total_matches": 3,
  "status": "OK"
}
```

## 依赖工具

- L1 基座：`evidence-log`（知识写入审计）
- 内部依赖：`context.py` 的 `SemanticMemorySearch`（语义检索通道）
- 外部依赖：embedding API（语义通道，可降级为 TF-IDF）

## 失败处理

- 检索无结果 → 返回空结果，标记 `NO_MATCHES`，建议扩大搜索范围
- embedding API 不可用 → 降级为 TF-IDF 关键词匹配，标记 `EMBED_DEGRADED`
- 知识库索引损坏 → 回退为全量遍历检索，标记 `INDEX_DEGRADED`
- 写入冲突（同 slug 已存在）→ 追加时间戳后缀，标记 `WRITE_DEDUP`
- 知识库目录不可写 → 缓存到 `shared/tasks/{id}/pending_knowledge.json`，标记 `WRITE_PENDING`

## 安全边界

- 只读检索时不修改知识库文件
- 写入时校验内容非空，防止空条目污染知识库
- 敏感信息（凭据、密钥、个人信息）在写入前脱敏
- 知识库文件大小限制：单条知识 ≤ 10KB，总数 ≤ 10000 条

## 复用价值

- 所有 Worker 均可检索历史经验，避免重复犯错
- 知识库随着复盘沉淀持续增长，团队经验可累积复用
- 相似问题匹配能力可加速 `root-cause-analysis` 的根因定位

## 协同关系

- **上游**：接收 `retrospective`（复盘产物）作为知识写入输入
- **下游**：为 `issue-parsing`（去重关联）、`root-cause-analysis`（相似问题检索）、`code-gen`（历史修复参考）提供知识检索
- **并行**：与 `context.py` 的 `SemanticMemorySearch` 协同（语义搜索通道）

## 里程碑

- 检索：输出 `KNOWLEDGE_RETRIEVED`（检索完成，结果已返回）
- 写入：输出 `KNOWLEDGE_WRITTEN`（知识已写入，索引已更新）