"""研发团队调度 Loop 交互入口 —— AgentTeams 原生版。

跑一条完整的「缺陷/需求 → 根因 → 修复 → 测试 → 发布 → 复盘」PDCA 闭环，
由 **AgentTeams 官方框架**调度 6 个研发 Worker 接力完成（协同基点：阿里 AgentTeams）。

交互方式（按丰富度递增）：
  1. 命令行一键运行：  run.py "修复登录页面空指针异常"
  2. 交互式输入：        run.py --interactive
  3. Rich 终端仪表盘：    run.py --dashboard "你的任务描述"
  4. Web 浏览器仪表盘：   run.py --web "你的任务描述"
  5. 仪表盘 + 交互命令：  run.py --dashboard --interactive

用法：
    cd software-dev-fullflow\src
    ..\demo\.venv\Scripts\python.exe run.py
    ..\demo\.venv\Scripts\python.exe run.py "你的缺陷/需求描述"
    ..\demo\.venv\Scripts\python.exe run.py --mock --dashboard "演示任务"
    ..\demo\.venv\Scripts\python.exe run.py --interactive --mode orchestrated

环境变量：
    - AgentTeams 连通：AGT_MODE / AGT_CONTROLLER（默认 docker / agentteams-controller）
    - mock 模式不需要任何 API key

运行模式（--mode）：
    delegated     委托给 AgentTeams 的 Manager（LLM 驱动，推荐，Matrix 留痕）
    orchestrated  Python 控制流水线 + 确定性验证闸门（tester/releaser 阶段真跑测试）
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# 支持在 src/ 下直接运行（把父目录加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loop.agentteams_loop import AgentTeamsLoop  # noqa: E402
from loop.dashboard import create_dashboard  # noqa: E402
from loop.web_dashboard import WebDashboard  # noqa: E402

# 默认工作目录：src/data/（运行产物，gitignore）
DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"


# ========================================================================== #
# 交互式命令系统
# ========================================================================== #

class InteractiveShell:
    """交互式命令 Shell —— 在任务运行中接受用户指令。

    支持的命令：
      status / s    查看当前进度
      workers / w   查看 Worker 状态
      events / e    查看最近事件
      pause / p     暂停任务（发送中断信号）
      resume / r    恢复任务
      help / h / ?  显示帮助
      quit / q      退出
    """

    def __init__(self, loop: AgentTeamsLoop):
        self.loop = loop
        self._prompt_task: asyncio.Task | None = None

    async def run(self) -> None:
        """运行交互式命令循环（在后台并行）。"""
        print("\n  交互模式已启动。输入命令或 ? 查看帮助。")
        print("  ─────────────────────────────────────────")

        loop_reader = asyncio.get_event_loop()
        while True:
            try:
                cmd = await loop_reader.run_in_executor(
                    None, lambda: input("\n  🎯 > ").strip()
                )
            except (EOFError, KeyboardInterrupt):
                break

            if not cmd:
                continue

            parts = cmd.lower().split()
            action = parts[0]

            if action in ("q", "quit", "exit"):
                print("  退出交互模式（任务仍在后台运行）...")
                break
            elif action in ("?", "h", "help"):
                self._print_help()
            elif action in ("s", "status"):
                self._print_status()
            elif action in ("w", "workers"):
                self._print_workers()
            elif action in ("e", "events"):
                self._print_events()
            elif action in ("p", "pause"):
                print("  ⚠ 暂停功能需要 AgentTeams 平台支持（agt update worker --state Paused）")
            elif action in ("r", "resume"):
                print("  ⚠ 恢复功能需要 AgentTeams 平台支持（agt update worker --state Running）")
            else:
                print(f"  未知命令: {action}。输入 ? 查看帮助。")

    def _print_help(self):
        print("""
  ┌──────────────────────────────────────────────┐
  │  可用命令                                      │
  ├──────────────────────────────────────────────┤
  │  s, status    查看当前 PDCA 进度               │
  │  w, workers   查看 Worker 状态                 │
  │  e, events    查看最近事件                     │
  │  p, pause     暂停任务                         │
  │  r, resume    恢复任务                         │
  │  ?, h, help   显示此帮助                       │
  │  q, quit      退出交互模式                     │
  └──────────────────────────────────────────────┘
        """)

    def _print_status(self):
        state = self.loop.state
        print(f"""
  ┌──────────────────────────────────────────────┐
  │  任务状态                                      │
  ├──────────────────────────────────────────────┤
  │  任务 ID:  {state.task_id}                     │
  │  当前阶段: {state.state.value}                  │
  │  已达成里程碑:                                 │""")
        for ms, info in state.milestones.items():
            verdict = info.get("verdict", "?")
            by = info.get("by", "?")
            icon = "✅" if verdict == "PASS" else "❌"
            print(f"│    {icon} {ms} ← @{by}")
        print("""  └──────────────────────────────────────────────┘""")

    def _print_workers(self):
        print("""
  ┌──────────────────────────────────────────────┐
  │  Worker 状态                                   │
  ├──────────────────────────────────────────────┤""")
        for name in ["aggregator", "rootcause", "fixer", "tester", "releaser", "retrospector"]:
            ms = self.loop.state.milestones
            # 从 milestones 推断 Worker 状态
            worker_done = any(
                name in str(info.get("by", ""))
                for info in ms.values()
            )
            icon = "✅" if worker_done else "⏳"
            print(f"│  {icon}  {name:<15} {'完成' if worker_done else '等待中'}")
        print("""  └──────────────────────────────────────────────┘""")

    def _print_events(self):
        events = self.loop.event_bus.history(task_id=self.loop.task_id, limit=10)
        print("\n  ┌──────────────────────────────────────────────┐")
        print("  │  最近事件 (最新 10 条)                          │")
        print("  ├──────────────────────────────────────────────┤")
        if not events:
            print("  │  (暂无事件)                                    │")
        else:
            for evt in events:
                ts = datetime.fromtimestamp(evt["timestamp"], tz=timezone.utc).strftime("%H:%M:%S")
                etype = evt["event_type"]
                source = evt["source"]
                data = evt.get("data", {})
                ms = data.get("milestone", "")
                detail = f" → {ms}" if ms else ""
                print(f"  │  {ts}  [{source}] {etype}{detail}")
        print("  └──────────────────────────────────────────────┘")


# ========================================================================== #
# 主入口
# ========================================================================== #

async def main() -> None:
    # ── 参数解析 ──
    args = [a for a in sys.argv[1:]]

    mock = "--mock" in args
    args = [a for a in args if a != "--mock"]

    use_dashboard = "--dashboard" in args
    args = [a for a in args if a != "--dashboard"]

    use_web = "--web" in args
    args = [a for a in args if a != "--web"]

    interactive = "--interactive" in args
    args = [a for a in args if a != "--interactive"]

    mode = "delegated"
    if "--mode" in args:
        i = args.index("--mode")
        try:
            mode = args[i + 1]
            del args[i : i + 2]
        except (IndexError, ValueError):
            print("参数 --mode 需跟 delegated/orchestrated，忽略。")
    if mode not in ("delegated", "orchestrated"):
        print(f"未知模式 {mode}，使用默认 delegated。")
        mode = "delegated"

    # ── 任务输入 ──
    if args:
        spec = " ".join(args)
    else:
        print("╔══════════════════════════════════════════════════╗")
        print("║  研发团队调度 Loop Demo（AgentTeams 原生）         ║")
        print("╠══════════════════════════════════════════════════╣")
        print(f"║  运行模式: {mode:<38} ║")
        if mock:
            print("║  mock 模式: 秒级演示完整闭环                       ║")
        if use_dashboard:
            print("║  仪表盘: 已启用                                   ║")
        if interactive:
            print("║  交互命令: 已启用                                 ║")
        print("╠══════════════════════════════════════════════════╣")
        print("║  描述一个缺陷/需求，回车开始：                      ║")
        print("║  例如: '登录接口在并发下偶发 500，需要定位并修复'    ║")
        print("║  输入 q 退出                                     ║")
        print("╚══════════════════════════════════════════════════╝")
        try:
            spec = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not spec or spec.lower() in {"q", "quit", "exit"}:
            return

    # ── 创建 Loop ──
    task_id = uuid.uuid4().hex[:8]
    workdir = DEFAULT_DATA_DIR
    t0 = datetime.now(timezone.utc)

    loop = AgentTeamsLoop(
        task_id=task_id, spec=spec, workdir=workdir, mode=mode, mock=mock,
    )

    if mock:
        print("（mock 模式：不连 AgentTeams，确定性结果快速演示完整闭环）")
    print(f"工作目录: {workdir / 'shared' / 'tasks' / task_id}")

    # ── 仪表盘 ──
    dash = None
    web = None
    if use_dashboard:
        dash = create_dashboard(loop.event_bus, loop.state, loop.ctx)
        await dash.start()
    if use_web:
        web = WebDashboard(loop.event_bus, loop.state, loop.ctx)
        await web.start()

    # ── 交互式 Shell ──
    shell = InteractiveShell(loop) if interactive else None
    shell_task = asyncio.create_task(shell.run()) if shell else None

    # ── 运行 Loop ──
    try:
        final = await loop.run()
    finally:
        # 停止仪表盘
        if dash:
            await dash.stop()
        if web:
            await web.stop()
        # 取消交互 shell
        if shell_task:
            shell_task.cancel()
            try:
                await shell_task
            except asyncio.CancelledError:
                pass

    # ── 结果 ──
    dt = datetime.now(timezone.utc) - t0
    print(f"\n总耗时: {dt.total_seconds():.1f}s")
    print(f"状态文件: {workdir / 'shared' / 'tasks' / task_id / 'state.json'}")
    print(f"闭环完成: {'是' if final.milestones.get('RETROSPECT_DONE') else '否（被截断/打回上限）'}")


if __name__ == "__main__":
    asyncio.run(main())