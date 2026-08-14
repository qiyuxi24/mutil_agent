"""验证逆向 API key 工具链地基 —— 测试路径兼容性与协议要求。

目标：判断「能否直接让 AgentTeams 网关代理逆向端点」，还是需要加适配层。
测试 4 个关键未知点（各 1 次轻量调用，最小 token 消耗）：
  1. /v2/chat/completions + stream=true（workbuddy_client 已知可用）→ 基线
  2. /v2/chat/completions + stream=false → 是否报 11101（验证 stream 必须）
  3. /v1/chat/completions + stream=true + 标准 Bearer → 模拟 Higress 网关，是否兼容
  4. 缺 X-User-Id / X-Domain header → 是否必须

用法：python verify_reverse_api.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workbuddy_client import WorkBuddyClient  # noqa: E402


def call(desc: str, path: str, headers: dict, body: dict) -> tuple[str, int]:
    """发一个请求，返回 (状态码, 响应前 200 字符)。"""
    url = f"https://copilot.tencent.com{path}"
    try:
        r = requests.post(url, headers=headers, json=body, timeout=60, stream=True)
        text = ""
        if r.status_code == 200:
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                if line[6:] == "[DONE]":
                    break
                try:
                    chunk = json.loads(line[6:])
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    text += delta.get("content", "")
                except Exception:
                    pass
                if len(text) > 100:
                    break
        return desc, f"[{r.status_code}] {text[:100] or r.text[:150]}"
    except Exception as e:
        return desc, f"EXC {type(e).__name__}: {str(e)[:150]}"


def main() -> None:
    print("=== 逆向 API key 工具链地基验证 ===\n")
    client = WorkBuddyClient()
    hdr = client._headers()
    base_body = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "回复OK两个字"}],
        "max_tokens": 10,
    }

    results = []

    # 测试 1: /v2 + stream=true（基线，已知可用）
    body = {**base_body, "stream": True}
    results.append(call("① /v2 路径 + stream=true (基线)", "/v2/chat/completions", hdr, body))

    # 测试 2: /v2 + stream=false（验证 stream 是否必须 → 11101?）
    body = {**base_body, "stream": False}
    results.append(call("② /v2 路径 + stream=false", "/v2/chat/completions", hdr, body))

    # 测试 3: /v1 + stream=true + 标准 Bearer（模拟 Higress 网关转发）
    # 注意：去掉 X-User-Id / X-Domain，模拟纯 OpenAI 网关（网关不转发自定义 header）
    hdr_v1 = {"Authorization": hdr["Authorization"], "Content-Type": "application/json"}
    body = {**base_body, "stream": True}
    results.append(call("③ /v1 路径 + stream=true + 无X-User-Id", "/v1/chat/completions", hdr_v1, body))

    # 测试 4: /v1 + stream=true + 全 header（含 X-User-Id / X-Domain）
    body = {**base_body, "stream": True}
    results.append(call("④ /v1 路径 + stream=true + 全header", "/v1/chat/completions", hdr, body))

    print(f"{'测试项':<45} {'结果':<50}")
    print("-" * 95)
    for desc, res in results:
        print(f"{desc:<45} {res:<50}")

    print("\n=== 结论判断 ===")
    ok3 = "[" in results[2][1] and results[2][1].startswith("[200]")
    ok4 = "[" in results[3][1] and results[3][1].startswith("[200]")
    if ok4:
        print("✅ /v1 + 全header 可用 → 可直接让 AgentTeams 网关代理（需注入 X-User-Id/X-Domain）")
    elif ok3:
        print("⚠️ /v1 + 标准 Bearer 可用 → 网关可代理但需确认模型名")
    else:
        print("❌ /v1 路径不兼容 → 需在网关与逆向端点间加 OpenAI 兼容适配层")
    print(f"  ③ 状态: {results[2][1][:8]} | ④ 状态: {results[3][1][:8]}")


if __name__ == "__main__":
    main()
