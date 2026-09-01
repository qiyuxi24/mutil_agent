# doc-gen — 文档生成工具模块

把 **Markdown / HTML → Word(.docx) / PDF** 的确定性文档生成能力，作为独立 Skill（`skills/doc-gen`）提供给 Agent 团队，用于产出正式交付物（需求文档、设计文档、测试报告、发布说明、复盘报告等）。

## 技术选型（全开源、宽松许可、性价比优先）

| 能力 | 方案 | 许可 | 说明 |
|------|------|------|------|
| Markdown → HTML | `markdown`（Python-Markdown） | BSD-3 | 事实标准，纯 Python |
| HTML → Word | `python-docx` + 自写轻量转换器 | MIT | 事实标准，纯 Python |
| HTML → PDF（主） | `weasyprint` | BSD-3 | 渲染质量高，支持完整 CSS/分页/页码 |
| PDF 兜底 | 降级输出 `.html`（浏览器可打印） | — | 无引擎也能出"可交付文档" |

**为什么这样选**：
- **必装依赖只有 2 个纯 pip 包**（python-docx + markdown），Word 能力零系统依赖，任何环境 `pip install` 即可用。
- weasyprint 是可选增强：装了就出高质量 PDF；不装自动降级 `.html`，绝不阻断 Agent 交付。
- 全部为 MIT/BSD 宽松许可，与本项目开源策略无冲突（无 AGPL/GPL 传染）。
- 不引入 pandoc/LaTeX/LibreOffice 等重量级二进制，容器镜像体积与启动时间都友好。

## 安装

```bash
# 必装（Word 能力 + Markdown 渲染）
pip install python-docx markdown

# 可选（PDF 能力）：Linux 容器先装系统库再 pip
apt-get update && apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 fonts-noto-cjk
pip install weasyprint
```

平台差异：
- **Windows**：`pip install python-docx markdown` 即可；weasyprint 在 Windows 上需 GTK runtime（`https://github.com/niccokunzmann/python-gtk-runtime`），不装则 PDF 降级 `.html`。
- **macOS**：`brew install pango` 后可装 weasyprint。
- **Linux 容器**（AgentTeams Worker）：按上表 apt 安装，中文字体用 `fonts-noto-cjk`。

## 使用

```bash
# Markdown → Word
python skills/doc-gen/scripts/docgen.py md2docx report.md report.docx --font-family "微软雅黑"

# Markdown → PDF（Linux 容器建议指定 Noto 字体）
python skills/doc-gen/scripts/docgen.py md2pdf report.md report.pdf --font-family "Noto Sans CJK SC"

# HTML → Word / PDF
python skills/doc-gen/scripts/docgen.py html2docx page.html page.docx
python skills/doc-gen/scripts/docgen.py html2pdf  page.html page.pdf

# 自定义 CSS（PDF）+ 机器可读结果（供 Agent 解析）
python skills/doc-gen/scripts/docgen.py md2pdf report.md report.pdf --css my.css --json
```

### 命令一览

| 子命令 | 输入 → 输出 | 关键选项 |
|--------|-------------|----------|
| `md2docx` | Markdown → .docx | `--font-family` `--font-size` |
| `md2pdf`  | Markdown → .pdf | `--font-family` `--css` `--no-fallback` |
| `html2docx` | HTML → .docx | `--font-family` `--font-size` |
| `html2pdf`  | HTML → .pdf | `--font-family` `--css` `--no-fallback` |

输入为 `-` 时从 stdin 读取；`--json` 输出 `{ok, output, format, degraded, ...}`。

## 架构（解耦设计）

```
Markdown ──┬──(markdown/markdown-it-py/内置)──► HTML ──┬──(python-docx)──► .docx
           │                                          └──(weasyprint)──► .pdf
           │                                                └──降级────────► .html
```

- **中间层是 HTML**：`_html_to_blocks()` 把 HTML 解析为结构化块树，docx 与 pdf 两个渲染端共用同一中间表示，任何一端增强不影响另一端。
- **docgen.py 完全自包含**：不 import 本项目任何内部模块，可复制到任意环境独立运行，也便于单测。
- **降级链路**：Markdown 引擎 3 级降级（markdown → markdown-it-py → 内置极简渲染器）；PDF 引擎无 weasyprint 时降级 `.html`。

## 测试

```bash
demo\.venv\Scripts\python.exe -m pytest tests/test_docgen.py -q
```

覆盖：md→docx 内容正确性（标题/段落/表格/代码块）、md→pdf 降级与真渲染、html→docx、中文字体设置。

## 常见问题

- **Word 里中文变方块/乱码**：必须传 `--font-family`（Windows 用"微软雅黑"，Linux 容器用"Noto Sans CJK SC"）；脚本已自动设置 `eastAsia` 字体属性。
- **PDF 中文变方块**：容器未装 `fonts-noto-cjk`；或 weasyprint 未装（此时输出的是 `.html` 降级文件，`degraded=true`）。
- **代码块背景**：docx 用灰底 shading 呈现；PDF 用 CSS `pre` 样式呈现。
