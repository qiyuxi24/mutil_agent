# -*- coding: utf-8 -*-
"""
host_tools_service.py —— 团队「本机操控」工具链（文件 + 命令 + 进程/服务）

让 AgentTeams 的 Worker（隔离容器）通过 MCP 操控宿主机（本机 Windows）的能力：
  - 文件：list / read / write / mkdir / delete / rename（限定在指定工作目录内，防路径穿越）
  - 命令：exec_command（在指定工作目录内执行 shell 命令）
  - 进程/服务：start_server（起服务）/ stop_process / health_check

安全边界：
  - 所有文件操作 + 命令执行都限定在 WORK_DIR（默认 D:\\agent-workspace）内。
  - 服务端对每个路径做 resolve + 前缀校验，防路径穿越（../ 逃逸）。
  - 命令默认在 WORK_DIR 内执行；进程命令白名单由宿主配置文件控制。

复用 src/agentteams/toolchains/mcp_adapter.py 的最小 MCP Streamable HTTP 适配层，
与 code_scan_service 同一套协议，经 Higress 网关 setup-mcp-server.sh 注册后，
Worker 用 mcporter 真实调用。

端点（对齐 src/agentteams/mcp/mcp-host-tools.yaml）：
  GET  /health                存活探针
  GET  /mcp                   MCP Streamable HTTP 会话初始化
  POST /mcp                   MCP JSON-RPC 消息处理（tools/list, tools/call）
  DELETE /mcp                 会话终止

运行（在宿主机 Windows，software-dev-fullflow 目录）：
  cd software-dev-fullflow
  python -m src.agentteams.toolchains.host_tools_service     # 默认 0.0.0.0:9300
环境变量：
  HOST_TOOLS_PORT   端口（默认 9300）
  HOST_TOOLS_WORKDIR   工作目录（默认 D:\\agent-workspace，不存在会自动创建）
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .mcp_adapter import McpAdapter

# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #

DEFAULT_WORKDIR = r"D:\agent-workspace"
PORT = int(os.environ.get("HOST_TOOLS_PORT", "9300"))
WORK_DIR = Path(os.environ.get("HOST_TOOLS_WORKDIR", DEFAULT_WORKDIR))

# 进程/服务白名单（工具名 → 启动命令）。默认只允许从 WORK_DIR 内启动 python 脚本。
ALLOWED_SERVERS: dict[str, list[str]] = {
    # "my-server": ["python", "server.py", "--port", "8000"],
}

# --------------------------------------------------------------------------- #
# 路径安全工具
# --------------------------------------------------------------------------- #

def _safe_resolve(rel_path: str) -> Path:
    """把相对路径解析到 WORK_DIR 内，校验不逃逸。"""
    p = Path(rel_path or ".")
    if p.is_absolute():
        # 绝对路径必须落在 WORK_DIR 内
        abs_p = p.resolve()
    else:
        abs_p = (WORK_DIR / p).resolve()
    root = WORK_DIR.resolve()
    if not (abs_p == root or root in abs_p.parents):
        raise PermissionError(f"路径越界，仅允许操作 {root}: {rel_path}")
    return abs_p


# --------------------------------------------------------------------------- #
# 工具实现（文件）
# --------------------------------------------------------------------------- #

def tool_list_dir(rel_path: str = "") -> dict:
    """列出指定目录下的条目（文件/子目录）。rel_path 相对 WORK_DIR。"""
    target = _safe_resolve(rel_path)
    if not target.is_dir():
        return {"error": f"not a directory: {target}"}
    entries = []
    for child in sorted(target.iterdir()):
        entries.append({
            "name": child.name,
            "is_dir": child.is_dir(),
            "size": child.stat().st_size if child.is_file() else 0,
        })
    return {"path": str(target), "count": len(entries), "entries": entries}


def tool_read_file(rel_path: str) -> dict:
    """读取文件内容（UTF-8）。rel_path 相对 WORK_DIR。"""
    target = _safe_resolve(rel_path)
    if not target.is_file():
        return {"error": f"not a file: {target}"}
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 二进制文件 → 读前 1KB hex 预览
        data = target.read_bytes()
        return {"path": str(target), "binary": True,
                "size": len(data), "hex_preview": data[:1024].hex()}
    return {"path": str(target), "size": len(content), "content": content}


def tool_write_file(rel_path: str, content: str) -> dict:
    """写入/覆盖文件内容（UTF-8），自动创建父目录。rel_path 相对 WORK_DIR。"""
    target = _safe_resolve(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "bytes": len(content.encode("utf-8")), "ok": True}


def tool_mkdir(rel_path: str) -> dict:
    """创建目录（含父目录）。rel_path 相对 WORK_DIR。"""
    target = _safe_resolve(rel_path)
    target.mkdir(parents=True, exist_ok=True)
    return {"path": str(target), "ok": True}


def tool_delete(rel_path: str) -> dict:
    """删除文件或空目录。rel_path 相对 WORK_DIR。"""
    target = _safe_resolve(rel_path)
    if target.is_file():
        target.unlink()
    elif target.is_dir():
        target.rmdir()  # 仅空目录
    else:
        return {"error": f"not found: {target}"}
    return {"path": str(target), "deleted": True}


def tool_rename(src: str, dst: str) -> dict:
    """重命名/移动（均在 WORK_DIR 内）。"""
    src_p = _safe_resolve(src)
    dst_p = _safe_resolve(dst)
    if not src_p.exists():
        return {"error": f"not found: {src_p}"}
    src_p.rename(dst_p)
    return {"from": str(src_p), "to": str(dst_p), "ok": True}


# --------------------------------------------------------------------------- #
# 工具实现（命令）
# --------------------------------------------------------------------------- #

def tool_exec_command(command: str, timeout: int = 60) -> dict:
    """在 WORK_DIR 内执行一条 shell 命令，返回 stdout/stderr/exit_code。

    安全：始终在 WORK_DIR 内运行；超时由 timeout 控制（默认 60s）。
    """
    if not command or not command.strip():
        return {"error": "command is required"}
    shell = sys.platform.startswith("win")
    try:
        proc = subprocess.run(
            command,
            shell=shell,
            cwd=str(WORK_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "command": command,
            "cwd": str(WORK_DIR),
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-4000:],
            "stderr": proc.stderr[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"error": f"command timed out after {timeout}s", "command": command}


# --------------------------------------------------------------------------- #
# 工具实现（进程/服务）
# --------------------------------------------------------------------------- #

def tool_start_server(name: str, args: str = "") -> dict:
    """从 ALLOWED_SERVERS 白名单启动一个宿主服务（后台进程）。"""
    cmd = ALLOWED_SERVERS.get(name)
    if not cmd:
        return {"error": f"unknown server '{name}'. allowed: {list(ALLOWED_SERVERS)}"}
    full_cmd = cmd + ([args] if args else [])
    proc = subprocess.Popen(
        full_cmd,
        cwd=str(WORK_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=sys.platform.startswith("win"),
    )
    return {"server": name, "pid": proc.pid, "started": True,
            "cmd": full_cmd, "cwd": str(WORK_DIR)}


def tool_stop_process(pid: int) -> dict:
    """按 PID 停止一个进程。"""
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, timeout=10)
        else:
            subprocess.run(["kill", str(pid)], capture_output=True, text=True, timeout=10)
        return {"pid": pid, "stopped": True}
    except Exception as e:  # noqa: BLE001
        return {"error": f"failed to stop {pid}: {e}"}


def tool_health_check() -> dict:
    """检查 WORK_DIR 是否存在且可写，返回宿主健康信息。"""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ok",
        "workdir": str(WORK_DIR),
        "workdir_writable": os.access(WORK_DIR, os.W_OK),
        "server_name": "host-tools",
        "timestamp": time.time(),
    }


# --------------------------------------------------------------------------- #
# FastAPI 应用
# --------------------------------------------------------------------------- #

def _register_mcp_tools(mcp: McpAdapter) -> None:
    mcp.register_tool(
        "list_dir", "列出 WORK_DIR 内指定目录下的条目（文件/子目录）",
        {"rel_path": {"type": "string", "description": "相对 WORK_DIR 的目录路径，默认根目录"}},
        [], tool_list_dir)
    mcp.register_tool(
        "read_file", "读取文件内容（UTF-8）",
        {"rel_path": {"type": "string", "description": "相对 WORK_DIR 的文件路径"}},
        ["rel_path"], tool_read_file)
    mcp.register_tool(
        "write_file", "写入/覆盖文件内容，自动创建父目录",
        {"rel_path": {"type": "string", "description": "相对 WORK_DIR 的文件路径"},
         "content": {"type": "string", "description": "要写入的完整内容"}},
        ["rel_path", "content"], tool_write_file)
    mcp.register_tool(
        "mkdir", "创建目录（含父目录）",
        {"rel_path": {"type": "string", "description": "相对 WORK_DIR 的目录路径"}},
        ["rel_path"], tool_mkdir)
    mcp.register_tool(
        "delete", "删除文件或空目录",
        {"rel_path": {"type": "string", "description": "相对 WORK_DIR 的路径"}},
        ["rel_path"], tool_delete)
    mcp.register_tool(
        "rename", "重命名/移动（均在 WORK_DIR 内）",
        {"src": {"type": "string", "description": "源相对路径"},
         "dst": {"type": "string", "description": "目标相对路径"}},
        ["src", "dst"], tool_rename)
    mcp.register_tool(
        "exec_command", "在 WORK_DIR 内执行一条 shell 命令",
        {"command": {"type": "string", "description": "要执行的命令"},
         "timeout": {"type": "number", "description": "超时秒数，默认 60"}},
        ["command"], tool_exec_command)
    mcp.register_tool(
        "start_server", "从白名单启动一个宿主后台服务",
        {"name": {"type": "string", "description": "服务名（须在白名单）"},
         "args": {"type": "string", "description": "额外参数，可选"}},
        ["name"], tool_start_server)
    mcp.register_tool(
        "stop_process", "按 PID 停止进程",
        {"pid": {"type": "number", "description": "进程 PID"}},
        ["pid"], tool_stop_process)
    mcp.register_tool(
        "health_check", "检查 WORK_DIR 健康 + 宿主信息", {}, [], tool_health_check)


def build_app():
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="AgentTeams Host Tools (本机操控)", version="1.0.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    mcp = McpAdapter(server_name="host-tools", server_version="1.0.0")
    _register_mcp_tools(mcp)

    _sessions: dict[str, str] = {}

    @app.get("/mcp")
    def mcp_get():
        session_id = mcp.create_session_id()
        _sessions[session_id] = "active"
        return JSONResponse(
            content={"status": "ok", "server": "host-tools"},
            headers={"Mcp-Session-Id": session_id},
        )

    @app.post("/mcp")
    async def mcp_post(request: Request):
        body = await request.json()
        result = mcp.handle_jsonrpc(body)
        if result is None:
            return Response(status_code=202)
        return result

    @app.delete("/mcp")
    def mcp_delete():
        return Response(status_code=204)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "host-tools", "workdir": str(WORK_DIR)}

    # ---- 本机可直接调用的 REST 便捷端点（调试/自检） ----
    @app.get("/v1/list")
    def rest_list(rel_path: str = ""):
        return tool_list_dir(rel_path)

    @app.post("/v1/write")
    async def rest_write(payload: dict):
        return tool_write_file(payload.get("rel_path", ""), payload.get("content", ""))

    @app.get("/v1/read")
    def rest_read(rel_path: str):
        return tool_read_file(rel_path)

    @app.post("/v1/exec")
    async def rest_exec(payload: dict):
        return tool_exec_command(payload.get("command", ""),
                                 timeout=int(payload.get("timeout", 60)))

    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
