# -*- coding: utf-8 -*-
"""LoongSuite · AgentScope 推理轨迹捕获验证脚本

验证 LoongSuite（官方 AgentTeams 可观测组件）能否捕获 AgentScope Agent 的
推理轨迹，并导出到本地 Jaeger（OTLP 接收端）。

前置条件：
  1. 本地 Jaeger 已启动（OTLP 4318 + UI 16686）：
     docker run -d --name jaeger-loongsuite \
       -e COLLECTOR_OTLP_ENABLED=true -p 16686:16686 -p 4317:4317 -p 4318:4318 \
       jaegertracing/all-in-one:1.60
  2. ~/.loongsuite/bootstrap-config.json 存在且指向本地 Jaeger（见
     demo/loongsuite/bootstrap-config.json）
  3. 依赖：agentscope==2.0.6 + loongsuite-* 0.8.0 + opentelemetry-exporter-otlp

用法：
  python verify-loongsuite-traces.py          # 跑一个 demo Agent，产生轨迹
  python verify-loongsuite-traces.py --query  # 查询 Jaeger 是否收到该服务轨迹

返回：0 成功；非 0 失败（找不到服务或 span）。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import time
import urllib.request

# 修复 LoongSuite bootstrap 破坏 mcp.types 属性绑定的副作用
import mcp as _mcp

_mcp.types = importlib.import_module("mcp.types")

from agentscope.agent import Agent, ReActConfig
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import TextBlock, ToolCallBlock, UserMsg
from agentscope.model import (
    ChatModelBase,
    ChatResponse,
    ChatUsage,
    FinishedReason,
)
from agentscope.tool import FunctionTool, Toolkit

SERVICE_NAME = "agentteams-worker-demo"
JAEGER_QUERY = "http://localhost:16686/api/services"
JAEGER_TRACES = "http://localhost:16686/api/traces"


def search_code(keyword: str) -> str:
    """在代码库中搜索与关键字相关的文件，用于根因定位。

    Args:
        keyword: 要搜索的关键字，例如函数名或错误码。
    """
    return json.dumps(
        {
            "matches": [
                {"file": "src/order/api.py", "line": 42, "hit": f"validate_order({keyword})"},
                {"file": "src/order/service.py", "line": 128, "hit": "if order.total is None: raise 500"},
            ]
        },
        ensure_ascii=False,
    )


class ScriptedChatModel(ChatModelBase):
    """不联网的脚本化模型：按调用次数依次返回「工具调用」→「最终文本」，
    用于在无外部 LLM 的前提下驱动 ReAct 循环走完，从而被 LoongSuite 捕获。
    """

    class Parameters(ChatModelBase.Parameters):
        pass

    def __init__(self) -> None:
        from pydantic import BaseModel

        class _Cred(BaseModel):
            pass

        super().__init__(
            credential=_Cred(),
            model="scripted-demo-worker",
            parameters=self.Parameters(),
            stream=False,
            max_retries=0,
        )
        self.formatter = OpenAIChatFormatter()
        self._call_count = 0

    async def _call_api(self, model_name, messages, tools=None, tool_choice=None, **kwargs):
        self._call_count += 1
        if self._call_count == 1:
            return ChatResponse(
                content=[
                    ToolCallBlock(id="call_1", name="search_code", input='{"keyword": "validate_order"}'),
                ],
                is_last=True,
                usage=ChatUsage(input_tokens=256, output_tokens=32, time=0.8),
                finished_reason=FinishedReason.COMPLETED,
            )
        return ChatResponse(
            content=[
                TextBlock(text="根因已定位：order.total 为 None 时触发 500，需在 validate_order 增加判空。"),
            ],
            is_last=True,
            usage=ChatUsage(input_tokens=320, output_tokens=64, time=0.9),
            finished_reason=FinishedReason.COMPLETED,
        )


async def _run_demo() -> None:
    from opentelemetry.instrumentation.agentscope import AgentScopeInstrumentor

    AgentScopeInstrumentor().instrument()

    from agentscope.permission import PermissionContext, PermissionMode
    from agentscope.state import AgentState

    toolkit = Toolkit(tools=[FunctionTool(search_code)])
    state = AgentState(
        permission_context=PermissionContext(mode=PermissionMode.ACCEPT_EDITS),
    )
    agent = Agent(
        name="worker-rootcause",
        system_prompt=(
            "你是软件研发团队里的根因定位员（RootCause）。当收到缺陷报告时，"
            "先用 search_code 工具在代码库中定位相关实现，再基于证据给出根因。"
        ),
        model=ScriptedChatModel(),
        toolkit=toolkit,
        state=state,
        react_config=ReActConfig(max_iters=5),
    )
    await agent.reply(
        UserMsg(
            name="manager",
            content="缺陷：调用 /order/validate 时，订单总价为空的请求返回 HTTP 500。请定位根因。",
        )
    )


def _query_jaeger() -> int:
    """查询 Jaeger：确认该 service 存在且有 span。返回 0=成功。"""
    with urllib.request.urlopen(JAEGER_QUERY, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    services = data.get("data") or []
    if SERVICE_NAME not in services:
        print(f"FAIL: Jaeger 未收到服务 {SERVICE_NAME}（已收到: {services}）")
        return 1

    url = f"{JAEGER_TRACES}?service={SERVICE_NAME}&limit=5"
    with urllib.request.urlopen(url, timeout=10) as resp:
        traces = json.loads(resp.read().decode("utf-8")).get("data") or []
    if not traces:
        print(f"FAIL: 服务 {SERVICE_NAME} 存在但无 trace")
        return 1

    print(f"PASS: Jaeger 已收到服务 {SERVICE_NAME}，共 {len(traces)} 条 trace")
    for trace in traces:
        ops = [s["operationName"] for s in trace.get("spans", [])]
        agents = sorted({
            t["value"]
            for s in trace.get("spans", [])
            for t in s.get("tags", [])
            if t["key"] == "gen_ai.agent.name"
        })
        print(f"  trace={trace.get('traceID')} spans={ops} agents={agents}")
        expected = {"invoke_agent", "react step", "chat"}
        found = {op.split(" ")[0] for op in ops if op.split(" ")[0] in expected}
        if not found:
            print("  WARN: 未找到预期的推理轨迹 span")
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", action="store_true", help="只查询 Jaeger，不重新跑 demo")
    args = parser.parse_args()

    if args.query:
        return _query_jaeger()

    asyncio.run(_run_demo())
    # OTLP BatchSpanProcessor 默认批量导出，等待一会让 span 落库
    print(f"demo 已跑完，等待 OTLP 批量导出...")
    time.sleep(5)
    return _query_jaeger()


if __name__ == "__main__":
    sys.exit(main())
