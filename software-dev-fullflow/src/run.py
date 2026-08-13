"""研发团队调度 Loop 交互入口。

跑一条完整的「缺陷/需求 → 根因 → 修复 → 测试 → 发布 → 复盘」PDCA 闭环，
由 Manager 调度 6 个研发 Worker 接力完成。

用法：
    cd software-dev-fullflow\src
    ..\demo\.venv\Scripts\python.exe run.py
    # 或：..\demo\.venv\Scripts\python.exe run.py "你的缺陷/需求描述"

环境变量（读 demo/.env，或直接用 demo/.venv 跑）：
    DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# 支持在 src/ 下直接运行（把父目录加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loop.manager import TeamManagerLoop  # noqa: E402

# 默认工作目录：src/data/（运行产物，gitignore）
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_env() -> None:
    """优先读 demo/.env，若没有则读 src/.env。"""
    for p in (
        Path(__file__).resolve().parent.parent / "demo" / ".env",
        Path(__file__).resolve().parent / ".env",
    ):
        if p.exists():
            load_dotenv(p, override=True)
            break


async def main() -> None:
    _load_env()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("缺少 DEEPSEEK_API_KEY，请在 demo/.env 配置后重试。")
        sys.exit(1)

    # 快速验证参数：--stages N 只跑前 N 个阶段（默认完整 8 阶段闭环）；--mock 用确定性结果秒级跑完
    max_stages = 8
    mock = "--mock" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--mock"]
    if "--stages" in args:
        i = args.index("--stages")
        try:
            max_stages = int(args[i + 1])
            del args[i : i + 2]
        except (IndexError, ValueError):
            print("参数 --stages N 需跟整数，忽略。")
            max_stages = 8

    # 命令行直接带任务，否则交互输入
    if args:
        spec = " ".join(args)
    else:
        print("=== 研发团队调度 Loop Demo ===")
        print("描述一个缺陷/需求（例如：'登录接口在并发下偶发 500，需要定位并修复'），回车开始。")
        print("输入 q 退出。")
        try:
            spec = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not spec or spec.lower() in {"q", "quit", "exit"}:
            return

    task_id = uuid.uuid4().hex[:8]
    workdir = DEFAULT_DATA_DIR
    t0 = datetime.now(timezone.utc)
    manager = TeamManagerLoop(task_id=task_id, spec=spec, workdir=workdir, mock=mock)
    if mock:
        print("（mock 模式：不调 API，确定性结果快速演示完整闭环）")
    print(f"工作目录: {workdir / 'shared' / 'tasks' / task_id}")

    final = await manager.run(max_stages=max_stages)

    dt = datetime.now(timezone.utc) - t0
    print(f"\n总耗时: {dt.total_seconds():.1f}s")
    print(f"状态文件: {workdir / 'shared' / 'tasks' / task_id / 'state.json'}")
    print(f"闭环完成: {'是' if final.milestones.get('RETROSPECT_DONE') else '否（被截断/打回上限）'}")


if __name__ == "__main__":
    asyncio.run(main())
