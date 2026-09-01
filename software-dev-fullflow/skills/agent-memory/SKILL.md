---
name: agent-memory
description: 通用可复用记忆系统：按 Agent 读写跨任务的独立记忆（每日日志/长期记忆/迭代记录）。触发词：记忆、回忆、沉淀、经验、memory、recall、consolidate、remember。
assign_when: 任何 Worker 需要读取历史经验、记录本次迭代教训、沉淀长期知识时分配。
---

# Skill: agent-memory

所有 Worker **统一复用**的可复用记忆框架。把「按 Agent 独立记忆 + 沉淀 + 检索」做成显式能力（而非各 SOUL 手写规则），对应代码实现 `AgentMemory` / `AgentMemoryRegistry`（`src/loop/context/agent_memory.py`）。

## 统一记忆契约（三段式）

每个 Agent 在 `shared/agents/<name>/memory/` 下持有独立记忆空间：

| 文件 | 内容 | 生命周期 |
|------|------|---------|
| `YYYY-MM-DD.md` | 每日工作日志（人类可读，按天追加） | 跨任务累积 |
| `MEMORY.md`（+`memory.json`） | 长期记忆（稳定知识/模式/偏好，供检索） | 长期保留，FIFO 淘汰 |
| `iterations.jsonl` | 迭代记录（结构化，每行一条，供检索） | 跨任务累积，最多 200 条 |

**通用契约要点**：① 记忆按 `agent_name` 隔离，各 Agent 互不覆盖；② 长期记忆由 `consolidate` 自动从近期迭代提炼（高频错误模式 / 成功模式）；③ 检索用 `recall`（关键词 + 子串匹配），供后续任务避免重复踩坑。

## 输入

- 操作：`read`（读迭代记录）/ `write`（写一条迭代）/ `recall`（检索历史经验）/ `consolidate`（沉淀长期记忆）/ `snapshot`（快照）
- Agent 名：`--agent <name>`（如 fixer / tester）
- 内容（write/recall）：`--task <task_id>`、`--phase <phase>`、`--outcome <success|fail|retry>`、`--mistake <text>`、`--fix <text>`、`--pattern <text>`、`--query <检索词>`

## 执行步骤

1. **写入迭代**（任务某个阶段完成后）：
   ```bash
   python skills/agent-memory/scripts/memory_cli.py write --agent fixer \
     --task T-0001 --phase fix --outcome success --pattern "拆解根因后一次修复成功"
   ```
2. **检索经验**（开始新阶段前，避免重复踩坑）：
   ```bash
   python skills/agent-memory/scripts/memory_cli.py recall --agent fixer --query "空指针"
   ```
3. **沉淀长期记忆**（任务/项目收尾时）：
   ```bash
   python skills/agent-memory/scripts/memory_cli.py consolidate --agent fixer
   ```
4. **快照**（观测/审计）：
   ```bash
   python skills/agent-memory/scripts/memory_cli.py snapshot --agent fixer
   ```

## 输出

- `read` / `recall`：返回 JSON 数组（迭代记录 / 相关历史经验，按相关度排序）
- `write` / `consolidate`：返回操作结果 + 新增长期记忆条目数
- `snapshot`：返回该 Agent 的记忆摘要（迭代数 / 长期条目数 / 最近阶段 / 总重试数）

## 依赖工具

- L1 基座：`AgentMemory` / `AgentMemoryRegistry`（`src/loop/context/agent_memory.py`，纯标准库）
- 外部依赖：无（仅 `json` / `argparse` / `pathlib`）

## 失败处理

- Agent 目录不存在 → `AgentMemory` 自动创建
- 检索无结果 → 返回空数组，标记 `NO_MEMORY`
- JSONL 解析异常 → 跳过损坏行，不中断（容错）

## 安全边界

- 只读写 `shared/agents/<name>/memory/`，不触及系统路径
- 不记录凭据 / 密钥 / Token（写入前由调用方脱敏）
- 长期记忆有上限（30 条），迭代记录有上限（200 条），防无限膨胀

## 复用价值

- 所有 Worker 统一挂载 `agent-memory` skill，形成可复用、可检索、可沉淀的记忆框架
- 与 `evidence-log`（执行证据）互补：evidence-log 记"事件"，agent-memory 记"经验教训"
- 为 `retrospective`（复盘）和 `knowledge-rag`（知识库写入）提供输入

## 协同关系

- **下游**：`retrospective`（复盘）、`knowledge-rag`（经验沉淀）消费本 Skill 沉淀的记忆
- **并行**：`evidence-log`（事件证据链）与本 Skill（经验记忆）并行记录
- **统一入口**：通过 `AgentMemoryRegistry` 统一读写，各 Agent 无需手写记忆规则

## 里程碑

- 写入成功：输出 `MEMORY_WRITTEN`
- 检索完成：输出 `MEMORY_RECALLED`
- 沉淀完成：输出 `MEMORY_CONSOLIDATED`（含新增条目数）
