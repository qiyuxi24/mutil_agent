# -*- coding: utf-8 -*-
"""
code_scan_service.py —— 团队自建「代码扫描」工具链（AgentScope 实现）

用阿里官方 AgentScope 2.x 的 FunctionTool 把代码扫描的确定性逻辑定义为 MCP 工具，
通过 FastAPI 暴露为 REST 端点。经 Higress 网关 setup-mcp-server.sh 注册后，
Fixer Worker 可用 mcporter 真实调用，作为「确定性验证闸门」裁判。

端点（对齐 src/agentteams/mcp/mcp-code-scan.yaml）：
  GET  /health                      存活探针
  POST /v1/scans                    提交代码扫描任务 → scan_id（异步）
  GET  /v1/scans/{scan_id}          查询扫描结果
  GET  /v1/issues?repo=&severity=   列出未关闭问题
  GET  /v1/issues/{issue_id}        获取问题详情

运行：
  cd software-dev-fullflow
  python -m src.agentteams.toolchains.code_scan_service   # 默认 0.0.0.0:9100
"""

from __future__ import annotations

import asyncio
import os

from .core import (
    SCAN_STORE,
    _next_id,
    run_code_scan,
)

# ---- AgentScope 官方组件：用 FunctionTool 定义工具 ----
from agentscope.tool import FunctionTool, Toolkit


def _exec_scan(repo: str, branch: str, workspace: str | None,
               changed_files: list | None, diff_stats: dict | None,
               patch_text: str | None) -> dict:
    """内核执行并落库，返回可直接序列化的结果。"""
    report = run_code_scan(
        repo=repo, branch=branch, workspace=workspace,
        changed_files=changed_files, diff_stats=diff_stats, patch_text=patch_text,
    )
    return report.to_dict()


def tool_start_scan(repo: str, branch: str = "main") -> dict:
    """提交一次代码扫描任务，返回扫描任务 ID（异步）。

    Args:
        repo: 仓库名，如 org/repo。
        branch: 要扫描的分支，默认 main。
    """
    scan_id = _next_id("scan")
    SCAN_STORE[scan_id] = {
        "id": scan_id,
        "repo": repo,
        "branch": branch,
        "status": "pending",
        "report": None,
        "created_at": None,
    }
    # 简化：立即执行确定性扫描（此处 workspace 未指定，仅做 diff/敏感项静态判定）
    report = _exec_scan(repo, branch, workspace=None, changed_files=None,
                        diff_stats=None, patch_text=None)
    SCAN_STORE[scan_id].update(status="completed", report=report)
    return {"scan_id": scan_id, "status": "completed", "repo": repo, "branch": branch}


def tool_get_scan_result(scan_id: str) -> dict:
    """查询指定代码扫描任务的执行结果与问题清单。

    Args:
        scan_id: 扫描任务 ID（来自 start_scan）。
    """
    rec = SCAN_STORE.get(scan_id)
    if not rec:
        return {"error": f"scan not found: {scan_id}"}
    return {"scan_id": scan_id, "status": rec["status"], "report": rec["report"]}


def tool_list_open_issues(repo: str, severity: str = "") -> dict:
    """列出指定仓库当前未关闭的代码扫描问题。

    Args:
        repo: 仓库名，如 org/repo。
        severity: 按严重级别过滤：critical|high|medium|low，空则全部。
    """
    issues = []
    for rec in SCAN_STORE.values():
        if rec["repo"] != repo or not rec["report"]:
            continue
        for issue in rec["report"].get("issues", []):
            item = {"repo": repo, "scan_id": rec["id"], "detail": issue}
            issues.append(item)
    return {"repo": repo, "count": len(issues), "issues": issues}


def tool_get_issue_detail(issue_id: str) -> dict:
    """获取单个代码扫描问题的详情。

    Args:
        issue_id: 问题 ID。
    """
    for rec in SCAN_STORE.values():
        if not rec["report"]:
            continue
        for issue in rec["report"].get("issues", []):
            if str(issue.get("name")) == issue_id or issue_id in str(issue):
                return {"issue_id": issue_id, "repo": rec["repo"],
                        "scan_id": rec["id"], "detail": issue}
    return {"error": f"issue not found: {issue_id}"}


_PENDING_TOOLS: dict = {}


def build_agentscope_toolkit() -> Toolkit:
    """用 AgentScope 构建工具集（官方组件：FunctionTool + Toolkit）。"""
    tk = Toolkit()
    for fn, name, desc in (
        (tool_start_scan, "start_scan", "提交代码扫描任务"),
        (tool_get_scan_result, "get_scan_result", "查询代码扫描结果"),
        (tool_list_open_issues, "list_open_issues", "列出未关闭代码扫描问题"),
        (tool_get_issue_detail, "get_issue_detail", "获取代码扫描问题详情"),
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
        # 已存在运行中的事件循环（uvicorn 场景）时，在 loop 上调度
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_add())


def build_app():
    """构建 FastAPI 应用。"""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="AgentTeams Code Scan Toolchain", version="1.0.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    # 用 AgentScope Toolkit 注册工具（延迟导入避免污染全局）
    tk = build_agentscope_toolkit()
    _register_tools_sync(tk)
    app.state.toolkit = tk

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "code-scan", "agentscope_tools": len(_PENDING_TOOLS) == 0}

    @app.post("/v1/scans")
    async def start_scan(payload: dict):
        repo = payload.get("repo", "")
        if not repo:
            raise HTTPException(status_code=400, detail="repo is required")
        branch = payload.get("branch", "main")
        result = tool_start_scan(repo, branch)
        return result

    @app.get("/v1/scans/{scan_id}")
    def get_scan_result(scan_id: str):
        return tool_get_scan_result(scan_id)

    @app.get("/v1/issues")
    def list_open_issues(repo: str, severity: str = ""):
        if not repo:
            raise HTTPException(status_code=400, detail="repo is required")
        return tool_list_open_issues(repo, severity)

    @app.get("/v1/issues/{issue_id}")
    def get_issue_detail(issue_id: str):
        return tool_get_issue_detail(issue_id)

    @app.get("/v1/tools")
    async def list_tools():
        """暴露 AgentScope Toolkit 的 MCP schema（供排查/演示）。"""
        schemas = await tk.get_tool_schemas()
        return {"count": len(schemas), "tools": schemas}

    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("CODE_SCAN_PORT", "9100"))
    uvicorn.run(app, host="0.0.0.0", port=port)
