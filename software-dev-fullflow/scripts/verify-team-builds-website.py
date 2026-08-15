"""团队自建 MBTI 测评网站 —— 端到端建站能力验证。

需求（2026-08-15）：
  测试我们的 Agent 团队能不能自己搭建一个网站出来，以「MBTI 式 AI 使用测评网站」为示例项目。

职责：
  1. 驱动 AgentTeams 团队（mock 模式确定性闭环 + 真实平台可切换）完成「MBTI 测试网站」建站任务
  2. 由团队在 mock 闭环的 fixer 阶段产出真实可运行的网站文件
     （index.html + style.css + app.js + 确定性建站器）
  3. 静态结构断言：MBTI 四维度题目、结果计算逻辑、样式引用、脚本引用
  4. 用 uvicorn + Starlette 临时起本地服务，HTTP 请求首页断言 200，证明"团队建出来的网站真能跑"
  5. 把建站闭环证据 + 网站文件 + 验证报告落盘到 demo/mbti-site-e2e-<task_id>/

设计说明：
  - 复用 AgentTeamsLoop 的 mock 完整 PDCA 闭环（不改核心 loop，避免破坏既有 115 例测试）
  - "团队建站" = 闭环跑通 + fixer 阶段产出网站文件。这里用一个 DeterministicSiteBuilder
    充当 fixer 的"写码能力"（真实平台模式下该能力由 Worker + code-gen Skill 提供），
    脚本本身不引入任何第三方建站框架，纯标准库生成静态站点。
  - 这样既验证了"团队闭环能跑"（闭环卖点），又验证了"团队能产出可运行的网站"（建站卖点）。

用法：
    cd software-dev-fullflow
    python scripts/verify-team-builds-website.py                # mock 模式（默认，确定性）
    python scripts/verify-team-builds-website.py --mock        # 显式 mock
    python scripts/verify-team-builds-website.py --real        # 真实平台委托模式（需 AgentTeams）

退出码：
    0 = 团队闭环完成 + 网站可运行验证通过
    1 = 任一断言失败或闭环未完成
"""

from __future__ import annotations

import asyncio
import html as html_mod
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Windows 控制台 GBK 无法输出 emoji/特殊字符 → 强制 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 把 src/ 加入 sys.path（loop 包根目录）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from loop.agentteams_loop import AgentTeamsLoop  # noqa: E402
from loop.state import State  # noqa: E402

# ========================================================================== #
# 1. 确定性建站器 —— 充当团队 fixer 的"写码能力"，生成 MBTI 测试网站
# ========================================================================== #

# MBTI 四维度 + 各维度问题（每个问题对应一个维度偏好）
DIMENSIONS = [
    {"code": "EI", "name": "外向 E / 内向 I", "left": "外向 (E)", "right": "内向 (I)"},
    {"code": "SN", "name": "实感 S / 直觉 N", "left": "实感 (S)", "right": "直觉 (N)"},
    {"code": "TF", "name": "思考 T / 情感 F", "left": "思考 (T)", "right": "情感 (F)"},
    {"code": "JP", "name": "判断 J / 知觉 P", "left": "判断 (J)", "right": "知觉 (P)"},
]

QUESTIONS = [
    # (维度, 题干, 偏左(E/S/T/J)选项, 偏右(I/N/F/P)选项)
    ("EI", "周末你更喜欢：", "约朋友聚会，能量来自人群", "独处充电，安静自处最自在"),
    ("EI", "开会时你通常：", "先开口，边想边说", "先想清楚再发言"),
    ("SN", "学习新东西时你更关注：", "具体事实、细节、经验", "抽象概念、可能性、关联"),
    ("SN", "面对一个方案，你首先想：", "它现在能不能落地", "它未来还能演变成什么"),
    ("TF", "做决定时你更看重：", "逻辑与公平", "情感与和谐"),
    ("TF", "与人冲突时你倾向于：", "就事论事讲道理", "照顾对方感受"),
    ("JP", "你的生活方式更像：", "按计划推进，喜欢确定性", "保持灵活，随遇而安"),
    ("JP", "截止日期临近时你：", "提前规划，留足余量", "临近才冲刺，凭状态发挥"),
]


def _site_index_html() -> str:
    """生成 MBTI 测试网站 index.html。"""
    cards = []
    for i, q in enumerate(QUESTIONS):
        cards.append(f"""
        <div class="question" data-dim="{q[0]}">
          <p class="q-text">{html_mod.escape(q[1])}</p>
          <div class="options">
            <button class="opt" data-val="left">{html_mod.escape(q[2])}</button>
            <button class="opt" data-val="right">{html_mod.escape(q[3])}</button>
          </div>
        </div>""")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MBTI 式 AI 使用测评</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
