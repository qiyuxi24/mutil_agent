"""逆向 API 适配层 —— OpenAI 兼容网关。

背景：
  AgentTeams 的 Higress 网关 / CoPaw 运行时都用 `/v1/chat/completions` 协议路径，
  而逆向的 CodeBuddy 端点只认 `/v2/chat/completions`（且强制 stream=true、需要特殊 header）。
  所以不能直接让 AgentTeams 网关代理逆向端点，必须在两者之间加这个适配层。

作用：
  把 OpenAI 兼容的 `/v1/chat/completions` 请求，转换成逆向端点所需的
  `/v2/chat/completions` + stream=true + X-User-Id/X-Domain header，并透传 SSE 流。

双模式支持：
  - 逆向模式（默认）：通过 CodeBuddy auth 凭据 → copilot.tencent.com/v2
  - DeepSeek 直连模式（fallback）：通过 DEEPSEEK_API_KEY → api.deepseek.com/v1

用法：
  python src/loop/reverse_gateway.py
  监听 http://0.0.0.0:9001/v1/chat/completions

接入 AgentTeams：
  controller 环境变量改为：
    AGENTTEAMS_LLM_PROVIDER=openai-compat
    AGENTTEAMS_OPENAI_BASE_URL=http://host.docker.internal:9001/v1
    AGENTTEAMS_LLM_API_KEY=sk-reverse-gateway-local
  （需重建 agentteams-controller 使配置生效）
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

# 确保 src/loop 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ------------------------------------------------------------------ #
# 模式检测：优先逆向模式，fallback DeepSeek 直连
# ------------------------------------------------------------------ #

REVERSE_AVAILABLE = False
DEEPSEEK_AVAILABLE = bool(os.environ.get("DEEPSEEK_API_KEY"))

try:
    from workbuddy_client import WorkBuddyClient  # noqa: E402

    _client = WorkBuddyClient()
    REVERSE_AVAILABLE = True
except (RuntimeError, ImportError) as e:
    print(f"[reverse_gateway] 逆向模式不可用 ({e})，将使用 DeepSeek 直连模式")
    _client = None

# 模型名映射
MODEL_MAP: dict[str, str] = {
    "deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek-v4-pro",
    "hunyuan-2.0-instruct": "hunyuan-2.0-instruct",
}

# 逆向端点
REVERSE_BASE = "https://copilot.tencent.com"
REVERSE_PATH = "/v2/chat/completions"

# DeepSeek 端点
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_PATH = "/v1/chat/completions"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

app = FastAPI(title="Reverse API Gateway (LLM → AgentTeams)")
_client_lock = threading.Lock()


def get_mode() -> str:
    """返回当前模式: 'reverse' | 'deepseek' | 'none'."""
    if REVERSE_AVAILABLE:
        return "reverse"
    if DEEPSEEK_AVAILABLE:
        return "deepseek"
    return "none"


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """OpenAI 兼容的模型列表。"""
    return {
        "object": "list",
        "data": [
            {"id": mid, "object": "model", "owned_by": "reverse-gateway"}
            for mid in MODEL_MAP
        ],
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    """健康检查端点。"""
    return {"status": "ok", "mode": get_mode()}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """接收 OpenAI 兼容请求，转发到上游端点并透传 SSE 流。"""
    mode = get_mode()
    if mode == "none":
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "无可用的 LLM 后端（逆向凭据和 DEEPSEEK_API_KEY 均未配置）", "type": "no_backend"}},
        )

    body = await request.json()

    # 模型名映射
    model = body.get("model", "deepseek-v4-flash")
    model = MODEL_MAP.get(model, model)

    # 是否要求流式
    stream = body.get("stream", True)

    if mode == "reverse":
        return await _proxy_reverse(model, body, stream)
    else:
        return await _proxy_deepseek(model, body, stream)


async def _proxy_reverse(model: str, body: dict, stream: bool) -> StreamingResponse:
    """代理到逆向 CodeBuddy 端点。"""
    import httpx

    payload: dict[str, Any] = {
        "model": model,
        "messages": body.get("messages", []),
        "stream": True,  # 逆向端点强制 stream=true
        "max_tokens": body.get("max_tokens", 2048),
        "temperature": body.get("temperature", 0.7),
    }
    for k in ("tools", "tool_choice", "functions", "stop", "top_p"):
        if k in body:
            payload[k] = body[k]

    headers = _client._headers()
    headers["Accept"] = "text/event-stream"
    url = f"{REVERSE_BASE}{REVERSE_PATH}"

    async def sse_proxy():
        async with httpx.AsyncClient(timeout=300) as hc:
            async with hc.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    err = await resp.aread()
                    yield f"data: {json.dumps({'error': {'message': err.decode('utf-8', 'ignore')[:500], 'type': 'upstream_error', 'code': resp.status_code}})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
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


async def _proxy_deepseek(model: str, body: dict, stream: bool) -> StreamingResponse:
    """代理到 DeepSeek API。"""
    import httpx

    payload: dict[str, Any] = {
        "model": model,
        "messages": body.get("messages", []),
        "stream": stream,
        "max_tokens": body.get("max_tokens", 2048),
        "temperature": body.get("temperature", 0.7),
    }
    for k in ("tools", "tool_choice", "functions", "stop", "top_p"):
        if k in body:
            payload[k] = body[k]

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    if stream:
        headers["Accept"] = "text/event-stream"

    url = f"{DEEPSEEK_BASE}{DEEPSEEK_PATH}"

    async def sse_proxy():
        async with httpx.AsyncClient(timeout=300) as hc:
            async with hc.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    err = await resp.aread()
                    yield f"data: {json.dumps({'error': {'message': err.decode('utf-8', 'ignore')[:500], 'type': 'upstream_error', 'code': resp.status_code}})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
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


# ------------------------------------------------------------------ #
# 启动入口
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    mode = get_mode()
    if mode == "reverse":
        print(f"OK 逆向模式: uid={_client.info['uid']}")
    elif mode == "deepseek":
        print(f"OK DeepSeek 直连模式: {DEEPSEEK_BASE}")
    else:
        print("WARN 无可用后端，适配层将返回 503")

    print(f"适配层启动: http://0.0.0.0:9001/v1/chat/completions")
    print(f"健康检查: http://localhost:9001/health")
    uvicorn.run(app, host="0.0.0.0", port=9001, log_level="warning")