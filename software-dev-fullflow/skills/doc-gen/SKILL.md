---
name: doc-gen
description: 文档生成：把 Markdown/HTML 内容渲染为 Word(.docx) 或 PDF，支持中文字体、表格、代码块、页眉页码。触发词：写文档、生成报告、导出 Word、导出 PDF、docx、pdf、排版、正式文档、deliverable。
assign_when: 需要产出正式交付物文档（需求文档/设计文档/测试报告/发布说明/复盘报告/对外汇报）时分配；Leader 汇总团队汇报、Aggregator 写 PRD、RootCause 出 RCA、Tester 出测试报告、Releaser 出发布说明、Retrospector 出复盘报告时默认启用。
---

# Skill: doc-gen

把 Agent 产出的 Markdown 内容一键渲染为 **Word(.docx)** 或 **PDF**，产出可直接交付/归档的正式文档。统一调用 `scripts/docgen.py`（自包含、确定性、可独立测试）。

## 输入

- 源内容：Markdown 文件（推荐，Agent 最擅长产出）或 HTML 文件；也可用 stdin 传入
- 目标格式：`docx`（Word）或 `pdf`（PDF）
- 可选样式：`--font-family`（中文字体）、`--css`（自定义 CSS，仅 PDF）、`--font-size`

## 执行步骤

1. **选格式**：Word 交付物 → `md2docx`；PDF 交付物 → `md2pdf`。
2. **执行命令**（脚本依赖缺失时自动降级，见「降级策略」）：

```bash
python skills/doc-gen/scripts/docgen.py md2docx report.md report.docx \
    --font-family "微软雅黑"            # Linux 容器用 "Noto Sans CJK SC"
python skills/doc-gen/scripts/docgen.py md2pdf report.md report.pdf \
    --font-family "Noto Sans CJK SC"
```

3. **校验产物**：确认输出文件存在且非空；`--json` 模式解析返回的 `{ok, output, format, degraded}`。
4. **归档**：产物放入任务产物目录（如 `shared/tasks/{id}/`），并在 evidence-log 记录 `doc_generated`。

## 降级策略（重要）

- **Markdown 引擎 3 级降级**：`markdown` → `markdown-it-py` → 内置极简渲染器（零依赖也能出文档）。
- **PDF 引擎降级**：weasyprint 未安装/缺系统库时，`md2pdf` 自动降级写出同名的 `.html` 文件（可用浏览器打印为 PDF），`degraded=true`；Word 能力完全不受影响。
- 容器内安装 weasyprint 系统依赖（Linux）：

```bash
apt-get update && apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 fonts-noto-cjk
pip install weasyprint
```

## 输出（DOC_GENERATED）

产物路径 + 格式 + 渲染引擎信息。可用 `--json` 获得机器可读结果：

```json
{"ok": true, "output": "report.pdf", "format": "pdf", "md_engine": "markdown", "pdf_engine": "weasyprint", "degraded": false}
```

## 使用规范

- **内容优先用 Markdown**：表格用 `|` 分隔、代码块用围栏、标题用 `#`；Agent 生成 Markdown 的准确性远高于手写 HTML。
- **中文字体必设**：Word 默认 `微软雅黑`（Windows）/ `Noto Sans CJK SC`（Linux 容器），PDF 默认 `Noto Sans CJK SC`，避免中文乱码/豆腐块。
- 详情见 `README.md`（依赖安装、平台差异、常见问题）与 `references/STYLE.md`（排版规范）。
