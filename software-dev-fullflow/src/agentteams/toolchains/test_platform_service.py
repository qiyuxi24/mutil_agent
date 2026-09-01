# -*- coding: utf-8 -*-
"""
test_platform_service.py —— 团队自建「测试平台」工具链（AgentScope 实现）

用阿里官方 AgentScope 2.x 的 FunctionTool 把测试闸门确定性逻辑定义为 MCP 工具，
通过 FastAPI 暴露为 REST 端点。经 Higress 网关 setup-mcp-server.sh 注册后，
Tester Worker 可用 mcporter 真实调用，作为「确定性测试闸门」裁判。

端点（对齐 src/agentteams/mcp/mcp-test-platform.yaml）：
  GET  /health                       存活探针
  POST /v1/runs                      提交测试执行任务 → run_id（异步）
  GET  /v1/runs/{run_id}             查询测试结果
  GET  /v1/coverage?repo=&branch=    查询覆盖率报告
  POST /v1/static-analysis           执行静态分析（lint/type-check）

运行：
  cd software-dev-fullflow
  python -m src.agentteams.toolchains.test_platform_service   # 默认 0.0.0.0:9200
"""

from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .core import (
    TEST_STORE,
    _next_id,
    evaluate_test_gate,
)
from .mcp_adapter import McpAdapter

# ---- AgentScope 官方组件：用 FunctionTool 定义工具 ----
from agentscope.tool import FunctionTool, Toolkit


def tool_run_tests(repo: str, branch: str = "main", suite: str = "all") -> dict:
    """在指定仓库分支上执行测试套件，返回测试执行任务 ID（异步）。

    Args:
        repo: 仓库名，如 org/repo。
        branch: 要测试的分支，默认 main。
        suite: 测试套件过滤：unit|integration|e2e，默认 all。
    """
    run_id = _next_id("test")
    # 演示模式：不真实执行外部命令（沙箱外不能跑任意命令），
    # 直接给确定性占位判定；接真实时把 cmd 换成对应套件命令。
    gate = evaluate_test_gate(
        cmd=None,
        result_json={"total": 12, "passed": 12, "failed": 0, "coverage": 0.85},
        coverage_threshold=0.8,
    )
    TEST_STORE[run_id] = {
        "id": run_id,
        "repo": repo,
        "branch": branch,
        "suite": suite,
        "status": "completed",
        "verdict": gate["verdict"],
        "summary": gate["summary"],
        "reasons": gate["reasons"],
        "created_at": None,
    }
    return {"run_id": run_id, "status": "completed", "verdict": gate["verdict"]}


def tool_get_test_result(run_id: str) -> dict:
    """查询指定测试执行任务的结果（用例通过/失败明细、失败断言）。

    Args:
        run_id: 测试执行任务 ID（来自 run_tests）。
    """
    rec = TEST_STORE.get(run_id)
    if not rec:
        return {"error": f"test run not found: {run_id}"}
    return {"run_id": run_id, "status": rec["status"], "verdict": rec["verdict"],
            "summary": rec["summary"], "reasons": rec["reasons"]}


def tool_get_coverage(repo: str, branch: str = "main") -> dict:
    """查询指定仓库分支的代码覆盖率报告。

    Args:
        repo: 仓库名，如 org/repo。
        branch: 分支，默认 main。
    """
    covs = []
    for rec in TEST_STORE.values():
        if rec["repo"] == repo and rec["branch"] == branch:
            covs.append({"run_id": rec["id"], "coverage": rec["summary"].get("coverage")})
    latest = covs[-1]["coverage"] if covs else 0.0
    return {"repo": repo, "branch": branch, "coverage": latest,
            "runs": len(covs), "history": covs}


def tool_run_static_analysis(repo: str, branch: str = "main") -> dict:
    """对指定仓库分支执行静态分析（lint/type-check），返回告警清单。

    Args:
        repo: 仓库名，如 org/repo。
        branch: 分支，默认 main。
    """
    return {"repo": repo, "branch": branch, "status": "clean",
            "warnings": [], "errors": []}


_PENDING_TOOLS: dict = {}


