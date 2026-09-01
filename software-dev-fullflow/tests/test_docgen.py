# -*- coding: utf-8 -*-
"""doc-gen 文档生成工具模块（skills/doc-gen/scripts/docgen.py）测试。

覆盖：Markdown 三引擎渲染 / HTML→docx 内容与中文字体 / HTML→pdf 真渲染与降级 / CLI 端到端。
运行：demo\\.venv\\Scripts\\python.exe -m pytest tests/test_docgen.py -q
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

DOCGEN_DIR = Path(__file__).resolve().parent.parent / "skills" / "doc-gen" / "scripts"
DOCGEN = DOCGEN_DIR / "docgen.py"

SAMPLE_MD = """# 测试报告

| 项目 | 内容 |
|------|------|
| 任务 | T-0042 |
| 结论 | 通过 |

## 概述

这是 **加粗** 和 *斜体*，以及 `行内代码`。

- 列表项一
- 列表项二

```python
print("hello")
```

> 重要提示

1. 第一步
2. 第二步
"""


@pytest.fixture(scope="module")
def docgen_mod():
    sys.path.insert(0, str(DOCGEN_DIR))
    import docgen  # type: ignore
    return docgen


# ------------------------------------------------------------
# 一、Markdown → HTML（三引擎）
# ------------------------------------------------------------

def test_md_to_html_builtin_engine(docgen_mod):
    """内置极简渲染器（零依赖兜底）必须能产出完整 HTML。"""
    html, engine = docgen_mod.md_to_html(SAMPLE_MD)
    assert engine in ("markdown", "markdown_it", "builtin")
    assert "<h1" in html
    assert "<h2" in html
    assert "<table" in html and "<th" in html
    assert "<pre" in html and "<code" in html
    assert "<blockquote" in html
    assert "<ul" in html and "<ol" in html


@pytest.mark.parametrize("engine", ["markdown", "markdown_it", "builtin"])
def test_md_to_html_engine_specific(docgen_mod, engine):
    """强制指定引擎（monkeypatch 探测结果）也必须产出关键结构。"""
    import docgen as dg

    original = dg._md_engine

    def fake():
        return engine

    dg._md_engine = fake
    try:
        html, used = dg.md_to_html(SAMPLE_MD)
        assert used == engine
        assert "<h1" in html and "<table" in html and "<pre" in html
    finally:
        dg._md_engine = original


# ------------------------------------------------------------
# 二、HTML → DOCX
# ------------------------------------------------------------

def test_html_to_docx_content(tmp_path, docgen_mod):
    docxlib = pytest.importorskip("docx", reason="需要 python-docx")
    html, _ = docgen_mod.md_to_html(SAMPLE_MD)
    out = tmp_path / "report.docx"
    docgen_mod.html_to_docx(html, out, font_family="微软雅黑")

    assert out.exists() and out.stat().st_size > 0
    doc = docxlib.Document(str(out))

    # 标题
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert any("测试报告" in h for h in headings)
    assert any("概述" in h for h in headings)

    # 段落文本（含行内样式后的纯文本）
    all_text = "\n".join(p.text for p in doc.paragraphs)
    assert "这是" in all_text and "行内代码" in all_text

    # 表格（表头 + 数据）
    assert len(doc.tables) >= 1
    table = doc.tables[0]
    assert table.rows[0].cells[0].text == "项目"
    assert any("T-0042" in cell.text for row in table.rows for cell in row.cells)

    # 列表
    list_styles = [p.style.name for p in doc.paragraphs]
    assert "List Bullet" in list_styles and "List Number" in list_styles


def test_html_to_docx_chinese_font(tmp_path, docgen_mod):
    """中文字体必须写入 eastAsia，避免 Word 中文乱码。"""
    docxlib = pytest.importorskip("docx", reason="需要 python-docx")
    html, _ = docgen_mod.md_to_html(SAMPLE_MD)
    out = tmp_path / "cn.docx"
    docgen_mod.html_to_docx(html, out, font_family="微软雅黑")

    doc = docxlib.Document(str(out))
    style = doc.styles["Normal"]
    rpr = style.element.find(docgen_mod.W_NS + "rPr")
    assert rpr is not None
    rfonts = rpr.find(docgen_mod.W_NS + "rFonts")
    assert rfonts is not None
    assert rfonts.get(docgen_mod.W_NS + "eastAsia") == "微软雅黑"


def test_html_to_docx_direct_html(tmp_path, docgen_mod):
    """HTML 直接转 docx（html2docx 路径），含链接与图片缺省容错。"""
    pytest.importorskip("docx", reason="需要 python-docx")
    html = (
        "<h1>标题</h1><p>段落 <strong>粗</strong> <em>斜</em> "
        "<a href='https://example.com'>链接</a></p>"
        "<pre><code>print(1)</code></pre>"
    )
    out = tmp_path / "page.docx"
    docgen_mod.html_to_docx(html, out)
    assert out.exists()


# ------------------------------------------------------------
# 三、HTML → PDF（weasyprint 真渲染 / 降级 html）
# ------------------------------------------------------------

def test_html_to_pdf_engine_or_fallback(tmp_path, docgen_mod):
    html, _ = docgen_mod.md_to_html(SAMPLE_MD)
    out = tmp_path / "report.pdf"
    result_path, engine = docgen_mod.html_to_pdf(html, out, font_family="Noto Sans CJK SC")

    if engine == "weasyprint":
        assert result_path.suffix == ".pdf"
        assert result_path.read_bytes().startswith(b"%PDF")
    else:
        # 降级：同目录写出 .html，仍可交付
        assert engine == "html_fallback"
        assert result_path.suffix == ".html"
        assert "<table>" in result_path.read_text(encoding="utf-8")


def test_html_to_pdf_no_fallback_raises(tmp_path, docgen_mod):
    """--no-fallback 语义：weasyprint 不可用时抛错而非降级。"""
    import docgen as dg

    if dg._weasyprint_available():
        pytest.skip("weasyprint 已安装，无降级路径可测")

    with pytest.raises(RuntimeError):
        dg.html_to_pdf("<p>x</p>", tmp_path / "a.pdf", allow_fallback=False)


# ------------------------------------------------------------
# 四、CLI 端到端
# ------------------------------------------------------------

def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DOCGEN), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def test_cli_md2docx_json(tmp_path, docgen_mod):
    pytest.importorskip("docx", reason="需要 python-docx")
    src = tmp_path / "in.md"
    src.write_text(SAMPLE_MD, encoding="utf-8")
    out = tmp_path / "out.docx"

    r = _run_cli("md2docx", str(src), str(out), "--json")
    assert r.returncode == 0, r.stderr
    result = json.loads(r.stdout.strip().splitlines()[-1])
    assert result["ok"] and result["format"] == "docx" and result["degraded"] is False
    assert Path(result["output"]).exists()


def test_cli_md2pdf_json(tmp_path, docgen_mod):
    src = tmp_path / "in.md"
    src.write_text(SAMPLE_MD, encoding="utf-8")
    out = tmp_path / "out.pdf"

    r = _run_cli("md2pdf", str(src), str(out), "--json")
    assert r.returncode == 0, r.stderr
    result = json.loads(r.stdout.strip().splitlines()[-1])
    assert result["ok"] and result["format"] == "pdf"
    if result["degraded"]:
        assert result["pdf_engine"] == "html_fallback"
        assert Path(result["output"]).suffix == ".html"
    else:
        assert result["pdf_engine"] == "weasyprint"
        assert Path(result["output"]).read_bytes().startswith(b"%PDF")


def test_cli_md2docx_stdin(tmp_path, docgen_mod):
    """stdin 输入（-）路径。"""
    pytest.importorskip("docx", reason="需要 python-docx")
    r = subprocess.run(
        [sys.executable, str(DOCGEN), "md2docx", "-", str(tmp_path / "stdin.docx"), "--json"],
        input=SAMPLE_MD, capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
    result = json.loads(r.stdout.strip().splitlines()[-1])
    assert result["ok"]
    assert Path(result["output"]).exists()