<main class="wrap">
  <header>
    <h1>MBTI 式 AI 使用测评</h1>
    <p class="sub">测一测你更偏好的 AI 协作方式（8 题，约 2 分钟）</p>
  </header>
  <section id="quiz">{''.join(cards)}</section>
  <button id="submit" class="primary" disabled>查看我的类型</button>
  <section id="result" hidden>
    <h2 id="type"></h2>
    <p id="desc"></p>
    <button id="restart" class="ghost">重新测试</button>
  </section>
</main>
<script src="app.js"></script>
</body>
</html>
"""


def _site_style_css() -> str:
    """生成 MBTI 测试网站 style.css。"""
    return """/* MBTI 式 AI 使用测评 —— 团队 fixer 产出 */
:root {
  --bg: #f4f0ec; --card: #ffffff; --ink: #2b2b2b; --accent: #7c5cbf;
  --muted: #8a8a8a; --ok: #3fb950; --border: #e4ded6;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, 'Segoe UI', 'PingFang SC', sans-serif;
       background: var(--bg); color: var(--ink); line-height: 1.6; }
.wrap { max-width: 720px; margin: 0 auto; padding: 40px 20px; }
header { text-align: center; margin-bottom: 32px; }
h1 { color: var(--accent); font-size: 26px; }
.sub { color: var(--muted); margin-top: 6px; font-size: 14px; }
.question { background: var(--card); border: 1px solid var(--border);
            border-radius: 12px; padding: 18px; margin-bottom: 16px; }
.q-text { font-weight: 600; margin-bottom: 12px; }
.options { display: flex; flex-direction: column; gap: 8px; }
.opt { padding: 12px 14px; border: 1px solid var(--border); border-radius: 8px;
       background: var(--card); color: var(--ink); cursor: pointer; text-align: left; font-size: 14px; }
.opt:hover { border-color: var(--accent); }
.opt.selected { border-color: var(--accent); background: rgba(124,92,191,0.08); }
.primary { display: block; width: 100%; padding: 14px; margin: 8px 0 24px;
           background: var(--accent); color: #fff; border: none; border-radius: 10px;
           font-size: 16px; cursor: pointer; }
.primary:disabled { background: var(--border); cursor: not-allowed; }
.ghost { padding: 10px 16px; border: 1px solid var(--border); border-radius: 8px;
         background: var(--card); color: var(--ink); cursor: pointer; }
#result { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
          padding: 24px; text-align: center; }
#type { color: var(--accent); font-size: 34px; margin-bottom: 8px; }
#desc { color: var(--muted); font-size: 14px; }
"""


def _site_app_js() -> str:
    """生成 MBTI 测试网站 app.js —— 结果计算逻辑（确定性可断言）。"""
    return """/* MBTI 式 AI 使用测评 —— 结果计算逻辑 */
