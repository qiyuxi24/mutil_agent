# ⚠️ 本脚本仅作「选型对比参考」，非参赛实现。参赛协同基点为阿里官方 AgentTeams。
# 交互版：MAF Sequential 多 Agent 协同（writer → reviewer）
# 运行后输入任意主题，观察两个 Agent 依次接力、共享上下文协作。
# 输入 q / quit 退出。
# 用法：.venv\Scripts\python.exe maf_sequential_interactive.py

import asyncio
import os
from typing import cast

from agent_framework import Agent, AgentResponse, Message
from agent_framework.openai import OpenAIChatCompletionClient
from agent_framework.orchestrations import SequentialBuilder
from dotenv import load_dotenv

load_dotenv()


def build_workflow():
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
    return SequentialBuilder(participants=[writer, reviewer], output_from="all").build()


async def run_once(prompt: str) -> None:
    workflow = build_workflow()
    print(f"\n===== Prompt =====\n{prompt}\n")
    try:
        result = await workflow.run(prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"[运行出错] {exc}")
        return

    conversation = [Message(role="user", contents=[prompt])]
    for output in result.get_outputs():
        response = cast(AgentResponse, output)
        conversation.extend(response.messages)

    print("===== Final Conversation =====")
    for i, msg in enumerate(conversation, start=1):
        name = msg.author_name or ("assistant" if msg.role == "assistant" else "user")
        print(f"{'-' * 60}\n{i:02d} [{name}]\n{msg.text}")


async def main() -> None:
    print("=== MAF 多 Agent 顺序协同 Demo（writer → reviewer，共享上下文）===")
    print("输入一个主题/需求，writer 先产出，reviewer 再评审。输入 q 退出。")
    while True:
        try:
            prompt = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not prompt or prompt.lower() in {"q", "quit", "exit"}:
            break
        await run_once(prompt)


if __name__ == "__main__":
    asyncio.run(main())
