# -*- coding: utf-8 -*-
"""LoongSuite · AgentScope 推理轨迹捕获 Demo

模拟 AgentTeams 里的一个「研发 Worker」（根因定位 + 修复）在 AgentScope 2.0
上做一次 ReAct 推理（带工具调用），用 LoongSuite 的 OTel instrumentation 把
整条推理轨迹（invoke_agent -> react_step -> execute_tool -> llm）导出到本地
Jaeger（http://localhost:4318）。

启动前必须：
  1. 本地已起 Jaeger:  docker run -d --name jaeger-loongsuite \
       -e COLLECTOR_OTLP_ENABLED=true -p 16686:16686 -p 4317:4317 -p 4318:4318 \
       jaegertracing/all-in-one:1.60
  2. 已配 ~/.loongsuite/bootstrap-config.json 指向本地 Jaeger（见同目录
     bootstrap-config.json）
  3. 已设 LOONGSUITE_PYTHON_SITE_BOOTSTRAP=true 环境变量

用法:
  $env:LOONGSUITE_PYTHON_SITE_BOOTSTRAP="true"
  python agentscope_worker_demo.py

跑完后打开 http://localhost:16686 搜索 service=agentteams-worker-demo 即可看到
该 Worker 的推理轨迹瀑布图。
"""

from __future__ import annotations

import asyncio
import importlib
import json
from typing import Any

# ---------------------------------------------------------------------------
# LoongSuite bootstrap 的 OTel auto-instrumentation 会破坏 `mcp.types` 子模块
# 属性绑定（已知副作用）。在 import agentscope 前强制补上该属性，否则
# agentscope.mcp 会因 `module 'mcp' has no attribute 'types'` 而无法导入。
# ---------------------------------------------------------------------------
import mcp as _mcp

_mcp.types = importlib.import_module("mcp.types")

from agentscope.agent import Agent, ReActConfig
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg, TextBlock, ToolCallBlock, UserMsg
from agentscope.model import (
    ChatModelBase,
    ChatResponse,
    ChatUsage,
    FinishedReason,
)
from agentscope.tool import FunctionTool, Toolkit, ToolChoice

# 一个「搜索代码」工具，模拟研发 Worker 的根因定位动作
def search_code(keyword: str) -> str:
    """在代码库中搜索与关键字相关的文件，用于根因定位。

    Args:
        keyword: 要搜索的关键字，例如函数名或错误码。
    """
    return json.dumps(
        {
            "matches": [
                {"file": "src/order/api.py", "line": 42, "hit": f"validate_order({keyword})"},
                {"file": "src/order/service.py", "line": 128, "hit": f"if order.total is None: raise 500"},
            ]
        },
        ensure_ascii=False,
    )


class ScriptedChatModel(ChatModelBase):
    """不联网的脚本化模型：按调用次数依次返回「工具调用」→「最终文本」。

    用来在无外部 LLM / 无配额消耗的前提下，驱动 Agent 走完一次真实的
    ReAct 循环（reasoning -> acting -> 再 reasoning），从而让 LoongSuite
    捕获完整的 span 树。
    """

    class Parameters(ChatModelBase.Parameters):
        pass

    def __init__(self) -> None:
        # credential / model 仅用于满足 ChatModelBase 的接口契约，不真正联网
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
        # AgentScope Agent 会读取 formatter 做消息格式化；脚本化模型不真正联网，
        # 复用 OpenAI formatter 只是占位以通过接口校验。
        self.formatter = OpenAIChatFormatter()
        self._call_count = 0

    async def _call_api(self, model_name, messages, tools=None, tool_choice=None, **kwargs):
        self._call_count += 1
        if self._call_count == 1:
            # 第 1 次：让模型调用 search_code 工具（参数 {"keyword": "validate_order"}）
            return ChatResponse(
                content=[
                    ToolCallBlock(
                        id="call_1",
                        name="search_code",
                        input='{"keyword": "validate_order"}',
                    )
                ],
                is_last=True,
                usage=ChatUsage(input_tokens=256, output_tokens=32, time=0.8),
                finished_reason=FinishedReason.COMPLETED,
            )
        # 第 2 次：输出最终结论（根因已定位）
        return ChatResponse(
            content=[
                TextBlock(text="根因已定位：order.total 为 None 时触发 500，需在 validate_order 增加判空。"),
            ],
            is_last=True,
            usage=ChatUsage(input_tokens=320, output_tokens=64, time=0.9),
            finished_reason=FinishedReason.COMPLETED,
        )


async def main() -> None:
    # LoongSuite 的 auto-instrumentation 在此版本下不会自动发现 agentscope 的
    # entry point，需手动启用插桩（会 wrap Agent.__init__ 注入 middleware）。
    from opentelemetry.instrumentation.agentscope import AgentScopeInstrumentor

    AgentScopeInstrumentor().instrument()

    toolkit = Toolkit(tools=[FunctionTool(search_code)])

    # 无人工值守场景下自动放行工具调用，让 ReAct 循环能完整走完
    # （reasoning -> 工具调用 -> 工具结果 -> 最终结论），从而被 LoongSuite
    # 捕获为完整的 span 树。
    from agentscope.permission import PermissionContext, PermissionMode
    from agentscope.state import AgentState

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

    reply = await agent.reply(
        UserMsg(
            name="manager",
            content="缺陷：调用 /order/validate 时，订单总价为空的请求返回 HTTP 500。请定位根因。",
        )
    )
    print("\n=== Worker 最终回复 ===")
    print(reply)


if __name__ == "__main__":
    asyncio.run(main())