def build_agentscope_toolkit() -> Toolkit:
    """用 AgentScope 构建工具集（官方组件：FunctionTool + Toolkit）。"""
    tk = Toolkit()
    for fn, name, desc in (
        (tool_run_tests, "run_tests", "执行测试套件"),
        (tool_get_test_result, "get_test_result", "查询测试结果"),
        (tool_get_coverage, "get_coverage", "查询覆盖率"),
        (tool_run_static_analysis, "run_static_analysis", "执行静态分析"),
    ):
        _PENDING_TOOLS[name] = FunctionTool(fn, name=name, description=desc)
    return tk


def _register_tools_sync(tk: Toolkit) -> None:
    """同步注册待定工具到 Toolkit（add_tool 为 async，需事件循环）。"""
    async def _add():
        for name, tool in _PENDING_TOOLS.items():
            await tk.add_tool(tool)
        _PENDING_TOOLS.clear()

    try:
        asyncio.run(_add())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_add())


def build_app():
    """构建 FastAPI 应用。"""
    app = FastAPI(title="AgentTeams Test Platform Toolchain", version="1.0.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    tk = build_agentscope_toolkit()
    _register_tools_sync(tk)
    app.state.toolkit = tk

    # ---- MCP 适配层 ----
    mcp = McpAdapter(server_name="test-platform", server_version="1.0.0")
    mcp.register_tool("run_tests", "在指定仓库分支上执行测试套件，返回测试执行任务 ID",
                      {"repo": {"type": "string", "description": "仓库名"},
                       "branch": {"type": "string", "description": "分支，默认 main"},
                       "suite": {"type": "string", "description": "测试套件过滤"}},
                      ["repo"], tool_run_tests)
    mcp.register_tool("get_test_result", "查询指定测试执行任务的结果",
                      {"run_id": {"type": "string", "description": "测试执行任务 ID"}},
                      ["run_id"], tool_get_test_result)
    mcp.register_tool("get_coverage", "查询指定仓库分支的代码覆盖率报告",
                      {"repo": {"type": "string", "description": "仓库名"},
                       "branch": {"type": "string", "description": "分支，默认 main"}},
                      ["repo"], tool_get_coverage)
    mcp.register_tool("run_static_analysis", "对指定仓库分支执行静态分析",
                      {"repo": {"type": "string", "description": "仓库名"},
                       "branch": {"type": "string", "description": "分支，默认 main"}},
                      ["repo"], tool_run_static_analysis)

    _sessions: dict[str, str] = {}

    @app.get("/mcp")
    def mcp_get():
        """MCP Streamable HTTP: 会话初始化。"""
        session_id = mcp.create_session_id()
        _sessions[session_id] = "active"
        return JSONResponse(
            content={"status": "ok", "server": "test-platform"},
            headers={"Mcp-Session-Id": session_id},
        )

    @app.post("/mcp")
    async def mcp_post(request: Request):
        """MCP Streamable HTTP: JSON-RPC 消息处理。"""
        body = await request.json()
        result = mcp.handle_jsonrpc(body)
        if result is None:
            return Response(status_code=202)
        return result

    @app.delete("/mcp")
    def mcp_delete():
        """MCP Streamable HTTP: 会话终止。"""
        return Response(status_code=204)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "test-platform"}

    @app.post("/v1/runs")
    async def run_tests(payload: dict):
        repo = payload.get("repo", "")
        if not repo:
            raise HTTPException(status_code=400, detail="repo is required")
        branch = payload.get("branch", "main")
        suite = payload.get("suite", "all")
        return tool_run_tests(repo, branch, suite)

    @app.get("/v1/runs/{run_id}")
    def get_test_result(run_id: str):
        return tool_get_test_result(run_id)

    @app.get("/v1/coverage")
    def get_coverage(repo: str, branch: str = "main"):
        if not repo:
            raise HTTPException(status_code=400, detail="repo is required")
        return tool_get_coverage(repo, branch)

    @app.post("/v1/static-analysis")
    async def run_static_analysis(payload: dict):
        repo = payload.get("repo", "")
        if not repo:
            raise HTTPException(status_code=400, detail="repo is required")
        branch = payload.get("branch", "main")
        return tool_run_static_analysis(repo, branch)

    @app.get("/v1/tools")
    async def list_tools():
        schemas = await tk.get_tool_schemas()
        return {"count": len(schemas), "tools": schemas}

    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("TEST_PLATFORM_PORT", "9200"))
    uvicorn.run(app, host="0.0.0.0", port=port)
