# RAG / 记忆方案（RAG-MEMORY）

> GOAI 大赛 · 赛道三「软件研发全流程协同」· 第 6 项核心产出
> 对应官方要求：**RAG 与上下文增强（推荐）** —— 定位是 Agent、Skill、MCP 调用链中的上下文能力。
> 官方强制：以下 4 项能力**至少实现 2 项**——①Agent 记忆存储 ②知识库 RAG ③共享状态管理 ④轨迹可观测。
> **我们的策略：4 项全部覆盖**（高于"4 选 2"要求）。
> 对应评审权重：**工程落地、运行验证与安全可审计 20%**。
> 日期：2026-08-12

---

## 0. 结论先行

> 我们用一套「共享文件系统 + 知识库 + Agent 记忆」三件套，覆盖官方 4 项中的 3 项（④轨迹可观测由第 5 项 `OBSERVABILITY.md` 覆盖）：
>
> | 官方选项 | 我们的实现 | 落地位置 |
> |---------|-----------|---------|
> | ① Agent 记忆存储 | 每个 Worker 的 `memory/`（日志 + 长期记忆） | `shared/agents/{name}/memory/` |
> | ② 知识库 RAG | 复盘沉淀 + 检索（问题→根因→解法→验证） | `shared/knowledge/` + 检索 |
> | ③ 共享状态管理 | 任务流转状态机 | `shared/tasks/{id}/state.json` |
> | ④ 轨迹可观测 | Trace/Log/Metrics | 见 `OBSERVABILITY.md` |

---

## 一、三件套总览

```
┌─────────────────────────────────────────────────────────┐
│  shared/ (MinIO 集中文件系统，多 Agent 共享，无状态 Worker)   │
│                                                         │
│  ├─ tasks/{id}/state.json   ③ 共享状态（任务流转状态机）      │
│  ├─ knowledge/{id}.md       ② 知识库 RAG（经验教训）         │
│  └─ agents/{name}/memory/   ① Agent 记忆（跨会话）           │
│                                                         │
│  ┌─────────────────────────────┐                        │
│  │  检索服务（RAG 引擎）          │                        │
│  │  查询 → 向量检索/关键词 → 上下文 │                        │
│  └─────────────┬───────────────┘                        │
│                │ 注入到 Agent 的 system prompt / context │
└────────────────┴────────────────────────────────────────┘
```

> **核心原则**：上下文不在 IM 消息里长篇传递（防上下文膨胀），而是**落共享文件 + 检索注入**——Agent 只带"文件引用 + 检索结果"，完整内容按需读取。这对齐 `references/theory/CONTEXT-ENGINEERING.md` 的"信息卸载"策略。

---

## 二、共享状态管理（③：任务流转状态机）

> 这其实在第 2 项（`PDCA-CLOSED-LOOP.md`）和第 4 项（`COLLABORATION-DESIGN.md`）已设计，此处给出**落地方案**。

### 2.1 状态文件 `shared/tasks/{id}/state.json`

```json
{
  "task_id": "task-abc123",
  "title": "修复登录接口超时",
  "current_state": "ROOT_CAUSE",
  "milestones": {
    "TASK_SPEC_READY":   { "at": "2026-08-12T10:00:00Z", "by": "Aggregator" },
    "ROOT_CAUSE_FOUND":  { "at": null, "by": null }
  },
  "artifacts": {
    "spec.md":      "tasks/task-abc123/spec.md",
    "root-cause":   "tasks/task-abc123/root-cause.md",
    "fix":          "tasks/task-abc123/fix/",
    "test-report":  "tasks/task-abc123/test-report.md"
  },
  "rollback_count": 0,
  "owner": "team-leader"
}
```

### 2.2 谁读谁写

| 角色 | 操作 |
|------|------|
| Team Leader | 读 `state.json` 判断当前状态 → 派对应 Worker；推进里程碑 |
| Manager | 读 `state.json` 全局巡检、审批、归档 |
| Worker | 读自己的输入产物；完成产出后写 `state.json` 里程碑 + 产物路径 |
| 观测层 | 读 `state.json` 打 Trace/Metrics（`OBSERVABILITY.md`） |

### 2.3 状态机规则（对接第 2 项）

- 状态流转由**里程碑词**驱动（`TASK_SPEC_READY → … → RETROSPECT_DONE`）。
- **确定性状态图**（enum + 转移表），Manager 只"根据状态派活"，不"记住状态"——状态在共享文件，**可审计、可恢复**。
- **恢复**：若 Worker/Manager 重启，读 `state.json` 即可从断点续跑（对应 AgentTeams 无状态 Worker + MinIO 持久化）。

---

## 三、知识库 RAG（②：经验教训沉淀 + 检索复用）

### 3.1 沉淀：谁写、写什么

**Retrospector（复盘沉淀员）** 在每个闭环完成后写结构化经验条目：

`shared/knowledge/{entry-id}.md`

```markdown
---
id: knowledge-001
type: bug-fix
task_id: task-abc123
root_cause: 连接池未配置超时
tags: [backend, connection-pool, timeout]
created: 2026-08-12T10:30:00Z
---
# 问题：登录接口超时

## 根因
连接池未设置连接超时，高并发下线程阻塞。

## 解法
配置连接池超时 + 熔断；修复见 task-abc123。

## 验证
压测通过，P99 从 5s 降到 200ms。

## 可复用性
适用于所有依赖数据库/外部服务的接口。
```

