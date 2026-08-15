"""只读监控脚本：捕获真实 AgentTeams 平台上的完整 PDCA 闭环。

区别于 `run.py`（会新建任务），本脚本**只读**现有房间，不创建/不派发新任务，
用于正式演示时被动观察 Manager 已驱动的 6 Worker 闭环推进，避免干扰现场任务。

行为：
1. Matrix 登录（只读平台）
2. 扫描 admin 已加入的所有房间（覆盖 admin+manager+worker 三方房间）
3. 持续轮询 detect_milestones，展示里程碑推进时间线（含首次出现时间）
4. 命中 RETROSPECT_DONE 即认为闭环完成，打印总结退出

用法（宿主执行）：
    cd software-dev-fullflow
    $env:AGENTTEAMS_ADMIN_PASSWORD = "AgentTeams2026!"
    python scripts/watch-pdca-closed-loop.py
    # 可选：$env:WATCH_SECS=1800  $env:POLL_SECS=10

⚠️ 只读：不调用 create/update/delete worker，不 send_matrix_message 派发任务。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from loop.agentteams_client import AgtCLI, AgentTeamsClient  # noqa: E402

# 闭环里程碑出现顺序（用于判断推进是否符合预期）
CLOSURE_ORDER = [
    "TASK_SPEC_READY",
    "ROOT_CAUSE_FOUND",
    "FIX_APPLIED",
    "TEST_PASSED",
    "RELEASE_OK",
    "RETROSPECT_DONE",
]


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


async def main() -> None:
    os.environ.setdefault("AGENTTEAMS_ADMIN_PASSWORD", "AgentTeams2026!")
    os.environ.setdefault("AGENTTEAMS_MANAGER_USER", "manager")

    timeout = float(os.environ.get("WATCH_SECS", "1800"))   # 默认 30 分钟
    poll = float(os.environ.get("POLL_SECS", "10"))

    client = AgentTeamsClient(mode="docker")

    # 平台连通性
    ok, out, _ = await AgtCLI.run("get", "managers", timeout=10)
    if not ok:
        print(f"[{_now()}] ⚠ agt get managers 失败（平台未就绪？）")
        return
    print(f"[{_now()}] 平台连通 OK\n{out.strip()}")

    try:
        client.matrix_login()
        print(f"[{_now()}] Matrix 登录成功（只读观察模式）")
    except Exception as e:  # noqa: BLE001
        print(f"[{_now()}] Matrix 登录失败: {e}")
        return

    start = time.time()
    seen: dict[str, float] = {}      # milestone -> 首次观测到的相对秒
    print(f"[{_now()}] 开始只读观察 {timeout:.0f}s，扫描全部房间中的里程碑…")

    while time.time() - start < timeout:
        await asyncio.sleep(poll)
        try:
            milestones = await client.detect_milestones(task_id="")
        except Exception as e:  # noqa: BLE001
            print(f"[{_now()}] ⚠ detect_milestones 异常: {e}")
            continue

        fresh = False
        for m in milestones:
            name = m["milestone"]
            if name not in seen:
                seen[name] = round(time.time() - start, 1)
                worker = m.get("worker", "?")
                print(f"[{_now()}] +{seen[name]:>6.1f}s 里程碑 {name} ← {worker}")
                fresh = True

        if "RETROSPECT_DONE" in seen:
            elapsed = round(time.time() - start, 1)
            print(f"\n✅ 闭环完成！观测耗时 {elapsed:.0f}s")
            _print_summary(seen)
            return

        # 每隔一段时间静默提示仍在观察（避免输出刷屏）
        if not fresh and int(time.time() - start) % 60 < poll and seen:
            current = _next_expected(seen)
            print(f"[{_now()}] ... 仍在观察，当前最近里程碑: {current}")

    print(f"\n⚠️  观察窗口 {timeout:.0f}s 内未出现 RETROSPECT_DONE（LLM 驱动较慢或任务未运行）。")
    if seen:
        print("已观测到的里程碑：")
        _print_summary(seen)


def _next_expected(seen: dict[str, float]) -> str:
    """返回下一个预期里程碑（根据已观测到的最深位置）。"""
    for name in CLOSURE_ORDER:
        if name not in seen:
            return name
    return "RETROSPECT_DONE"


def _print_summary(seen: dict[str, float]) -> None:
    print("\n里程碑时间线：")
    for name in CLOSURE_ORDER:
        if name in seen:
            print(f"    {name:<20} +{seen[name]:>6.1f}s")
        else:
            print(f"    {name:<20} （未观测到）")


if __name__ == "__main__":
    asyncio.run(main())
