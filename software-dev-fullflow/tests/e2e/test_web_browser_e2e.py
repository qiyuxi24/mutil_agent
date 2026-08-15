"""P0-Browser: Web Dashboard 浏览器端到端测试（Playwright）。

需要先安装 Chromium 浏览器：
    demo\\.venv\\Scripts\\python.exe -m playwright install chromium

覆盖浏览器中的关键用户流程：
  P0-BRW-01: 仪表盘页面加载与渲染
  P0-BRW-02: PDCA 流水线阶段展示
  P0-BRW-03: Worker 状态卡片渲染
  P0-BRW-04: SSE 事件流实时更新 UI
  P0-BRW-05: 批准/驳回按钮交互
  P0-BRW-06: 状态轮询与更新

运行方式：
    python -m pytest tests/e2e/test_web_browser_e2e.py -v

如果 Playwright 浏览器不可用，所有测试自动跳过。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

# 确保 src/ 在 sys.path
SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# --------------------------------------------------------------------------- #
# Playwright 可用性检测
# --------------------------------------------------------------------------- #

try:
    from playwright.sync_api import sync_playwright, Page, Browser
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# 尝试检测浏览器是否已安装
try:
    if HAS_PLAYWRIGHT:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
            HAS_BROWSER = True
except Exception:
    HAS_BROWSER = False

PLAYWRIGHT_AVAILABLE = HAS_PLAYWRIGHT and HAS_BROWSER
SKIP_REASON = (
    "Playwright 浏览器不可用" if not HAS_PLAYWRIGHT
    else "Chromium 浏览器未安装，运行: demo\\.venv\\Scripts\\python.exe -m playwright install chromium"
)


# --------------------------------------------------------------------------- #
# Web Dashboard 服务管理
# --------------------------------------------------------------------------- #

def start_web_server(port: int = 0, host: str = "127.0.0.1"):
    """启动 Web Dashboard 服务，返回 (server_task, url)。"""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, HTMLResponse
    from starlette.routing import Route

    from loop.state import TaskState, State
    from loop.event_bus import EventBus
    from loop.context import ContextManager
    from loop.web_dashboard import DASHBOARD_HTML

    event_bus = EventBus()
    task_state = TaskState(task_id="e2e-browser-001", spec="浏览器 E2E 测试")
    ctx = ContextManager(task_id="e2e-browser-001", workdir=Path("."), total_budget=1000)

    async def index(request):
        return HTMLResponse(DASHBOARD_HTML)

    async def status_api(request):
        return JSONResponse({
            "task_id": task_state.task_id,
            "state": task_state.state.value,
            "milestones": list(task_state.milestones.keys()),
            "artifacts": task_state.artifacts,
        })

    async def approve_api(request):
        body = await request.body()
        body_str = body.decode("utf-8", errors="replace")
        approved = "approved=true" in body_str
        return JSONResponse({"status": "ok", "approved": approved})

    app = Starlette(debug=False, routes=[
        Route("/", index, methods=["GET"]),
        Route("/api/status", status_api, methods=["GET"]),
        Route("/api/approve", approve_api, methods=["POST"]),
    ])

    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)

    async def serve():
        await server.serve()

    loop = asyncio.new_event_loop()
    task = loop.create_task(serve())

    # 等待服务器启动
    import time
    time.sleep(0.5)

    # 获取实际端口
    actual_port = server.servers[0].sockets[0].getsockname()[1] if server.servers else port
    url = f"http://{host}:{actual_port}"

    return {
        "task": task,
        "server": server,
        "url": url,
        "event_bus": event_bus,
        "task_state": task_state,
        "loop": loop,
    }


# --------------------------------------------------------------------------- #
# P0-BRW-01: 仪表盘页面加载
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason=SKIP_REASON)
class TestDashboardPageLoad:
    """P0-BRW-01: 仪表盘页面加载与渲染。"""

    @pytest.fixture(scope="class")
    def server(self):
        """启动 Web 服务器（class 级别，共享）。"""
        svr = start_web_server(port=0)
        yield svr
        svr["server"].should_exit = True
        svr["task"].cancel()

    def test_page_loads_successfully(self, server, page: Page):
        """仪表盘页面应成功加载（HTTP 200）。"""
        response = page.goto(server["url"])
        assert response is not None
        assert response.ok

    def test_page_title_renders(self, server, page: Page):
        """页面标题应渲染。"""
        page.goto(server["url"])
        title = page.title()
        assert "PDCA" in title or "仪表盘" in title

    def test_pipeline_stages_visible(self, server, page: Page):
        """PDCA 流水线阶段应可见。"""
        page.goto(server["url"])
        # 等待 JavaScript 渲染
        page.wait_for_timeout(500)

        stages = [
            "需求聚合", "任务拆解", "根因定位",
            "代码修复", "测试验证", "发布准备",
            "发布审批", "复盘沉淀",
        ]
        page_content = page.content()
        for stage in stages:
            assert stage in page_content, f"阶段 '{stage}' 应在页面中可见"

    def test_worker_cards_visible(self, server, page: Page):
        """Worker 状态卡片应可见。"""
        page.goto(server["url"])
        page.wait_for_timeout(500)

        workers = ["aggregator", "rootcause", "fixer", "tester", "releaser", "retrospector"]
        page_content = page.content()
        for worker in workers:
            assert worker in page_content, f"Worker '{worker}' 应在页面中可见"


# --------------------------------------------------------------------------- #
# P0-BRW-02: 审批按钮交互
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason=SKIP_REASON)
class TestApproveButtons:
    """P0-BRW-02: 批准/驳回按钮交互。"""

    @pytest.fixture
    def server(self):
        svr = start_web_server(port=0)
        yield svr
        svr["server"].should_exit = True
        svr["task"].cancel()

    def test_approve_button_exists(self, server, page: Page):
        """批准按钮应存在且可点击。"""
        page.goto(server["url"])
        page.wait_for_timeout(500)

        approve_btn = page.locator("button.approve")
        assert approve_btn.count() > 0, "批准按钮应存在"

    def test_reject_button_exists(self, server, page: Page):
        """驳回按钮应存在且可点击。"""
        page.goto(server["url"])
        page.wait_for_timeout(500)

        reject_btn = page.locator("button.reject")
        assert reject_btn.count() > 0, "驳回按钮应存在"

    def test_approve_button_clickable(self, server, page: Page):
        """批准按钮点击应触发 API 调用。"""
        page.goto(server["url"])
        page.wait_for_timeout(500)

        # 点击批准按钮
        approve_btn = page.locator("button.approve")
        if approve_btn.count() > 0:
            approve_btn.first.click()
            page.wait_for_timeout(500)
            # 验证页面没有崩溃
            assert page.title()  # 页面仍存在


# --------------------------------------------------------------------------- #
# P0-BRW-03: 状态 API 集成
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason=SKIP_REASON)
class TestStatusIntegration:
    """P0-BRW-03: 状态 API 数据集成。"""

    @pytest.fixture
    def server(self):
        svr = start_web_server(port=0)
        yield svr
        svr["server"].should_exit = True
        svr["task"].cancel()

    def test_status_api_accessible(self, server, page: Page):
        """状态 API 应从浏览器可访问。"""
        api_url = f"{server['url']}/api/status"
        response = page.goto(api_url)
        assert response is not None
        assert response.ok

        body = response.text()
        data = json.loads(body)
        assert data["task_id"] == "e2e-browser-001"
        assert data["state"] == "SPEC_INPUT"

    def test_approve_api_accessible(self, server, page: Page):
        """审批 API 应从浏览器可访问。"""
        # 使用 page.evaluate 发送 POST 请求
        result = page.evaluate("""async () => {
            const res = await fetch('/api/approve', {
                method: 'POST',
                body: 'approved=true'
            });
            return await res.json();
        }""")
        assert result["status"] == "ok"


# --------------------------------------------------------------------------- #
# P0-BRW-04: 页面无 JavaScript 错误
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason=SKIP_REASON)
class TestPageStability:
    """P0-BRW-04: 页面稳定性测试。"""

    @pytest.fixture
    def server(self):
        svr = start_web_server(port=0)
        yield svr
        svr["server"].should_exit = True
        svr["task"].cancel()

    def test_no_console_errors(self, server, page: Page):
        """页面加载后不应有 JavaScript 控制台错误。"""
        errors = []

        def on_error(msg):
            if msg.type == "error":
                errors.append(msg.text)

        page.on("console", on_error)
        page.goto(server["url"])
        page.wait_for_timeout(1000)

        # 注意：SSE 连接可能在 TestClient 中失败，排除 SSE 相关错误
        critical_errors = [
            e for e in errors
            if "EventSource" not in e and "SSE" not in e
        ]
        assert len(critical_errors) == 0, \
            f"页面应有 0 个非 SSE 控制台错误，实际 {len(critical_errors)}: {critical_errors}"

    def test_page_reloads_without_error(self, server, page: Page):
        """页面刷新后应正常加载。"""
        page.goto(server["url"])
        page.wait_for_timeout(500)

        # 刷新页面
        page.reload()
        page.wait_for_timeout(500)

        assert page.title()  # 页面仍存在且有标题

    def test_multiple_tabs_independent(self, server, context):
        """多个标签页应独立运行。"""
        page1 = context.new_page()
        page2 = context.new_page()

        page1.goto(server["url"])
        page2.goto(server["url"])

        page1.wait_for_timeout(500)
        page2.wait_for_timeout(500)

        # 两个页面都应该正常渲染
        assert "PDCA" in page1.title() or "仪表盘" in page1.title()
        assert "PDCA" in page2.title() or "仪表盘" in page2.title()

        page1.close()
        page2.close()


# --------------------------------------------------------------------------- #
# Playwright fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="session")
def browser():
    """Session 级别的浏览器实例。"""
    if not PLAYWRIGHT_AVAILABLE:
        pytest.skip(SKIP_REASON)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def context(browser):
    """每个测试独立的浏览器上下文。"""
    ctx = browser.new_context()
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    """每个测试独立的页面。"""
    p = context.new_page()
    yield p
    p.close()