### 3.2 检索：谁查、怎么查

| 使用场景 | 谁检索 | 检索方式 |
|---------|--------|---------|
| 根因定位时找"类似历史缺陷" | RootCause | 按根因/标签/关键词 |
| 修复时找"同类解法" | Fixer | 按解法/技术栈 |
| 生成测试时找"历史回归场景" | Tester | 按 tags/验证 |
| Manager 调度时评估"难度" | Manager | 按类型统计 |

**检索实现（三选一，按复赛落地成熟度）**：
1. **文件系统关键词检索**（最简，复赛首选）：`shared/knowledge/` 里 grep 关键词 + 标签匹配。
2. **向量检索 RAG**（增强，落地成熟）：用嵌入模型把条目向量化，查询时语义检索 Top-K，注入 Agent context。
3. **MCP 检索工具**：封装成 `rag_search` MCP 工具（对齐官方"Skill 封装检索、MCP 接入数据源"）。

### 3.3 检索结果注入（上下文增强）

```
Agent 决策前：
  RAG 检索 top-3 相似经验 → 注入 system prompt 的"相关经验"区
  → Agent 基于历史解法 + 当前 spec 决策，而非从零想
```

> 这实现"**越跑越懂项目**"——下一个类似缺陷直接检索复用，不必重新定位。

---

## 四、Agent 记忆存储（①：跨会话记忆）

### 4.1 两级记忆（对齐 AgentTeams / 常见 Agent 记忆模式）

| 层级 | 内容 | 位置 | 更新 |
|------|------|------|------|
| **短期记忆（会话/日）** | 当天工作日志：读了什么、产出什么、踩了什么坑 | `shared/agents/{name}/memory/YYYY-MM-DD.md` | Agent 每会话追加 |
| **长期记忆** | 稳定的项目知识、偏好、重要决策 | `shared/agents/{name}/memory/MEMORY.md` | Agent 定期整理 |

### 4.2 记忆的作用

- **跨会话连续性**：Worker 无状态重建后，从 `memory/` + MinIO 恢复"我记得什么"，不丢上下文。
- **个性化**：每个 Worker 记住自己在项目中的角色与偏好。
- **动态团队召回**：裁员时 `knowledge_export` 归档记忆 → 召回时重新挂载（`AGENT-IDENTITY.md` §2.2）。

### 4.3 记忆与知识库的分工

| | 知识库 RAG | Agent 记忆 |
|---|-----------|-----------|
| 主体 | 团队共享（多人复用） | 个人私有（本 Agent） |
| 内容 | 沉淀的经验教训 | 工作日志 / 偏好 |
| 生命周期 | 长期（项目级） | 随 Agent 存在/召回 |
| 用途 | RAG 检索复用 | 会话连续性 |

---

## 五、与第 5 项（可观测）的分工

| 数据 | 归属 | 存储 |
|------|------|------|
| Trace/Log/Metrics | 可观测（第 5 项） | OTel 后端 |
| 执行证据/审计 | 共享状态（本文件 ③） | `shared/tasks/{id}/` |
| 知识库 | RAG（本文件 ②） | `shared/knowledge/` |
| Agent 记忆 | 记忆（本文件 ①） | `shared/agents/{name}/memory/` |

> **关联键都是 `task.id`**：观测 → 证据 → 复盘沉淀 → 记忆，通过 task.id 打通整条链路。

---

## 六、满足官方 4 选 2 的证据

| 官方 4 项 | 我们的覆盖 | 文档依据 |
|----------|-----------|---------|
| ① Agent 记忆存储 | ✅ 两级记忆（短期+长期） | 本文件 §四 |
| ② 知识库 RAG | ✅ 复盘沉淀 + 检索注入 | 本文件 §三 |
| ③ 共享状态管理 | ✅ state.json 状态机 | 本文件 §二 + `PDCA-CLOSED-LOOP.md` |
| ④ 轨迹可观测 | ✅ Trace/Log/Metrics | `OBSERVABILITY.md` |

> **4 项全覆盖**，远超"4 选 2"，是评审亮点。

---

## 七、评审亮点（供 PPT/简介引用）

- **4 选 2 全覆盖**：官方至少实现 2 项，我们 4 项全部覆盖（记忆/RAG/共享状态/可观测）。
- **闭环沉淀**：复盘 → 知识库 → RAG → 反哺根因/修复，实现"越跑越懂项目"。
- **无状态可恢复**：状态/记忆/证据全在 MinIO，Worker 可销毁重建不丢上下文（对齐 AgentTeams 无状态设计）。
- **上下文瘦身**：信息卸载（文件引用 + 检索注入），对齐 Context Engineering，防上下文膨胀。

---

## 八、相关文档索引

- 总体计划：`../PLAN.md`
- 官方 RAG/上下文要求：`../references/docs/OFFICIAL-REQUIREMENTS.md` §六
- 共享状态状态机：`PDCA-CLOSED-LOOP.md`（第 2 项）
- 上下文传递机制：`COLLABORATION-DESIGN.md` §三（第 4 项）
- 可观测：`OBSERVABILITY.md`（第 5 项）
- 动态团队（记忆召回）：`../agents/AGENT-IDENTITY.md` §2.2
- 上下文工程（信息卸载）：`../references/theory/CONTEXT-ENGINEERING.md`
- AgentTeams 共享文件机制：`AGENTTEAMS-INTERNALS.md` §6
