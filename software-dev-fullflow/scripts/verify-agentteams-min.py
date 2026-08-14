"""最小验证：真实 AgentTeams 平台的最小闭环链路。

不做完整闭环（太慢，deepseek-v4-flash 单次 2-4 分钟），只验证：
1. Matrix 登录（平台 API 连通）
2. 动态找到/建立与 @manager 的 DM 房间
3. 向 Manager 发送一个 PDCA 任务
4. 短轮询 N 秒，观察 Manager 是否开始响应（出现里程碑词 TASK_SPEC_READY 或 Manager 的指令）

用法（宿主执行）：
    cd software-dev-fullflow\src
    $env:AGENTTEAMS_ADMIN_PASSWORD = "AgentTeams2026!"
    ..\demo\.venv\Scripts\python.exe scripts\..\loop\..\..\verify_agentteams_min.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from loop.agentteams_client import AgtCLI, AgentTeamsClient  # noqa: E402


async def main() -> None:
    os.environ.setdefault("AGENTTEAMS_ADMIN_PASSWORD", "AgentTeams2026!")
    os.environ.setdefault("AGENTTEAMS_MANAGER_USER", "manager")

    client = AgentTeamsClient(mode="docker")
    spec = "验证最小链路：修复登录接口在空用户名时返回 500 的问题"

    # 1. 平台连通 + Matrix 登录
    ok, out, _ = await AgtCLI.run("get", "managers", timeout=10)
    print(f"[1] agt get managers → exit={ok}")
    if ok:
        print(f"    {out.strip()}")

    try:
        client.matrix_login()
        print("[2] Matrix 登录成功")
    except Exception as e:  # noqa: BLE001
        print(f"[2] Matrix 登录失败: {e}")
        return

    # 2. 找/建 Manager DM 房间
    try:
        room_id = client.ensure_manager_room()
        print(f"[3] Manager DM 房间: {room_id}")
    except RuntimeError as e:
        print(f"[3] 找/建 Manager 房间失败: {e}")
        return

    # 3. 发任务
    try:
        client.send_matrix_message(room_id, f"【PDCA 闭环任务】\n{spec}\n请按 6 Worker 流水线接力，输出里程碑词")
        print("[4] 任务已发送到 Manager 房间")
    except Exception as e:  # noqa: BLE001
        print(f"[4] 发送任务失败: {e}")
        return

    # 4. 短轮询观察 Manager 响应（默认 180s）
    timeout = float(os.environ.get("VERIFY_WAIT_SECS", "180"))
    poll = 10
    elapsed = 0.0
    seen: set[str] = set()
    print(f"[5] 轮询 {timeout:.0f}s，观察 Manager 是否开始响应…")
    while elapsed < timeout:
        await asyncio.sleep(poll)
        elapsed += poll
        try:
            msgs = client.read_room_messages(room_id, 50)
        except Exception:  # noqa: BLE001
            continue
        for m in msgs:
            if m["sender"].startswith(f"@{client.manager_user}:"):
                body = m["content"]
                hit = [k for k in
                       ["TASK_SPEC_READY", "ROOT_CAUSE_FOUND", "FIX_APPLIED",
                        "TEST_PASSED", "RELEASE_OK", "RETROSPECT_DONE"]
                       if k in body]
                if hit and body not in seen:
                    seen.add(body)
                    print(f"    [{elapsed:.0f}s] Manager 响应，里程碑: {hit} | {body[:120]}")
        if seen:
            print("\n✅ Manager 已开始响应并推进任务 —— 最小链路验证通过。")
            print(f"    （完整闭环约 20-30 分钟，可用 run.py --mode delegated 或监控脚本观察）")
            return
        print(f"    ... {elapsed:.0f}s 尚无响应")

    print("\n⚠️  在等待窗口内 Manager 未出现里程碑（LLM 驱动，单次调用 2-4 分钟，属正常）。")
    print("    可加长 VERIFY_WAIT_SECS 或用 run.py --mode delegated 跑完整闭环。")


if __name__ == "__main__":
    asyncio.run(main())
