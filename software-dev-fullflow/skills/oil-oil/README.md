# 外部 Skill 归档区：oil-oil（油欧呦）

> 归档日期：2026-09-01
> 来源：GitHub 用户 **oil-oil**（林志煌 Zhihuang Lin，https://github.com/oil-oil，个人网站 https://www.oiloil.org/）
> 性质：**外部参考 Skill 库**（Vibe Coding / Claude Code / Codex / Kimi / Grok 生态），按项目 `skills/<name>/` 形式归档，**不挂载任何 Worker**，仅作理念与方法论借鉴。
> 背景：完整人物调查见 `references/oil-oil/INVESTIGATION.md`。

---

## 归档说明

- 本目录下每个子目录 = 一个 oil-oil 的原创 Skill 仓库，目录名保留**仓库名**（来源可追溯），内部结构统一为项目形式：`SKILL.md` + 可选 `scripts/` `references/` `assets/` `agents/`。
- 共 **29 个** skill（2026-09-01 浅克隆 `--depth 1`，经本机代理 127.0.0.1:7890）。
- ⚠️ **frontmatter `name` 不一定等于目录名**（见下方映射表），以 `SKILL.md` 内的 `name` 为准。
- 归档后 `scripts/verify-skill-refs.py` 只核对 `workers.yaml` 引用的 Skill，本归档区不参与挂载、不影响验证。
- 如需借鉴某个 skill 进正式体系：复制其目录到 `skills/<正式名>/`，补 `assign_when` 等字段，再登记 `REGISTRY.md` / `ASSIGNMENT-MATRIX.md`。

---

## Skill 清单（29）

| 目录名（=仓库名） | frontmatter name | 一句话简介 |
|---|---|---|
| `agent-record` | `agent-record` | 用 Agent Record 操作已运行的 Chrome / Ego Lite，录制带自然鼠标、聚焦与说明文字的产品 Demo（2K60/4K60） |
| `beautify-github-readme` | `beautify-github-readme` | 用 SVG 标题 + 真实案例为仓库设计主题化 README 首页 |
| `build-deepseek-harness-plugin` | `build-deepseek-harness-plugin` | 创建/改造/迁移/评审/调试/发布 DeepSeek Harness 可安装组合包（Cordis 装配/Web Client bundle/Slot） |
| `bulkgen-skill` | `bulkgen` | BulkGen 批量生成 Agent Skill |
| `codex` | `codex` | Claude Code Skill：把编码/探索/实现/评审/验证任务派发给持久化 Codex CLI Agent |
| `codex-explore-skill` | `explore` | Codex 子 Agent：编码前的大范围代码库侦察（reconnaissance） |
| `codex-team-mode` | `team-mode` | Codex Skill：协调 4 个自定义子 Agent 做开发/研究/分析/文档/数据/内容 |
| `codex-usage` | `codex-usage` | 生成中文 Codex Token 使用报告（读本机 Codex SQLite state 数据库） |
| `computer-use-skill` | `computer-use` | Claude Code 的 computer use（视觉操作）Skill |
| `draw-ui` | `draw-ui` | Claude Code Skill：生成 UI 设计稿，并把生成的 UI 截图还原成 HTML/CSS |
| `git-ship` | `git-ship` | Codex Agent Skill：分支/PR/合并一键发布（git ship） |
| `grok` | `grok` | Skill：把前端实现/UI 优化/编码/评审/图片生成任务委托给本机 Grok CLI |
| `grok-designer` | `grok-designer` | 把 Grok 4.5 作为外部设计顾问：UI/UX 评审、方案定方向 |
| `html-doc` | `html-doc` | 把 Markdown 转成可读性更强的 HTML 文档（视觉优先） |
| `kimi` | `kimi` | Agent Skill：把设计/前端/编码/仓库探索任务委托给本地 Kimi Code CLI |
| `lumina` | `lark-lumina` | AI 英语外教 Lumina：住在飞书 Base 里、有完整人格与持续记忆的双语学习合伙人 |
| `oil-cover` | `oil-cover` | 生成小红书/B 站 AI 工具实操视频封面（脚本模式与 Agent 自主模式、真实视频证据、三画幅） |
| `oil-html` | `oil-html` | oil 个人专用 HTML 分享文档 skill |
| `oil-ppt` | `oil-ppt` | 创建/修改/检查 16:9 HTML 演示文稿，按需导出混合可编辑 PPTX（默认配 oil-tone） |
| `oil-skill-creator` | `oil-skill-creator` | 像做产品一样写 Skill：创建、评审、整改和发布 Agent Skill |
| `oil-tone` | `oil-tone` | 让 AI 文案保持真实、平实、完整和易读的文风 Skill（中文/英文） |
| `oil-video-article` | `oil-video-article` | 视频转公众号图文工作流：Screen Studio 工程/普通视频 → 本地公众号 Markdown 文章 |
| `oil-visual` | `oil-visual` | 建立一致的 oil 风格视觉系统（manga-ink 插画风，两种模式） |
| `qwen-subtitle` | `qwen-subtitle` | 用阿里云百炼(千问)做视频字幕智能纠错 + 多语言翻译 + 克隆原声配音出海 |
| `react-flow-advanced-best-practices` | `react-flow-advanced-best-practices` | React Flow (@xyflow/react) 专家级指导：架构/性能/类型安全 |
| `screen-studio-editor` | `screen-studio-editor` | 剪辑整理 Screen Studio .screenstudio 工程：删停顿/误讲/重复，合并工程，屏幕轨对齐 PPT |
| `see-skill` | `see` | 多模态视觉桥：拒绝"不支持视觉"，强制模型看图 |
| `vibe-hub-skill` | `vibehub` | 让任何 Agent 帮你学懂 Vibe Coding 术语、把模糊描述改成准确需求 |
| `video-publisher-skill` | `video-publisher` | 为小红书/抖音/B 站/视频号准备并发布验证过的视频草稿 |

---

## 目录名 → frontmatter name 映射（不一致项）

| 目录名 | frontmatter name |
|---|---|
| `bulkgen-skill` | `bulkgen` |
| `codex-explore-skill` | `explore` |
| `codex-team-mode` | `team-mode` |
| `computer-use-skill` | `computer-use` |
| `lumina` | `lark-lumina` |
| `see-skill` | `see` |
| `vibe-hub-skill` | `vibehub` |
| `video-publisher-skill` | `video-publisher` |

---

## 借鉴优先级建议（按与本项目相关性）

1. **`codex-team-mode`（team-mode）**：多 Agent 派发/协作，与本项目 Leader 编排 + Worker 分工同构，已借鉴出 `dispatch-contract`。
2. **`oil-skill-creator`**：Skill 工程方法论（创建/评审/整改/发布），可借鉴完善 `manage-skill`。
3. **`git-ship`**：分支/PR/发布一键流，可借鉴 Releaser 的 `release-gate` 简化路径。
4. **`html-doc` / `beautify-github-readme`**：视觉优先文档，可借鉴 `doc-gen` 的 HTML 中间层渲染。
5. **`oil-tone`**：文案文风规范，可借鉴团队报告/复盘文档的表达风格。
6. **`react-flow-advanced-best-practices`**：如涉及关系图/流程图前端（UModel 可视化）可参考。
