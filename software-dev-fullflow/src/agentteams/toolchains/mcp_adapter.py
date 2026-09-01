# -*- coding: utf-8 -*-
"""
mcp_adapter.py —— 最小 MCP Streamable HTTP 协议适配层

为 code_scan_service / test_platform_service 提供 MCP 协议兼容端点，
让 mcporter 可以正常发现工具列表并调用。

MCP Streamable HTTP 协议要点：
  - GET  /mcp → 返回 200 + Mcp-Session-Id header（会话初始化）
  - POST /mcp → JSON-RPC 2.0 消息处理（tools/list, tools/call）
  - DELETE /mcp → 会话终止

仅依赖标准库，不引入额外 MCP SDK。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

# JSON-RPC 2.0 错误码
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


def make_jsonrpc_error(request_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def make_jsonrpc_response(request_id: Any, result: Any) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def build_tool_schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    """构建单个工具 JSON Schema。"""
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
    }


class McpAdapter:
    """最小 MCP 适配器，注册工具定义和处理函数。"""

    def __init__(self, server_name: str, server_version: str = "1.0.0"):
        self.server_name = server_name
        self.server_version = server_version
        self._tools: dict[str, dict] = {}       # name → schema
        self._handlers: dict[str, Callable] = {}  # name → handler fn

    def register_tool(self, name: str, description: str, properties: dict,
                      required: list[str] | None, handler: Callable) -> None:
        """注册一个工具及其处理函数。"""
        self._tools[name] = build_tool_schema(name, description, properties, required)
        self._handlers[name] = handler

    def _tools_list(self) -> dict:
        return {"tools": list(self._tools.values())}

    def _tools_call(self, params: dict) -> dict:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in self._handlers:
            raise ValueError(f"Unknown tool: {tool_name}")
        result = self._handlers[tool_name](**arguments)
        # MCP 要求返回 content 列表
        return {
            "content": [
                {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
            ]
        }

    def handle_jsonrpc(self, request: dict) -> dict:
        """处理 JSON-RPC 2.0 请求。"""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        if method == "tools/list":
            return make_jsonrpc_response(req_id, self._tools_list())
        elif method == "tools/call":
            try:
                result = self._tools_call(params)
                return make_jsonrpc_response(req_id, result)
            except ValueError as e:
                return make_jsonrpc_error(req_id, JSONRPC_INVALID_PARAMS, str(e))
            except Exception as e:
                return make_jsonrpc_error(req_id, JSONRPC_INTERNAL_ERROR, str(e))
        elif method == "initialize":
            return make_jsonrpc_response(req_id, {
                "protocolVersion": "2025-03-26",
                "serverInfo": {
                    "name": self.server_name,
                    "version": self.server_version,
                },
                "capabilities": {"tools": {}},
            })
        elif method == "notifications/initialized":
            return None  # 通知无需响应
        else:
            return make_jsonrpc_error(req_id, JSONRPC_METHOD_NOT_FOUND, f"Unknown method: {method}")

    def create_session_id(self) -> str:
        return str(uuid.uuid4())