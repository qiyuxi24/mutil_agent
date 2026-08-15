"""E2E 测试共享 fixtures。

提供：
  - web_app: 启动 Web Dashboard Starlette 应用（TestClient）
  - web_server: 真实 uvicorn 服务器（用于 SSE 流测试）
  - cli_runner: CLI run.py 子进程运行器
  - mock_task_state: 完整的 Mock PDCA 闭环 TaskState
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import httpx
from starlette.testclient import TestClient

# 确保 src/ 在 sys.path
SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from loop.state import TaskState, State, Milestone, STATE_EXECUTOR
from loop.event_bus import EventBus
from loop.context import ContextManager


# ========================================================================== #
# Web Dashboard fixtures
# ========================================================================== #

@pytest.fixture
def event_bus():
    """独立的 EventBus 实例。"""
    return EventBus()


@pytest.fixture
def task_state():
    """基础 TaskState 实例。"""
    return TaskState(task_id="e2e-test-001", spec="E2E 测试任务: 修复登录接口空用户名500")


@pytest.fixture
def context_mgr(tmp_path, task_state):
    """ContextManager 实例。"""
    return ContextManager(
        task_id=task_state.task_id,
        workdir=tmp_path,
        total_budget=32000,
    )


@pytest.fixture
def web_app(event_bus, task_state, context_mgr):
    """创建 Web Dashboard Starlette 应用（TestClient）。"""
    from loop.web_dashboard import WebDashboard

    dashboard = WebDashboard(event_bus, task_state, context_mgr, port=0, host="127.0.0.1")

    # 构建 Starlette app（与 WebDashboard.start 内部逻辑一致）
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, HTMLResponse
    from starlette.routing import Route
    try:
        from sse_starlette.sse import EventSourceResponse
    except ImportError:
        from starlette.sse import EventSourceResponse

    async def index(request):
        from loop.web_dashboard import DASHBOARD_HTML
        return HTMLResponse(DASHBOARD_HTML)

    async def events_sse(request):
        import asyncio as aio
        queue: aio.Queue = aio.Queue(maxsize=100)
        dashboard._queues.append(queue)

        async def generate():
            try:
                while True:
                    data = await queue.get()
                    if data is None:
                        break
                    yield {"event": "message", "data": data}
            except aio.CancelledError:
                pass
            finally:
                if queue in dashboard._queues:
                    dashboard._queues.remove(queue)

        return EventSourceResponse(generate())

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
        if approved:
            await event_bus.milestone_reached(
                "human", task_state.task_id, "RELEASE_APPROVED",
                data={"approved": True},
            )
        else:
            await event_bus.milestone_failed(
                "human", task_state.task_id, "RELEASE_REJECTED",
                data={"rejected": True},
            )
        return JSONResponse({"status": "ok", "approved": approved})

    app = Starlette(debug=False, routes=[
        Route("/", index, methods=["GET"]),
        Route("/events", events_sse, methods=["GET"]),
        Route("/api/status", status_api, methods=["GET"]),
        Route("/api/approve", approve_api, methods=["POST"]),
    ])

    return TestClient(app, raise_server_exceptions=False)


# ========================================================================== #
# CLI fixtures
# ========================================================================== #

@pytest.fixture
def run_py_path():
    """run.py 的绝对路径。"""
    p = SRC / "run.py"
    assert p.exists(), f"run.py 不存在: {p}"
    return p


@pytest.fixture
def venv_python():
    r"""demo\.venv 中的 Python 解释器路径。"""
    p = SRC.parent / "demo" / ".venv" / "Scripts" / "python.exe"
    if not p.exists():
        p = SRC.parent / ".venv" / "Scripts" / "python.exe"
    if not p.exists():
        # fallback: 当前 Python
        return Path(sys.executable)
    return p


def run_cli(spec: str, workdir: Path, venv_python: Path, run_py_path: Path,
            extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """运行 CLI run.py 并返回结果。

    Args:
        spec: 任务描述
        workdir: 工作目录
        venv_python: Python 解释器
        run_py_path: run.py 路径
        extra_args: 额外参数（如 --mock）

    Returns:
        subprocess.CompletedProcess
    """
    args = [
        str(venv_python), str(run_py_path),
        "--mock",  # 默认 mock 模式（不依赖 AgentTeams 平台）
    ]
    if extra_args:
        args.extend(extra_args)
    args.append(spec)

    env = {
        **dict(subprocess.os.environ),
        "PYTHONPATH": str(SRC),
        "PYTHONUNBUFFERED": "1",
    }

    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=str(workdir),
        env=env,
        timeout=120,
    )


# ========================================================================== #
# Mock TaskState fixtures
# ========================================================================== #

@pytest.fixture
def mock_task_state():
    """完整的 Mock PDCA 闭环 TaskState（6 里程碑全部达成）。"""
    ts = TaskState(task_id="e2e-mock-001", spec="修复登录接口空用户名500")
    for ms, role in (
        (Milestone.TASK_SPEC_READY, "aggregator"),
        (Milestone.ROOT_CAUSE_FOUND, "rootcause"),
        (Milestone.FIX_APPLIED, "fixer"),
        (Milestone.TEST_PASSED, "tester"),
        (Milestone.RELEASE_OK, "releaser"),
        (Milestone.RETROSPECT_DONE, "retrospector"),
    ):
        ts.advance(ms, by=role)
    ts.artifacts = {st.value: f"{st.value.lower()}.md" for st in State}
    return ts


# ========================================================================== #
# 异步 HTTP 客户端（用于 SSE 流测试）
# ========================================================================== #

@pytest.fixture
async def async_client():
    """异步 httpx 客户端。"""
    async with httpx.AsyncClient() as client:
        yield client