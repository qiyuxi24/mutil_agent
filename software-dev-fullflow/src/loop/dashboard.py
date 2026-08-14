"""Rich 终端仪表盘 —— 实时 PDCA 进度 + Worker 状态 + 事件流。

基于 EventBus 事件驱动，复用 TaskState、AgentInterface、State 等已有组件。
提供类似 Claude Code Agent View + AgentsRoom 的终端可视化体验。

特性：
  - PDCA 8 阶段流水线进度条（颜色编码：pending/running/done/failed）
  - 6 个 Worker 实时状态面板（角色 + 里程碑 + 耗时）
  - 事件流（最近 N 条事件，实时滚动）
  - 上下文预算仪表盘
  - 桌面通知（Worker 完成/失败时）

用法：
    from loop.dashboard import Dashboard
    from loop.agentteams_loop import AgentTeamsLoop

    loop = AgentTeamsLoop(...)
    dash = Dashboard(loop.event_bus, loop.state, loop.ctx)
    # dashboard 自动订阅 EventBus 事件，实时更新
    await dash.start()
    await loop.run()
    await dash.stop()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loop.agent_bus import EventBus, EventType, Event
from loop.state import State, Milestone, TaskState, STATE_EXECUTOR, STATE_EXPECTED_MILESTONE
from loop.context import ContextManager

# Rich 是可选依赖，优雅降级
try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn
    from rich.layout import Layout
    from rich.text import Text
    from rich import box
    from rich.columns import Columns
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


# ========================================================================== #
# 1. 颜色与图标常量
# ========================================================================== #

# Worker 角色颜色（与 AgentsRoom 风格对齐）
ROLE_COLORS: dict[str, str] = {
    "aggregator":   "bright_cyan",
    "rootcause":    "bright_magenta",
    "fixer":        "bright_yellow",
    "tester":       "bright_green",
    "releaser":     "bright_blue",
    "retrospector": "bright_white",
    "manager":      "red",
}

# Worker 角色图标
ROLE_ICONS: dict[str, str] = {
    "aggregator":   "📋",
    "rootcause":    "🔍",
    "fixer":        "🔧",
    "tester":       "🧪",
    "releaser":     "🚀",
    "retrospector": "📝",
    "manager":      "👔",
}

# 状态图标
STATUS_ICONS: dict[str, str] = {
    "pending":   "⏳",
    "running":   "🔄",
    "done":      "✅",
    "failed":    "❌",
    "skipped":   "⏭️",
    "timeout":   "⏰",
}

# 阶段名称中文映射
STAGE_NAMES: dict[State, str] = {
    State.SPEC_INPUT:      "需求聚合",
    State.SPEC_DECOMPOSE:  "任务拆解",
    State.ROOT_CAUSE:      "根因定位",
    State.FIX_APPLY:       "代码修复",
    State.TEST_VERIFY:     "测试验证",
    State.RELEASE:         "发布准备",
    State.RELEASE_APPROVE: "发布审批",
    State.RETROSPECT:      "复盘沉淀",
}

# PDCA 阶段顺序
PDCA_STAGES = [
    State.SPEC_INPUT, State.SPEC_DECOMPOSE, State.ROOT_CAUSE,
    State.FIX_APPLY, State.TEST_VERIFY, State.RELEASE,
    State.RELEASE_APPROVE, State.RETROSPECT,
]


# ========================================================================== #
# 2. 纯文本仪表盘（无 Rich 时的降级方案）
# ========================================================================== #

class PlainDashboard:
    """纯文本仪表盘 —— 当 Rich 不可用时的降级方案。

    输出简洁的 ANSI 转义码彩色文本，不依赖任何第三方库。
    """

    ANSI_COLORS = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
        "blue": "\033[94m", "magenta": "\033[95m", "cyan": "\033[96m",
        "white": "\033[97m", "reset": "\033[0m", "bold": "\033[1m",
        "dim": "\033[2m",
    }

    def __init__(self, event_bus: EventBus, state: TaskState, ctx: ContextManager):
        self.event_bus = event_bus
        self.state = state
        self.ctx = ctx
        self._worker_status: dict[str, dict] = {}
        self._events: list[str] = []
        self._started = False

        # 初始化 Worker 状态
        for w in ["aggregator", "rootcause", "fixer", "tester", "releaser", "retrospector"]:
            self._worker_status[w] = {"status": "pending", "milestone": "", "elapsed": 0}

    async def start(self):
        if self._started:
            return
        self._started = True
        self.event_bus.subscribe("*", self._on_event)
        self._print_header()

    async def stop(self):
        self._print_footer()

    def _on_event(self, event: Event):
        self._update_worker_state(event)
        self._append_event(event)
        self._print_status_line(event)

    def _update_worker_state(self, event: Event):
        worker = event.source
        if worker not in self._worker_status:
            return
        ws = self._worker_status[worker]
        etype = event.event_type

        if etype == EventType.WORKER_STARTED:
            ws["status"] = "running"
        elif etype == EventType.WORKER_COMPLETED:
            ws["status"] = "done"
            ws["milestone"] = event.data.get("milestone", "")
            ws["elapsed"] = event.data.get("elapsed", 0)
        elif etype == EventType.WORKER_FAILED:
            ws["status"] = "failed"
        elif etype == EventType.ERROR_OCCURRED:
            ws["status"] = "failed"

    def _append_event(self, event: Event):
        icon = {"WORKER_STARTED": "▶", "WORKER_COMPLETED": "✓", "WORKER_FAILED": "✗",
                "MILESTONE_REACHED": "🏁", "ERROR_OCCURRED": "⚠", "TASK_COMPLETED": "🎉"}
        ico = icon.get(event.event_type.value, "•")
        color = ROLE_COLORS.get(event.source, "white")
        ansi = self.ANSI_COLORS.get(color, "")
        ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).strftime("%H:%M:%S")
        self._events.append(f"{ansi}{ico} [{ts}] {event.source}: {event.event_type.value}{self.ANSI_COLORS['reset']}")
        if len(self._events) > 20:
            self._events = self._events[-20:]

    def _print_header(self):
        c = self.ANSI_COLORS
        print(f"\n{c['bold']}{c['cyan']}╔══════════════════════════════════════════════╗{c['reset']}")
        print(f"{c['bold']}{c['cyan']}║{c['reset']}  {c['bold']}PDCA 闭环调度仪表盘{c['reset']}                          {c['bold']}{c['cyan']}║{c['reset']}")
        print(f"{c['bold']}{c['cyan']}╠══════════════════════════════════════════════╣{c['reset']}")
        print(f"{c['bold']}{c['cyan']}║{c['reset']}  任务: {self.state.task_id[:30]:<30} {c['bold']}{c['cyan']}║{c['reset']}")
        print(f"{c['bold']}{c['cyan']}║{c['reset']}  规格: {self.state.spec[:30]:<30} {c['bold']}{c['cyan']}║{c['reset']}")
        print(f"{c['bold']}{c['cyan']}╚══════════════════════════════════════════════╝{c['reset']}")
        print()

    def _print_status_line(self, event: Event):
        """打印单行状态更新。"""
        c = self.ANSI_COLORS
        worker = event.source
        etype = event.event_type
        ico = ROLE_ICONS.get(worker, "●")
        color = ROLE_COLORS.get(worker, "white")
        ansi = c.get(color, "")

        if etype == EventType.WORKER_STARTED:
            print(f"  {ico} {ansi}{worker}{c['reset']} → {c['yellow']}运行中...{c['reset']}")
        elif etype == EventType.WORKER_COMPLETED:
            ms = event.data.get("milestone", "")
            elapsed = event.data.get("elapsed", 0)
            print(f"  {ico} {ansi}{worker}{c['reset']} → {c['green']}完成{c['reset']} {ms} ({elapsed:.1f}s)")
        elif etype == EventType.WORKER_FAILED:
            print(f"  {ico} {ansi}{worker}{c['reset']} → {c['red']}失败{c['reset']}")
        elif etype == EventType.MILESTONE_REACHED:
            ms = event.data.get("milestone", "")
            print(f"  {c['green']}🏁 里程碑达成: {ms}{c['reset']}")
        elif etype == EventType.ERROR_OCCURRED:
            err = event.data.get("error", "")
            print(f"  {c['red']}⚠ 错误: {worker} - {err[:80]}{c['reset']}")

    def _print_footer(self):
        c = self.ANSI_COLORS
        print(f"\n{c['bold']}{c['cyan']}════════════════════════════════════════════════{c['reset']}")
        print(f"  最终状态: {self.state.state.value}")
        print(f"  里程碑: {list(self.state.milestones.keys())}")
        print()

        # Worker 总结
        print(f"{c['bold']}Worker 执行总结:{c['reset']}")
        for name, ws in self._worker_status.items():
            icon = ROLE_ICONS.get(name, "●")
            status_icon = STATUS_ICONS.get(ws["status"], "?")
            color = ROLE_COLORS.get(name, "white")
            ansi = c.get(color, "")
            ms = f" → {ws['milestone']}" if ws["milestone"] else ""
            elapsed = f" ({ws['elapsed']:.1f}s)" if ws["elapsed"] else ""
            print(f"  {icon} {ansi}{name:<15}{c['reset']} {status_icon} {ws['status']}{ms}{elapsed}")
        print()


# ========================================================================== #
# 3. Rich 终端仪表盘（完整版）
# ========================================================================== #

if HAS_RICH:

    @dataclass
    class WorkerCard:
        """Worker 状态卡片数据。"""
        name: str
        status: str = "pending"      # pending / running / done / failed
        milestone: str = ""
        elapsed: float = 0.0
        retries: int = 0

    class RichDashboard:
        """Rich 终端实时仪表盘。

        面板布局：
        ┌──────────────────────────────────────┐
        │          HEADER (任务信息)            │
        ├──────────────────┬───────────────────┤
        │  PDCA 流水线     │   Worker 状态面板  │
        │  (8 阶段进度条)  │   (6 张角色卡片)  │
        ├──────────────────┴───────────────────┤
        │         事件流 (最新 15 条)           │
        ├──────────────────────────────────────┤
        │         上下文预算 + 性能指标          │
        └──────────────────────────────────────┘
        """

        MAX_EVENTS = 15

        def __init__(self, event_bus: EventBus, state: TaskState, ctx: ContextManager):
            self.event_bus = event_bus
            self.state = state
            self.ctx = ctx
            self.console = Console()

            # Worker 状态
            self._workers: dict[str, WorkerCard] = {}
            for w in ["aggregator", "rootcause", "fixer", "tester", "releaser", "retrospector"]:
                self._workers[w] = WorkerCard(name=w)

            # 事件缓冲
            self._events: list[tuple[str, str, str]] = []  # (timestamp, source, message)

            # 阶段完成顺序
            self._stage_order: list[State] = []

            self._started = False
            self._live: Live | None = None
            self._task_start: float = 0

        # ------------------------------------------------------------------ #
        # 生命周期
        # ------------------------------------------------------------------ #

        async def start(self):
            """启动仪表盘。"""
            if self._started:
                return
            self._started = True
            self._task_start = time.time()

            self.event_bus.subscribe("*", self._on_event)

            self._live = Live(
                self._render(),
                console=self.console,
                refresh_per_second=4,
                screen=True,
            )
            self._live.start()

        async def stop(self):
            """停止仪表盘，打印最终报告。"""
            if self._live:
                self._live.stop()
                self._live = None
            self._print_final_report()

        # ------------------------------------------------------------------ #
        # 事件处理
        # ------------------------------------------------------------------ #

        def _on_event(self, event: Event):
            """处理 EventBus 事件（同步回调，在 emit 线程中执行）。"""
            self._update_worker(event)
            self._append_event(event)
            self._update_stage(event)

        def _update_worker(self, event: Event):
            worker = event.source
            if worker not in self._workers:
                return
            w = self._workers[worker]
            etype = event.event_type

            if etype == EventType.WORKER_STARTED:
                w.status = "running"
                w.elapsed = 0
            elif etype == EventType.WORKER_COMPLETED:
                w.status = "done"
                w.milestone = event.data.get("milestone", "")
                w.elapsed = event.data.get("elapsed", 0)
            elif etype == EventType.WORKER_FAILED:
                w.status = "failed"
            elif etype == EventType.MILESTONE_FAILED:
                w.status = "failed"
                w.retries = event.data.get("retries", 0)
            elif etype == EventType.ERROR_OCCURRED:
                if w.status == "running":
                    w.status = "failed"

        def _append_event(self, event: Event):
            ts = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).strftime("%H:%M:%S")
            icon = {
                "WORKER_STARTED": "▶", "WORKER_COMPLETED": "✓", "WORKER_FAILED": "✗",
                "MILESTONE_REACHED": "🏁", "MILESTONE_FAILED": "💥",
                "ERROR_OCCURRED": "⚠", "TASK_STARTED": "🚀", "TASK_COMPLETED": "🎉",
                "HUMAN_INTERVENTION_REQUIRED": "🆘",
            }.get(event.event_type.value, "•")

            msg = event.event_type.value
            if event.data.get("milestone"):
                msg = f"{msg} → {event.data['milestone']}"
            if event.data.get("error"):
                msg = f"{msg}: {event.data['error'][:60]}"

            self._events.append((ts, event.source, f"{icon} {msg}"))
            if len(self._events) > self.MAX_EVENTS:
                self._events = self._events[-self.MAX_EVENTS:]

        def _update_stage(self, event: Event):
            """追踪阶段推进顺序。"""
            if event.event_type == EventType.MILESTONE_REACHED:
                # 根据里程碑映射到阶段
                milestone_to_state = {
                    "TASK_SPEC_READY": State.SPEC_INPUT,
                    "ROOT_CAUSE_FOUND": State.ROOT_CAUSE,
                    "FIX_APPLIED": State.FIX_APPLY,
                    "TEST_PASSED": State.TEST_VERIFY,
                    "RELEASE_OK": State.RELEASE,
                    "RETROSPECT_DONE": State.RETROSPECT,
                }
                ms = event.data.get("milestone", "")
                if ms in milestone_to_state:
                    stage = milestone_to_state[ms]
                    if stage not in self._stage_order:
                        self._stage_order.append(stage)

        # ------------------------------------------------------------------ #
        # 渲染
        # ------------------------------------------------------------------ #

        def _render(self) -> Layout:
            """渲染完整仪表盘布局。"""
            layout = Layout()
            layout.split(
                Layout(self._render_header(), size=3),
                Layout(name="main"),
                Layout(self._render_footer(), size=3),
            )
            layout["main"].split_row(
                Layout(self._render_pipeline(), ratio=2),
                Layout(self._render_workers(), ratio=3),
            )
            return layout

        def _render_header(self) -> Panel:
            """渲染顶部标题栏。"""
            elapsed = time.time() - self._task_start if self._task_start else 0
            title = Text.assemble(
                ("PDCA 闭环调度仪表盘", "bold cyan"),
                (f"    任务 {self.state.task_id}", "dim"),
                (f"    已运行 {elapsed:.0f}s", "dim"),
            )
            return Panel(title, box=box.HEAVY)

        def _render_pipeline(self) -> Panel:
            """渲染 PDCA 8 阶段流水线。"""
            table = Table(show_header=False, box=box.SIMPLE, padding=(0, 1))
            table.add_column("阶段", style="dim", width=10)
            table.add_column("状态", width=6)
            table.add_column("执行者", style="dim", width=12)

            current_state = self.state.state
            for stage in PDCA_STAGES:
                executor = STATE_EXECUTOR.get(stage, "—")
                expected_ms = STATE_EXPECTED_MILESTONE.get(stage)
                ms_name = expected_ms.value if expected_ms else "—"

                # 判断阶段状态
                if stage in self._stage_order:
                    status_icon = "✅"
                    status_style = "green"
                    status_text = "done"
                elif stage == current_state:
                    status_icon = "🔄"
                    status_style = "yellow"
                    status_text = "running"
                elif self._is_stage_passed(stage):
                    status_icon = "✅"
                    status_style = "green"
                    status_text = "done"
                else:
                    status_icon = "⏳"
                    status_style = "dim"
                    status_text = "pending"

                name = STAGE_NAMES.get(stage, stage.value)
                icon = ROLE_ICONS.get(executor, "●")
                table.add_row(
                    f"[{status_style}]{status_icon} {name}[/{status_style}]",
                    f"[{status_style}]{status_text}[/{status_style}]",
                    f"{icon} {executor}",
                )

            return Panel(table, title="[bold]PDCA 流水线[/bold]", border_style="blue")

        def _is_stage_passed(self, stage: State) -> bool:
            """检查阶段是否已通过（从 state.milestones 判断）。"""
            ms = STATE_EXPECTED_MILESTONE.get(stage)
            if ms and ms.value in self.state.milestones:
                return self.state.milestones[ms.value].get("verdict") == "PASS"
            return False

        def _render_workers(self) -> Panel:
            """渲染 Worker 状态面板（6 张卡片）。"""
            cards: list[Panel] = []
            for name in ["aggregator", "rootcause", "fixer", "tester", "releaser", "retrospector"]:
                w = self._workers[name]
                cards.append(self._render_worker_card(w))

            grid = Table.grid()
            grid.add_column()
            grid.add_column()
            for i in range(0, len(cards), 2):
                grid.add_row(cards[i], cards[i + 1] if i + 1 < len(cards) else "")

            # 事件流在 Workers 下方
            events_table = self._render_events()

            content = Table.grid()
            content.add_row(grid)
            content.add_row("")
            content.add_row(events_table)

            return Panel(content, title="[bold]Worker 状态 & 事件流[/bold]", border_style="magenta")

        def _render_worker_card(self, w: WorkerCard) -> Panel:
            """渲染单个 Worker 卡片。"""
            color = ROLE_COLORS.get(w.name, "white")
            icon = ROLE_ICONS.get(w.name, "●")

            status_style = {
                "pending": "dim",
                "running": "yellow",
                "done": "green",
                "failed": "red",
            }.get(w.status, "dim")

            status_icon = STATUS_ICONS.get(w.status, "?")

            lines: list[str] = []
            lines.append(f"[{color}]{icon} {w.name}[/{color}]")
            lines.append(f"[{status_style}]{status_icon} {w.status}[/{status_style}]")
            if w.milestone:
                lines.append(f"[dim]→ {w.milestone}[/dim]")
            if w.elapsed > 0:
                lines.append(f"[dim]⏱ {w.elapsed:.1f}s[/dim]")
            if w.retries > 0:
                lines.append(f"[red]↺ {w.retries} 次重试[/red]")

            body = "\n".join(lines)
            return Panel(body, border_style=color, padding=(0, 1), width=22)

        def _render_events(self) -> Panel:
            """渲染事件流。"""
            if not self._events:
                return Panel("[dim]等待事件...[/dim]", title="事件流", border_style="dim")

            lines: list[str] = []
            for ts, source, msg in self._events[-10:]:
                color = ROLE_COLORS.get(source, "white")
                lines.append(f"[dim]{ts}[/dim] [{color}]{source:<12}[/{color}] {msg}")

            return Panel("\n".join(lines), title="事件流", border_style="dim", height=12)

        def _render_footer(self) -> Panel:
            """渲染底部状态栏。"""
            # 上下文预算
            try:
                snapshot = self.ctx.snapshot()
                budget = snapshot.get("budget", {})
                used = budget.get("used", 0)
                total = budget.get("total_budget", 32000)
                pct = (used / total * 100) if total else 0
                budget_color = "green" if pct < 50 else "yellow" if pct < 70 else "red"
                budget_text = f"上下文: [{budget_color}]{used}/{total} tokens ({pct:.0f}%)[/{budget_color}]"
            except Exception:
                budget_text = "上下文: —"

            # Worker 统计
            done_count = sum(1 for w in self._workers.values() if w.status == "done")
            running_count = sum(1 for w in self._workers.values() if w.status == "running")
            failed_count = sum(1 for w in self._workers.values() if w.status == "failed")

            stats = (
                f"Worker: [green]{done_count} done[/green]  "
                f"[yellow]{running_count} running[/yellow]  "
                f"[red]{failed_count} failed[/red]  |  "
                f"{budget_text}"
            )
            return Panel(stats, box=box.SIMPLE)

        # ------------------------------------------------------------------ #
        # 最终报告
        # ------------------------------------------------------------------ #

        def _print_final_report(self):
            """任务结束后打印最终报告。"""
            self.console.print()
            self.console.print(Panel("任务完成", style="bold green"))

            # Worker 总结
            table = Table(title="Worker 执行总结", box=box.ROUNDED)
            table.add_column("Worker", style="bold")
            table.add_column("状态")
            table.add_column("里程碑")
            table.add_column("耗时")
            table.add_column("重试")

            for name, w in self._workers.items():
                icon = ROLE_ICONS.get(name, "●")
                color = ROLE_COLORS.get(name, "white")
                status_style = {
                    "pending": "dim", "running": "yellow", "done": "green", "failed": "red"
                }.get(w.status, "dim")
                table.add_row(
                    f"[{color}]{icon} {name}[/{color}]",
                    f"[{status_style}]{w.status}[/{status_style}]",
                    w.milestone or "—",
                    f"{w.elapsed:.1f}s" if w.elapsed > 0 else "—",
                    str(w.retries) if w.retries > 0 else "—",
                )

            self.console.print(table)
            self.console.print()


# ========================================================================== #
# 4. 工厂函数
# ========================================================================== #

def create_dashboard(
    event_bus: EventBus,
    state: TaskState,
    ctx: ContextManager,
) -> PlainDashboard | RichDashboard:
    """创建仪表盘实例（自动选择 Rich 或纯文本模式）。

    Args:
        event_bus: EventBus 实例
        state: TaskState 实例
        ctx: ContextManager 实例

    Returns:
        RichDashboard 或 PlainDashboard
    """
    if HAS_RICH:
        return RichDashboard(event_bus, state, ctx)
    return PlainDashboard(event_bus, state, ctx)


# ========================================================================== #
# 5. 自检
# ========================================================================== #

async def _self_test():
    """快速自检：验证仪表盘的事件处理逻辑。"""
    from loop.context import ContextManager
    from loop.state import TaskState

    print("=== Dashboard 自检 ===")

    # 创建 mock 组件
    state = TaskState(task_id="test-001", spec="测试仪表盘")
    event_bus = EventBus()
    ctx = ContextManager(task_id="test-001", workdir=Path("."), total_budget=1000)

    # 创建仪表盘
    dash = create_dashboard(event_bus, state, ctx)
    await dash.start()
    print(f"✓ 仪表盘类型: {type(dash).__name__}")

    # 模拟事件
    await event_bus.worker_started("aggregator", "test-001")
    await event_bus.worker_completed("aggregator", "test-001", "TASK_SPEC_READY", elapsed=1.5)
    await event_bus.milestone_reached("aggregator", "test-001", "TASK_SPEC_READY")
    await event_bus.worker_started("rootcause", "test-001")
    await event_bus.worker_completed("rootcause", "test-001", "ROOT_CAUSE_FOUND", elapsed=3.0)
    await event_bus.milestone_reached("rootcause", "test-001", "ROOT_CAUSE_FOUND")

    # 验证 Worker 状态（兼容两种仪表盘）
    if HAS_RICH and isinstance(dash, RichDashboard):
        agg_status = dash._workers["aggregator"].status
        rc_status = dash._workers["rootcause"].status
        fixer_status = dash._workers["fixer"].status
    else:
        agg_status = dash._worker_status["aggregator"]["status"]
        rc_status = dash._worker_status["rootcause"]["status"]
        fixer_status = dash._worker_status["fixer"]["status"]
    assert agg_status == "done"
    assert rc_status == "done"
    assert fixer_status == "pending"
    print("✓ Worker 状态更新正确")

    # 验证事件缓冲
    assert len(dash._events) >= 4
    print(f"✓ 事件缓冲: {len(dash._events)} 条事件")

    print("=== 自检通过 ===")


if __name__ == "__main__":
    asyncio.run(_self_test())