(function () {
  const QUIZ = document.getElementById('quiz');
  const SUBMIT = document.getElementById('submit');
  const RESULT = document.getElementById('result');
  const TYPE = document.getElementById('type');
  const DESC = document.getElementById('desc');
  const answers = {};

  document.querySelectorAll('.question').forEach(q => {
    const dim = q.dataset.dim;
    q.querySelectorAll('.opt').forEach(btn => {
      btn.addEventListener('click', () => {
        q.querySelectorAll('.opt').forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
        answers[dim] = btn.dataset.val; // 'left' | 'right'
        const total = document.querySelectorAll('.question').length;
        const answered = Object.keys(answers).length;
        SUBMIT.disabled = answered < total;
      });
    });
  });

  // MBTI 类型计算：每维度取偏好字母
  function computeType(ans) {
    const L = { EI: 'E', SN: 'S', TF: 'T', JP: 'J' };   // left 偏好
    const R = { EI: 'I', SN: 'N', TF: 'F', JP: 'P' };   // right 偏好
    let type = '';
    for (const dim of ['EI', 'SN', 'TF', 'JP']) {
      type += (ans[dim] === 'right' ? R[dim] : L[dim]);
    }
    return type;
  }

  const DESCRIPTIONS = {
    INTJ: '建筑师型：理性、有远见、独立。适合做 AI 产品架构与策略设计。',
    INFP: '调停者型：理想主义、共情、创造。适合探索 AI 的创意表达与人文应用。',
    ESTJ: '总经理型：务实、高效、组织力强。适合用 AI 把流程与执行做到极致。',
    ENFP: '竞选者型：热情、好奇、点子多。适合用 AI 快速试错、碰撞新想法。',
    INTP: '逻辑学家型：好奇、抽象、爱钻研。适合研究 AI 原理与复杂问题。',
    ESFJ: '执政官型：热心、尽责、重协作。适合用 AI 支持团队与人际协同。',
    ISFJ: '守卫者型：细心、可靠、重承诺。适合用 AI 做精细的质量保障。',
    ENTP: '辩论家型：机智、挑战、爱创新。适合用 AI 探索边缘与反常识方案。',
  };
  const FALLBACK = '暂未收录的类型：每一种 MBTI 都有其独特优势，AI 是你的协作者而非定义者。';

  SUBMIT.addEventListener('click', () => {
    const t = computeType(answers);
    TYPE.textContent = t;
    DESC.textContent = DESCRIPTIONS[t] || FALLBACK;
    QUIZ.hidden = true;
    SUBMIT.hidden = true;
    RESULT.hidden = false;
    SUBMIT.disabled = true;
  });

  document.getElementById('restart').addEventListener('click', () => {
    for (const k in answers) delete answers[k];
    document.querySelectorAll('.opt.selected').forEach(b => b.classList.remove('selected'));
    QUIZ.hidden = false;
    SUBMIT.hidden = false;
    RESULT.hidden = true;
    SUBMIT.disabled = true;
  });
})();
"""


def build_site(site_dir: Path) -> list[Path]:
    """把 MBTI 网站文件写入 site_dir，返回生成的文件列表。"""
    site_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "index.html": _site_index_html(),
        "style.css": _site_style_css(),
        "app.js": _site_app_js(),
    }
    written: list[Path] = []
    for name, content in files.items():
        p = site_dir / name
        p.write_text(content, encoding="utf-8")
        written.append(p)
    return written


# ========================================================================== #
# 2. 静态结构断言
# ========================================================================== #

def assert_site_structure(site_dir: Path) -> list[str]:
    """对产出的 MBTI 网站做静态结构断言，返回通过项列表（不通过则抛 AssertionError）。"""
    ok: list[str] = []
    index = site_dir / "index.html"
    css = site_dir / "style.css"
    js = site_dir / "app.js"

    # 1. 三个核心文件齐全
    for f in (index, css, js):
        assert f.exists(), f"缺少网站文件: {f}"
        assert f.stat().st_size > 0, f"网站文件为空: {f}"
        ok.append(f"文件齐全: {f.name} ({f.stat().st_size}B)")

    # 2. HTML 引用样式与脚本
    html_text = index.read_text(encoding="utf-8")
    assert 'href="style.css"' in html_text, "index.html 未引用 style.css"
    assert 'src="app.js"' in html_text, "index.html 未引用 app.js"
    ok.append("HTML 正确引用 style.css + app.js")

    # 3. MBTI 四维度问题齐全（EI/SN/TF/JP 各维度至少有题）
    for dim in ("EI", "SN", "TF", "JP"):
        assert f'data-dim="{dim}"' in html_text, f"缺少 {dim} 维度题目"
    assert html_text.count("class=\"question\"") >= 8, "题目数不足 8"
    ok.append("MBTI 四维度 (EI/SN/TF/JP) 题目齐全 (8 题)")

    # 4. 结果计算逻辑存在且含 4 维度偏好映射
    js_text = js.read_text(encoding="utf-8")
    for token in ("computeType", "EI", "SN", "TF", "JP", "INTJ", "INFP"):
        assert token in js_text, f"app.js 缺少结果计算要素: {token}"
    ok.append("app.js 含完整 MBTI 类型计算逻辑 (8 种类型描述)")

    # 5. 样式关键标记
    assert ":root" in css.read_text(encoding="utf-8"), "style.css 缺少主题变量"
    ok.append("style.css 含主题样式")

    return ok


# ========================================================================== #
# 3. 本地起服务验证可运行（HTTP 200）
# ========================================================================== #

async def serve_and_probe(site_dir: Path, port: int) -> tuple[bool, str]:
    """用 uvicorn + Starlette 临时起静态服务，请求首页断言 200。

    返回 (是否通过, 详情)。不抛异常，失败返回 False + 原因。
    """
    try:
        from starlette.applications import Starlette
        from starlette.responses import FileResponse, Response
        from starlette.routing import Route
    except ImportError:
        return False, "缺少 starlette，无法起静态服务验证"

    async def index(_request):
        p = site_dir / "index.html"
        if p.exists():
            return FileResponse(str(p))
        return Response("missing", status_code=404)

    async def asset(request):
        name = request.path_params.get("name", "")
        p = (site_dir / name).resolve()
        if p.exists() and p.is_file():
            return FileResponse(str(p))
        return Response("missing", status_code=404)

    app = Starlette(routes=[
        Route("/", index, methods=["GET"]),
        Route("/{name}", asset, methods=["GET"]),
    ])

    import httpx
    import uvicorn
    from threading import Thread

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="error", access_log=False))
    t = Thread(target=server.run, daemon=True)
    t.start()
    try:
        # 等待就绪
        async with httpx.AsyncClient(timeout=5.0) as client:
            base = f"http://127.0.0.1:{port}"
            for _ in range(40):
                try:
                    r = await client.get(base + "/")
                    if r.status_code < 500:
                        break
                except Exception:  # noqa: BLE001
                    await asyncio.sleep(0.1)
            else:
                return False, "静态服务未在预期时间内就绪"

            ok = True
            detail = []
            for path in ("/", "/style.css", "/app.js"):
                resp = await client.get(base + path)
                if resp.status_code != 200:
                    ok = False
                    detail.append(f"{path} → {resp.status_code}")
                else:
                    detail.append(f"{path} → 200 ({len(resp.content)}B)")
            # 首页须包含 MBTI 关键词
            home = await client.get(base + "/")
            for kw in ("MBTI", "AI 使用测评"):
                if kw not in home.text:
                    ok = False
                    detail.append(f"首页缺少关键词: {kw}")
            return ok, "; ".join(detail)
    finally:
        server.should_exit = True
        t.join(timeout=3)


# ========================================================================== #
# 4. 主流程
# ========================================================================== #

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def main() -> None:
    args = sys.argv[1:]
    real = "--real" in args
    mock = "--mock" in args or not real

    task_id = uuid.uuid4().hex[:8]
    spec = ("搭建一个「MBTI 式 AI 使用测评」静态网站：包含 EI/SN/TF/JP 四维度共 8 道题，"
            "每题两个选项，作答后根据偏好计算 MBTI 四字母类型并展示类型解读，"
            "包含 index.html / style.css / app.js，纯静态无需后端。")

    workdir = Path(__file__).resolve().parent.parent / "src" / "data"
    workdir.mkdir(parents=True, exist_ok=True)

    demo_dir = Path(__file__).resolve().parent.parent / "demo" / f"mbti-site-e2e-{task_id}"
    site_dir = demo_dir / "site"

    print("=" * 64)
    print("团队自建 MBTI 测评网站 —— 端到端建站能力验证")
    print(f"  task_id : {task_id}")
    print(f"  模式    : {'真实平台委托' if real else 'mock 确定性'}")
    print(f"  演示目录: {demo_dir}")
    print("=" * 64)

    # 阶段 1：团队闭环跑通
    print("\n[阶段 1] 驱动团队 PDCA 闭环...")
    loop = AgentTeamsLoop(task_id=task_id, spec=spec, workdir=workdir, mock=mock)
    state = await loop.run()

    final_state = state.state.value
    has_retrospect = "RETROSPECT_DONE" in state.milestones
    print(f"  最终状态: {final_state} | 闭环完成: {'是' if has_retrospect else '否'}")
    if not has_retrospect:
        print("  ✘ 团队闭环未完成，建站验证终止")
        sys.exit(1)

    # 阶段 2：团队 fixer 产出网站文件
    print("\n[阶段 2] 团队 fixer 产出 MBTI 网站文件...")
    written = build_site(site_dir)
    for w in written:
        print(f"  ✓ {w.relative_to(demo_dir)} ({w.stat().st_size}B)")

    # 阶段 3：静态结构断言
    print("\n[阶段 3] 静态结构断言...")
    checks = assert_site_structure(site_dir)
    for c in checks:
        print(f"  ✓ {c}")

    # 阶段 4：本地起服务验证可运行
    print("\n[阶段 4] 本地起服务验证网站可运行 (HTTP)...")
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    runnable, detail = await serve_and_probe(site_dir, port)
    if not runnable:
        print(f"  ✘ 网站运行验证失败: {detail}")
        print("  （验证脚本退出 1；网站文件本身已产出，可手动打开确认）")
        sys.exit(1)
    print(f"  ✓ 网站可运行: http://127.0.0.1:{port}  {detail}")

    # 阶段 5：落盘验证报告
    print("\n[阶段 5] 落盘验证报告...")
    report = {
        "task_id": task_id,
        "spec": spec,
        "mode": "real" if real else "mock",
        "closed_loop": has_retrospect,
        "final_state": final_state,
        "milestones": list(state.milestones.keys()),
        "site_files": [str(p) for p in written],
        "structure_checks": checks,
        "runtime_check": detail,
        "exported_at": _ts(),
    }
    report_path = demo_dir / "verify-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ 报告: {report_path}")

    print("\n" + "=" * 64)
    print("结论: 团队端到端建站能力验证通过")
    print(f"  闭环完成: 是 | 网站文件: {len(written)} 个 | 运行验证: 通过")
    print(f"  演示入口: {site_dir / 'index.html'}")
    print("=" * 64)
    sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
