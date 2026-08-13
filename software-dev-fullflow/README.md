# 赛道三 · 软件研发全流程协同

> GOAI 世界人工智能开源大赛 — Agent Infra（新智基座）赛道 · 方向三
> 赛事官网：https://www.goaihz.com/tracks

## 选题方向

围绕「缺陷/需求聚合 → 代码根因定位 → 修复方案生成与执行 → 测试验证与发布确认 → 复盘与知识沉淀」构建 **多 Agent 闭环**。

可参考场景：
- 多源缺陷/需求信息聚合与去重（Issue、日志、用户反馈）
- 代码缺陷自动定位与影响面分析
- 修复方案生成与自动化编码执行
- 测试验证与灰度发布结果确认
- 上线复盘与研发知识库沉淀

## 核心要求（开发必读）

1. **多 Agent 协同（硬性）**：至少 3 个不同职能的 Agent，每个有清晰身份定义；以 **AgentTeams（原名 Hiclaw）** 为协同设计基点；需提交 Agent Identity 清单（参赛手册附录A）；说明闭环：任务输入 → 任务拆解 → 上下文传递 → 工具调用 → 结果验证 → 执行证据沉淀 → 审批与回滚 → 经验沉淀
2. **Skill（必选）**：核心 Skill 清单（名称/用途/输入输出/调用条件/依赖工具/失败处理/安全边界/复用价值）
3. **MCP 与工具集成（推荐）**：MCP 推荐接入协议；未用 MCP 需给出等价契约
4. **可观测（推荐）**：Trace / Log / Metrics 至少 1-2 类
5. **RAG 与上下文增强（推荐）**：Agent 记忆存储 / 知识库 RAG / 共享状态管理 / 轨迹可观测 4 项至少实现 2 项
6. **工具链**：AgentTeams（必须）、云 Skills 门户、Nacos/Higress/PolarDB/RocketMQ/LoongSuite（推荐）

## 赛程与提交

| 阶段 | 时间 | 提交材料 |
|------|------|----------|
| 报名 | 7.16 起 | 报名信息 |
| 初赛 | 7.16–8.16 | ①作品简介(500字内) ②方案PPT ③(可选)可执行代码包 |
| 初赛评审 | 8.17–8.24 | 复赛名单 Top30 |
| 复赛 | 8.25–9.3 | ①更新版方案 ②AgentTeams 代码包 ③Demo/视频 |
| 决赛 | 9.22 | 路演PPT + 现场Demo + 代码仓库最终版 |

## 评审权重

- 场景价值与行业可复制性 **25%**
- 多 Agent 协同与自主闭环能力 **25%**
- Skill 工程体系与生态复用 **25%**
- 工程落地、运行验证与安全可审计 **20%**
- 开放/开源贡献 **5%**

## 项目目录结构

```
software-dev-fullflow/
├── .gitignore
├── README.md            ← 本文件
├── design/              ← 架构设计与多 Agent 闭环设计（待产）
├── skills/              ← 核心 Skill 清单与定义（待产）
├── agents/              ← Agent 身份定义（待产）
├── src/                 ← 核心实现（AgentTeams 协同代码包，待产）
├── demo/                ← Demo / 演示脚本（待产）
├── references/          ← 参考资料集（第三方源码仓库 + 理论/学习文档，整体已被 gitignore），说明见 references/README.md
│   ├── refs/            ← AgentTeams / AgentScope / UnifiedModel 参考仓库
│   ├── agent-framework/ ← MAF 微软参考实现
│   ├── theory/          ← 理论依据（THEORY / THEORY-REFERENCE / FRAMEWORK-COMPARISON）
│   └── docs/            ← OFFICIAL-REQUIREMENTS / MAF-LEARNING-PATH
└── data/                ← 运行数据（已被 gitignore）

## 理论目录（references/theory/）

> 理论文档已随参考资料整体并入 `references/`（已被 gitignore）。原内容：
- `THEORY.md`：赛道特殊性分析 + 五大理论板块（需求缺陷/流程/质量/闭环/多Agent协作）+ 推荐的"PDCA 总纲 + 三条子原理"框架
- `THEORY-REFERENCE.md`：理论速查表，供写 PPT / 作品简介 / Agent Identity 时快速引用
- `FRAMEWORK-COMPARISON.md`：AgentTeams vs Microsoft Agent Framework 深度对比（架构/并发/核心代码定位/选型建议）

## 参考框架：Microsoft Agent Framework（references/agent-framework/）

本地已通过镜像拉取微软开源的多 Agent 工作流框架（源码约 4861 个文件，Python + .NET 双实现），源码位于 `references/agent-framework/`（已被 gitignore）。

**定位**：生产级 AI Agent 与多 Agent 工作流构建框架，核心是**图式工作流引擎**（graph-based workflow）。

**与赛道三高度契合的能力**：
- **多 Agent 编排**：顺序 / **并发** / 交接（handoff）/ 群组协作
- **图式工作流**：核心源码在 `python/packages/core/src/agent_framework/_workflows/`（`_workflow.py` / `_edge.py` / `_workflow_builder.py` / `_executor.py`）
- **Agent Skills**：领域知识/能力封装（`_skills.py`）
- **MCP 集成**：原生支持（`_mcp.py`），对接赛道"工具集成"
- **可观测**：内置 OpenTelemetry（`observability.py`）
- **声明式 Agent**：YAML 定义（`declarative-agents/`）
- **审批/工具授权**：`_harness/_tool_approval.py`，对应赛道"审批与回滚"

> 注意：本仓库通过 `ghfast.top` 镜像拉取（直连 github.com 不通）。官方最新仓库：https://github.com/microsoft/agent-framework
> 建议：AgentTeams 为参赛必须的协同基点，MAF 可作为参考实现/备选技术栈，两者需在方案中说明关系（兼容性/替代原因）。
>
> **参考资料汇总见 `references/README.md`**（含 AgentTeams/AgentScope/UnifiedModel/MAF 的来源、用途与拉取说明，整体已被 gitignore）。
```
