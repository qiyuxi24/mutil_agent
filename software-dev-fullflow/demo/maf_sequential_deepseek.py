# Copyright (c) Microsoft. All rights reserved.
# 修改自 MAF 官方案例 samples/03-workflows/orchestrations/sequential_agents.py
# 改造点：
#   - 将 FoundryChatClient（需微软账号）替换为 OpenAIChatCompletionClient（OpenAI 兼容协议）
#   - 直接使用 DeepSeek 官方 API（deepseek-v4-flash）即可运行，无需额外账号
#   - 演示 MAF 的「顺序编排（Sequential）」多 Agent 协同：writer → reviewer 共享上下文

import asyncio
import os
from typing import cast

from agent_framework import Agent, AgentResponse, Message
from agent_framework.openai import OpenAIChatCompletionClient
from agent_framework.orchestrations import SequentialBuilder
from dotenv import load_dotenv

# 从 .env 读取配置
load_dotenv()


"""
Sample: Sequential workflow (agent-focused API) with shared conversation context

Build a high-level sequential workflow using SequentialBuilder and two domain agents.
The shared conversation flows through each participant. Each agent appends its
assistant message to the context. The sample prints the original user message plus
the visible outputs from both agents.

Note on internal adapters:
- Sequential orchestration includes small adapter nodes for input normalization
  ("input-conversation"), agent-response conversion ("to-conversation:<participant>"),
  and completion ("complete"). These may appear as ExecutorInvoke/Completed events in
  the stream—similar to how concurrent orchestration includes a dispatcher/aggregator.
  You can safely ignore them when focusing on agent progress.

Prerequisites:
- Set OPENAI_API_KEY / OPENAI_BASE_URL / DEEPSEEK_MODEL in .env (or export them).
"""


async def main() -> None:
    # 1) Create agents，使用 OpenAI 兼容的 Chat Completions 客户端接 DeepSeek
    client = OpenAIChatCompletionClient(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )

    writer = Agent(
        client=client,
        instructions=("You are a concise copywriter. Provide a single, punchy marketing sentence based on the prompt."),
        name="writer",
    )

    reviewer = Agent(
        client=client,
        instructions=("You are a thoughtful reviewer. Give brief feedback on the previous assistant message."),
        name="reviewer",
    )

    # 2) Build sequential workflow: writer -> reviewer
    workflow = SequentialBuilder(participants=[writer, reviewer], output_from="all").build()

    # 3) Run and collect outputs
    prompt = "Write a tagline for a budget-friendly eBike."
    print(f"===== Prompt =====\n{prompt}\n")
    result = await workflow.run(prompt)
    conversation = [Message(role="user", contents=[prompt])]
    for output in result.get_outputs():
        response = cast(AgentResponse, output)
        conversation.extend(response.messages)

    if conversation:
        print("===== Final Conversation =====")
        for i, msg in enumerate(conversation, start=1):
            name = msg.author_name or ("assistant" if msg.role == "assistant" else "user")
            print(f"{'-' * 60}\n{i:02d} [{name}]\n{msg.text}")


if __name__ == "__main__":
    asyncio.run(main())
