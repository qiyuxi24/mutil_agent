---
name: doc-management
description: 文档全生命周期管理：用可恢复运行状态机跟踪文档任务的多阶段进度（大纲→初稿→评审→定稿→归档），阶段执行与验收分离（done ≠ accepted），跨模型/确定性验收后才算定稿，断点可恢复。触发词：文档管理、文档任务、评审、验收、定稿、归档、长文档、doc run、文档状态。
assign_when: 需要管理长文档任务的阶段状态、对文档产物做验收门禁、文档任务中断后续跑、或跟踪整套交付文档的产出进度时分配；Leader 编排文档类任务、DocManager 管理文档生命周期时默认启用。
---

# Skill: doc-management

管理**文档任务**的完整生命周期：每个文档任务是一个有序 phase 列表，逐阶段推进，**执行与验收分离**——executor 只负责写到 `done`，`accepted`（定稿）必须由确定性验证或跨模型评审写入。

## 核心思想（ARIS acceptance-gate 原则）

> **loop 可以 DRIVE 恢复，不能 ACQUIT（自我验收）自己。**

- `done` = 执行完成（executor 自我报告，可暂停/继续）
- `accepted` = 验收通过（确定性验证脚本 / 跨模型评审，附 `verdict_id` + reviewer）
- `provisional` = 同族评审通过（可推进，但不视为正式定稿）
- 恢复时前向解析到第一个**非终态** phase：`done` 但未 `accepted` 的 phase 会**重新验收**，绝不静默跳过

## 工具

状态机脚本（原封不动引入，勿改）：`vendor/aris/run_state.py`（依赖同目录 `provenance.py`）。

```bash
python vendor/aris/run_state.py start <root> <run_id> --phases 大纲,初稿,评审,定稿,归档 --executor claude
python vendor/aris/run_state.py set    <root> <run_id> <phase> done --artifact <path>
python vendor/aris/run_state.py accept <root> <run_id> <phase> --verdict-id <验证报告/脚本名> --reviewer <codex|gemini|deterministic:verify_doc.py>
python vendor/aris/run_state.py resume <root> <run_id>
python vendor/aris/run_state.py status <root> <run_id>
```

- `<root>` 建议用任务目录 `src/data/shared/tasks/{id}/`，状态落在 `<root>/.aris/runs/<run_id>.json`
- `<run_id>` 用 `{task_id}-{doc}`（如 `t-42-prd`）

## 执行步骤

1. **规划 phases**：按文档类型定阶段（通用五段：`大纲→初稿→评审→定稿→归档`，可按需增删）。
2. **start**：创建运行，记录 executor。
3. **推进**：每完成一个 phase 的产出 → `set ... done --artifact <产物路径>`；产物写入任务目录并记录 evidence-log。
4. **验收**：
   - **确定性验证优先**（推荐）：写一个小验证脚本（如检查必填章节、字数、链接有效、docx/pdf 能打开）→ `accept --reviewer deterministic:<脚本>`。
   - 无确定性验证时用**跨模型评审**：`accept --reviewer codex`（须提供评审 trace/报告 id 作为 `verdict-id`）。
   - 只有同族模型可用时用 `mark-provisional`，并在状态里明确它是 provisional（不算定稿）。
5. **中断恢复**：进程中断后重跑 `resume` 得到第一个未终态 phase，从那里继续；`done` 未 `accepted` 的 phase 重新执行验收。
6. **归档**：全部 `accepted` 后，产物归入任务产物目录，`status` 显示 COMPLETE，写 evidence-log `doc_accepted`。

## 验收门禁（gate）示例

```bash
# 运行前把 gate 结果记录进 run 状态（可审计）
python vendor/aris/run_state.py gate-set <root> <run_id> --gate 必填章节 --verdict PASS --reasons "需求/设计/测试/发布/复盘五章齐全"
```

> 注：若当前 run_state.py 无 `gate-set` 子命令，跳过此步，直接以 `accept` 的 `--verdict-id` 承载验证报告路径即可。

## 使用规范

- **不修改 `vendor/aris/` 下文件**；需要新能力时在 `src/loop/` 下写本项目自己的模块，后续再融合。
- `accepted` 必须带 `verdict_id`（验证脚本路径 / 评审报告 id）+ reviewer，缺一不可。
- 同族自评不得写成 `accepted`（会触发 provenance 的 cross-family 校验），只能 `provisional`。
- 文档任务状态在 `audit/audit.jsonl` 留痕，AuditLogger 记录 `doc_phase_done` / `doc_accepted`。
