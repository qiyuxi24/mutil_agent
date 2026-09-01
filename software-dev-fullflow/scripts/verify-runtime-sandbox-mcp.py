#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
沙箱阶段三验证（服务化）：通过 MCP streamable-http 客户端连接 Runtime Sandbox MCP 服务。

前置：scripts/runtime-sandbox-mcp.py 已启动（默认 http://127.0.0.1:8322/mcp）。
用法（Windows PowerShell，项目根 software-dev-fullflow）：
  demo\.venv\Scripts\python.exe scripts\verify-runtime-sandbox-mcp.py [--url http://127.0.0.1:8322/mcp]

验证项：
  V1 工具清单：应包含 run_ipython_cell / run_shell_command
  V2 run_shell_command：echo 往返
  V3 run_ipython_cell：print 往返 + 计算结果
退出码：0=全部 PASS；1=存在 FAIL；2=无法连接。
"""
import argparse
import asyncio
import sys

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")


def tool_text(result) -> str:
    """从 CallToolResult 中提取文本。"""
    parts = []
    for item in result.content or []:
        t = getattr(item, "text", None)
        if t:
            parts.append(str(t))
    return "\n".join(parts)


async def run(url: str) -> int:
    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    try:
        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                record("V0 MCP 连接", True, f"connected: {url}")

                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                ok = "run_ipython_cell" in names and "run_shell_command" in names
                record(
                    "V1 工具清单",
                    ok,
                    f"共 {len(names)} 个工具: {', '.join(names[:8])}",
                )

                r = await session.call_tool("run_shell_command", {"command": "echo mcp-http-ok"})
                text = tool_text(r)
                ok = "mcp-http-ok" in text
                record("V2 shell echo (HTTP)", ok, text.strip().splitlines()[0] if text.strip() else "(空)")

                r = await session.call_tool("run_ipython_cell", {"code": "print(6 * 7)"})
                text = tool_text(r)
                ok = "42" in text
                record("V3 ipython 计算 (HTTP)", ok, f"6*7 -> {text.strip()!r}")

    except Exception as e:
        record("V0 MCP 连接", False, f"{type(e).__name__}: {e}")
        return 2

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print(f"\n==== 结果汇总: {passed}/{len(RESULTS)} PASS, {failed} FAIL ====")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Runtime Sandbox MCP 服务化验证")
    parser.add_argument("--url", default="http://127.0.0.1:8322/mcp", help="MCP streamable-http 端点")
    args = parser.parse_args()
    return asyncio.run(run(args.url))


if __name__ == "__main__":
    sys.exit(main())
