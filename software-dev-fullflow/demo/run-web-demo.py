"""Web 仪表盘演示 —— 按真实节奏展示完整 PDCA 闭环。

在浏览器实时看 6 个 Worker 接力完成「缺陷→根因→修复→测试→发布→复盘」。
事件按真实节奏逐阶段推送（不是瞬间刷完），web server 保持运行供查看。

用法：
    ..\demo\.venv\Scripts\python.exe run-web-demo.py
    然后浏览器打开 http://127.0.0.1:8080
    Ctrl+C 停止。

注意：需在 src/ 目录运行（依赖 loop 包）。端口默认 8080。
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# 把 src/ 加入 sys.path
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from loop.agent_bus import EventBus  # noqa: E402
from loop.context import ContextManager  # noqa: E402
from loop.state import TaskState  # noqa: E402
from loop.web_dashboard import WebDashboard  # noqa: E402

PORT = 8080
STAGE_INTERVAL = 1.5  # 每阶段间隔（秒），可按需调整


async def run_demo() -> None:
    task_id = uuid.uuid4().hex[:8]
    spec = "登录接口空用户名返回 500，需定位并修复"
    print(f"任务: {spec}")
    print(f"工作目录: {SRC / 'data' / 'shared' / 'tasks' / task_id}")

    # 共享状态组件
    state = TaskState(task_id=task_id, spec=spec)
    event_bus = EventBus()
    ctx = ContextManager(task_id=task_id, workdir=SRC / "data", total_budget=32000)

    # 启动 Web 仪表盘
    web = WebDashboard(event_bus, state, ctx, port=PORT)
    await web.start()
    print("浏览器打开: http://127.0.0.1:8080")
    print("按 Ctrl+C 停止演示\n")

    # 逐阶段推送事件（模拟真实闭环节奏）
    await event_bus.task_started(task_id, spec)

    stages = [
        # (worker, 里程碑, 阶段说明)
        ("aggregator",  "TASK_SPEC_READY",   "需求聚合：多源缺陷归一化 → spec.md"),
        ("aggregator",  "TASK_SPEC_READY",   "任务拆解：拆成可执行子任务"),
        ("rootcause",   "ROOT_CAUSE_FOUND",  "根因：login.py L42 未对 user 空值检查，影响所有登录"),
        ("fixer",       "FIX_APPLIED",       "修复：入口参数校验 + 空值防护 + 异常映射（三层）"),
        ("tester",      "TEST_PASSED",       "测试验证：单测/边界/回归 10/10 通过"),
        ("releaser",    "RELEASE_OK",        "发布确认：灰度 10% → 金丝雀健康检查通过 → 全量"),
        ("retrospector","RETROSPECT_DONE",   "复盘沉淀：经验写入 RAG 知识库，闭环闭合"),
    ]

    for i, (worker, milestone, note) in enumerate(stages):
        await event_bus.worker_started(worker, task_id)
        print(f"  ▶ {worker:14s} 开始…")
        await asyncio.sleep(STAGE_INTERVAL)
        elapsed = 1.0 + i * 0.5  # 模拟累计耗时
        await event_bus.worker_completed(worker, task_id, milestone, elapsed=elapsed)
        await event_bus.milestone_reached(worker, task_id, milestone)
        print(f"  ✓ {worker:14s} → {milestone}  ({note})")
        await asyncio.sleep(STAGE_INTERVAL * 0.6)

    await event_bus.task_completed(task_id, data={"duration_secs": 181, "tests": "10/10"})
    print("\n✅ 完整 PDCA 闭环演示完成（真实平台实测 181s 走完）")
    print("   web 仪表盘保持运行中，打开浏览器查看最终看板。")

    # 保持 web server 运行，等待 Ctrl+C
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await web.stop()


if __name__ == "__main__":
    try:
        asyncio.run(run_demo())
    except KeyboardInterrupt:
        print("\n已停止。")
