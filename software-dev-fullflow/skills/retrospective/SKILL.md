---
name: retrospective
description: 对一次完整闭环进行复盘，提炼经验教训、失败模式、可复用规则，沉淀到知识库（RAG），形成组织记忆。触发词：复盘、总结、沉淀、回顾、retrospect、review。
assign_when: 复盘沉淀员（Retrospector）需要在闭环完成后进行复盘并沉淀知识时分配。
---

# Skill: retrospective

对一次完整研发闭环进行复盘，提炼经验教训与失败模式，沉淀到知识库（RAG），让组织「越用越聪明」。**本 Skill 是组织记忆的核心。**

## 输入

- 任务全生命周期记录：`spec.json` → `root-cause.json` → `fix.json` → `test.json` → `release.json`（含回滚/证据）。

## 执行步骤

1. **收集**：拉取任务全链路记录与执行证据（`evidence-log`）。
2. **复盘**：总结做了什么、结果如何、卡点在哪、有何可改进。
3. **提炼失败模式**：识别可复用的「失败模式 + 规避方法」（如"X 类缺陷反复出现"）。
4. **规则化**：把经验提炼成结构化知识条目（含来源溯源）。
5. **沉淀**：通过 `knowledge-rag` 写入知识库。
6. **产出**：`retrospect-report` + 知识条目，写入 `shared/tasks/{id}/retrospect.json`。

## 输出（RETROSPECT_DONE）

```json
{
  "task_id": "T-0001",
  "summary": "空指针缺陷，已修复并通过测试发布",
  "lessons": ["在入口统一做空值校验"],
  "failure_patterns": [{"pattern": "null_pointer", "avoidance": "入口统一校验", "times": 3}],
  "improvements": ["增加静态空值检查到 CI"],
  "knowledge_refs": ["knowledge://defect/null-pointer-guard"],
  "status": "RETROSPECT_DONE"
}
```

## 依赖工具

- L1 基座：`knowledge-rag`（写入）、`evidence-log`（读取）
- MCP/外部：知识库存储（PolarDB/向量库）、RAG 检索

## 失败处理

- 记录不全 → 基于现有证据生成复盘并标注缺口。
- 知识库写入失败 → 本地暂存，待重试，不阻塞交付。

## 安全边界

- 复盘内容脱敏（去敏感信息/凭据）；知识库写入需有来源溯源。
- 不自动传播到生产配置。

## 里程碑

- 输出：`RETROSPECT_DONE` → **闭环闭合**。
- 沉淀的知识供后续任务通过 RAG 复用（见 `design/RAG-MEMORY.md` 待建）。
