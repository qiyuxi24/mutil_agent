#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentScope Runtime 沙箱 MCP 服务（streamable-http 模式）。

把 BaseSandbox / FilesystemSandbox 的能力以 MCP 工具形式暴露给 Higress / Agent 客户端。
复用 agentscope_runtime 官方 mcp_server 的 register_tools，仅把传输层从 stdio 升级为
streamable-http，方便被 Higress McpBridge (proxy 模式) 拉取。

两种后端模式：
  1. 内嵌模式（默认）：本进程直接起 Docker 沙箱容器（BaseSandbox(base_url=None)）
  2. 远程模式：--base-url 指向已启动的 SandboxManager（
     python -m agentscope_runtime.sandbox.manager.server.app），由 Manager 管理容器池

用法（Windows PowerShell，项目根 software-dev-fullflow）：
  # 内嵌模式，单进程直接管 Docker 容器
  demo\.venv\Scripts\python.exe scripts\runtime-sandbox-mcp.py --port 8322

  # 远程模式：先起 Manager，再连它
  demo\.venv\Scripts\python.exe scripts\runtime-sandbox-mcp.py --base-url http://127.0.0.1:8321 --port 8322

健康检查：GET http://127.0.0.1:8322/mcp 应返回 200。
"""
import argparse
import logging
import sys

LOG = logging.getLogger("runtime-sandbox-mcp")


def build_box(args):
    """按参数构造沙箱实例（复用 agentscope_runtime 官方类）。"""
    from agentscope_runtime.sandbox import BaseSandbox
    from agentscope_runtime.sandbox.box.filesystem.filesystem_sandbox import (
        FilesystemSandbox,
    )

    kwargs = {"base_url": args.base_url, "bearer_token": args.bearer_token}

    if args.type == "base":
        if args.workspace_dir:
            kwargs["workspace_dir"] = args.workspace_dir
        return BaseSandbox(**kwargs)

    if args.type == "filesystem":
        if args.workspace_dir:
            # FilesystemSandbox 的参数名是 sandbox_root
            kwargs.pop("workspace_dir", None)
            kwargs["sandbox_root"] = args.workspace_dir
        return FilesystemSandbox(**kwargs)

    raise ValueError(f"不支持的沙箱类型: {args.type}（仅支持 base/filesystem）")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AgentScope Runtime 沙箱 MCP 服务 (streamable-http)"
    )
    parser.add_argument(
        "--type",
        default="base",
        choices=["base", "filesystem"],
        help="沙箱类型（默认 base）",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="SandboxManager 地址（如 http://127.0.0.1:8321）；不传则内嵌模式",
    )
    parser.add_argument("--bearer-token", default=None, help="Manager 鉴权 token")
    parser.add_argument("--workspace-dir", default=None, help="宿主机 workspace 目录")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8322, help="监听端口")
    args = parser.parse_args()

    from agentscope_runtime.sandbox.mcp_server import mcp, register_tools

    box = build_box(args)
    # register_tools 内部会 list_tools()，内嵌模式必须先 start() 创建容器/取得 identity
    try:
        box.start()
    except Exception as e:
        print(f"[runtime-sandbox-mcp] 沙箱启动失败: {e}", flush=True)
        return 1
    register_tools(box)
    print(
        f"[runtime-sandbox-mcp] 启动 streamable-http MCP: {args.host}:{args.port} "
        f"| type={args.type} | backend={'remote:' + args.base_url if args.base_url else 'embedded(Docker)'} "
        f"| sandbox_id={getattr(box, 'sandbox_id', 'n/a')}",
        flush=True,
    )

    app = mcp.streamable_http_app()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
