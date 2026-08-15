"""Team 派单验证：向 rnd-team 的 Team Room 给 @team-leader 派单，观察 Leader 是否响应协调。

验证 Team + Leader 两级协作是否跑通：
1. admin 登录 Matrix
2. 确认 admin 在 Team Room（teamRoomID 从 agt get teams -o json 读取）
3. 向 Team Room 发 @team-leader 派单
4. 短轮询读 Team Room 消息，看 Leader 是否响应并开始协调 6 Worker

用法（宿主执行，需 src 在 PYTHONPATH）：
    cd software-dev-fullflow\src
    $env:PYTHONPATH = "c:\...\software-dev-fullflow\src"
    $env:AGENTTEAMS_ADMIN_PASSWORD = "AgentTeams2026!"
    ..\demo\.venv\Scripts\python.exe ..\scripts\verify-team-dispatch.py [等待秒数]
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from loop.agentteams_client import AgtCLI, AgentTeamsClient  # noqa: E402


async def get_team_room_id(client: AgentTeamsClient) -> str:
    """通过 agt CLI 读取 rnd-team 的 teamRoomID。"""
    ok, out, err = await AgtCLI.run("get", "teams", "-o", "json", timeout=30)
    if not ok:
        raise RuntimeError(f"agt get teams 失败: {err}")
    import json
    data = json.loads(out)
    for t in data.get("teams", []):
        if t.get("name") == "rnd-team":
            return t.get("teamRoomID", "")
    return ""


async def main() -> None:
    os.environ.setdefault("AGENTTEAMS_ADMIN_PASSWORD", "AgentTeams2026!")
    timeout = float(os.environ.get("TEAM_WAIT_SECS", "300"))

    client = AgentTeamsClient(mode="docker")

    # 1. 登录
    client.matrix_login()
    print("[1] Matrix 登录成功")

    # 2. 获取 Team Room ID（优先环境变量，否则 agt 读取）
    team_room = os.environ.get("TEAM_ROOM_ID", "")
    if not team_room:
        try:
            team_room = await get_team_room_id(client)
        except RuntimeError as e:
            print(f"[2] agt 读取 Team Room 失败: {e}")
            print("    请用 $env:TEAM_ROOM_ID 直接指定（agt get teams -o json 的 teamRoomID）")
            return
    if not team_room:
        print("[2] 未找到 rnd-team 的 teamRoomID")
        return
    print(f"[2] Team Room: {team_room}")

    # 确认 admin 在 Team Room
    try:
        members = client.get_room_members(team_room)
        print(f"    Team Room 成员: {[m.split(':')[0] for m in members]}")
    except RuntimeError as e:
        print(f"    ⚠ 读取成员失败（admin 可能未加入 Team Room）: {e}")

    # 3. 派单给 @team-leader
    spec = "验证 Team 两级协作：请协调 6 个 Worker 修复登录接口在空用户名时返回 500 的问题"
    client.send_matrix_message(team_room, f"@team-leader {spec}")
    print(f"[3] 任务已发送到 Team Room（@team-leader）")

    # 4. 短轮询观察 Leader 响应
    poll = 10
    elapsed = 0.0
    seen: set[str] = set()
    print(f"[4] 轮询 {timeout:.0f}s，观察 Leader 是否响应协调…")
    while elapsed < timeout:
        await asyncio.sleep(poll)
        elapsed += poll
        try:
            msgs = client.read_room_messages(team_room, 50)
        except Exception:  # noqa: BLE001
            continue
        for m in msgs:
            sender = m["sender"]
            if not sender.startswith(f"@team-leader:"):
                continue
            body = m["content"]
            hit = [k for k in
                   ["TASK_SPEC_READY", "ROOT_CAUSE_FOUND", "FIX_APPLIED",
                    "TEST_PASSED", "RELEASE_OK", "RETROSPECT_DONE", "协调",
                    "@aggregator", "@rootcause", "@fixer", "@tester", "@releaser", "@retrospector"]
                   if k in body]
            if hit and body[:120] not in seen:
                seen.add(body[:120])
                print(f"    [{elapsed:.0f}s] @team-leader 响应，命中: {hit} | {body[:150]}")
        if any("RETROSPECT_DONE" in m.get("content", "") for m in msgs if m["sender"].startswith("@team-leader:")):
            print("\n✅ Leader 已完成并回报 RETROSPECT_DONE —— Team 两级协作验证通过。")
            return
        if elapsed >= 60 and not seen:
            print(f"    ... {elapsed:.0f}s 尚无 Leader 响应（LLM 驱动，可能仍需等待）")
        elif not seen:
            print(f"    ... {elapsed:.0f}s")

    if seen:
        print("\n✅ @team-leader 已响应并开始协调 —— Team 派单链路验证通过。")
        print("    （完整两级闭环约 20-30 分钟，可加长 TEAM_WAIT_SECS 或用监控脚本观察）")
    else:
        print("\n⚠️ 等待窗口内 @team-leader 未响应（可能未收到消息/未加入房间/LLM 慢）。")
        print("    建议：Element Web 检查 Team Room 成员，或加长 TEAM_WAIT_SECS。")


if __name__ == "__main__":
    asyncio.run(main())
