"""⚠️ ⚠️ ⚠️  [DEPRECATED / 已废弃，仅保留作参考]  ⚠️ ⚠️ ⚠️

本模块：逆向 API 适配层 —— OpenAI 兼容网关（曾用于 CodeBuddy 逆向端点桥接）

【废弃原因】
  参赛主路径已切换为 AgentTeams 官方平台 + DeepSeek API Key 直连（OpenAI 兼容协议原生支持），
  不再需要通过逆向 CodeBuddy 桌面版作为模型通道。本文件仅保留给后续若需接入非标准模型端点时参考。

【当前状态】
  - 不被 run.py、agentteams_loop.py、loop/__init__.py 等参赛主路径模块 import
  - 仅 test_context_with_api.py / verify_reverse_api.py 等手工调试脚本会引用
  - 不随参赛代码包的单元测试、集成测试、演示脚本加载执行

================================================================================
逆向 API 适配层 —— OpenAI 兼容网关（打通 AgentTeams 的关键桥接）。

背景：
  AgentTeams 的 Higress 网关 / CoPaw 运行时都用 `/v1/chat/completions` 协议路径，
  而逆向的 CodeBuddy 端点只认 `/v2/chat/completions`（且强制 stream=true、需要特殊 header）。
  所以不能直接让 AgentTeams 网关代理逆向端点，必须在两者之间加这个适配层。

作用：
  把 OpenAI 兼容的 `/v1/chat/completions` 请求，转换成逆向端点所需的
  `/v2/chat/completions` + stream=true + X-User-Id/X-Domain header，并透传 SSE 流。

用法：
  python reverse_gateway.py
  监听 http://127.0.0.1:9001/v1/chat/completions

接入 AgentTeams：
  controller 环境变量改为：
    AGENTTEAMS_LLM_PROVIDER=openai-compat
    AGENTTEAMS_OPENAI_BASE_URL=http://<本机IP>:9001/v1
    AGENTTEAMS_LLM_API_KEY=<任意非空>   # 适配层不校验，透传逆向凭据
  （需重启 agentteams-controller 使配置生效）

安全：
  适配层只允许本机/内网访问；不做鉴权（透传本地 auth 凭据）。
  生产/参赛演示建议加 key 校验。
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workbuddy_client import WorkBuddyClient  # noqa: E402

# 逆向端点（固定）
REVERSE_BASE = "https://copilot.tencent.com"
REVERSE_PATH = "/v2/chat/completions"

# 模型名映射：AgentTeams 传入的 model → 逆向端点支持的 model
# 当前 AgentTeams DEFAULT_MODEL=deepseek-v4-flash，与逆向端点一致，直接透传。
# 若 AgentTeams 传其他模型名（如 openclaw 默认的 gpt-5.4），这里映射。
MODEL_MAP: dict[str, str] = {
    "deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek-v4-pro",
    "hunyuan-2.0-instruct": "hunyuan-2.0-instruct",
}

app = FastAPI(title="Reverse API Gateway (CodeBuddy → AgentTeams)")

# 全局客户端（复用 workbuddy_client 的 auth 加载）
_client: WorkBuddyClient | None = None
_client_lock = threading.Lock()


def get_client() -> WorkBuddyClient:
    """懒加载全局 WorkBuddyClient（auth 从本地文件读取）。"""
    global _client
    with _client_lock:
        if _client is None:
            _client = WorkBuddyClient()
        return _client


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """OpenAI 兼容的模型列表（供 AgentTeams/openclaw 探测）。"""
    return {
        "object": "list",
        "data": [
            {"id": mid, "object": "model", "owned_by": "reverse-gateway"}
            for mid in MODEL_MAP
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> StreamingResponse:
    """接收 OpenAI 兼容请求，转发到逆向端点并透传 SSE 流。"""
    import httpx

    body = await request.json()
    # 模型名映射
    model = body.get("model", "deepseek-v4-flash")
    model = MODEL_MAP.get(model, model)

    # 透传关键参数；强制 stream=true（逆向端点必需）
    payload: dict[str, Any] = {
        "model": model,
        "messages": body.get("messages", []),
        "stream": True,
        "max_tokens": body.get("max_tokens", 2048),
        "temperature": body.get("temperature", 0.7),
    }
    # 兼容 openclaw 可能传的工具参数
    for k in ("tools", "tool_choice", "functions", "stop", "top_p"):
        if k in body:
            payload[k] = body[k]

    client = get_client()
    headers = client._headers()
    headers["Accept"] = "text/event-stream"

    url = f"{REVERSE_BASE}{REVERSE_PATH}"

    async def sse_proxy():
        """把逆向端点的 SSE 流透传给 AgentTeams 客户端。"""
        async with httpx.AsyncClient(timeout=300) as hc:
            async with hc.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    err = await resp.aread()
                    yield f"data: {json.dumps({'error': {'message': err.decode('utf-8', 'ignore')[:500], 'type': 'upstream_error', 'code': resp.status_code}})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                # 透传上游 SSE 行；确保以 [DONE] 结束
                saw_done = False
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line == "data: [DONE]":
                        saw_done = True
                        yield line + "\n\n"
                        break
                    yield line + "\n\n"
                if not saw_done:
                    yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_proxy(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    # 自检：加载凭据
    try:
        c = get_client()
        print(f"✓ 凭据加载成功 uid={c.info['uid']}")
    except Exception as e:
        print(f"✘ 凭据加载失败: {e}")
        sys.exit(1)
    print("适配层启动: http://127.0.0.1:9001/v1/chat/completions")
    print("启动前请确认逆向 key 可用（python verify_reverse_api.py）")
    uvicorn.run(app, host="0.0.0.0", port=9001, log_level="warning")
