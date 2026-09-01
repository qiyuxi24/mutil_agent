# -*- coding: utf-8 -*-
"""GAP-26 守护进程 —— 任务队列 + 断点续跑 + 失败重试 + 超时/卡死告警。

解决「run.py 是单次 CLI，进程死/断网无自动拉起，不符合长时间稳定运行」的短板。

设计对齐 ARIS watchdog（tools/watchdog.py）：
  - 目录结构：<base_dir>/watchdog.pid, tasks.json, alerts.log, status/<name>.json, status/summary.txt
  - 单 writer 契约：所有写盘用「临时文件 + os.replace」原子替换
  - 卡死检测（detect-only）：任务在跑但状态文件长时间无更新 → 写 alerts.log 告警，不干预

本守护进程在 ARIS「只检测」的基础上增加「拉起执行」能力（GAP-26 第一步）：
  1. 周期拉任务：扫描 tasks.json 队列
  2. 提交平台：对未完成/未启动任务拉起执行器（默认跑 run_pdca_task，可注入以便测试）
  3. 断点续跑：以同一 task_id 启动 → AgentTeamsLoop 内部 delegation.json 自动 resume forward，
     对齐 wait_for_task 超时恢复语义（超时不是失败，下一轮以同一 task_id 续跑）
  4. 失败重试：attempts < max_attempts 时重试，达到上限标记 FAILED 并告警
  5. 超时/卡死告警：任务运行中超 stale_after_seconds 无进度 → STALE 告警；整体超 task_timeout → TIMEOUT 告警

CLI 用法：
    python -m loop.watchdog --base-dir data/shared/watchdog --register '{"name":"t1","spec":"修复登录接口500","mock":true}'
    python -m loop.watchdog --base-dir data/shared/watchdog --status
    python -m loop.watchdog --base-dir data/shared/watchdog --interval 30   # 前台守护
    python -m loop.watchdog --base-dir data/shared/watchdog --unregister t1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

DEFAULT_BASE_DIR = "data/shared/watchdog"
DEFAULT_INTERVAL = 30          # 守护循环周期（秒）
DEFAULT_MAX_ATTEMPTS = 3       # 单任务最大尝试次数
DEFAULT_STALE_AFTER = 3600     # 状态文件无更新多久算卡死（秒）
DEFAULT_TASK_TIMEOUT = 6 * 3600  # 单任务整体超时（秒）

# 任务状态
PENDING = "pending"      # 已注册，等待拉起
RUNNING = "running"      # 执行器已拉起
COMPLETED = "completed"  # 闭环完成
FAILED = "failed"        # 超过最大尝试次数
TIMEOUT = "timeout"      # 单任务整体超时（告警后仍保留，下轮可续跑）
STALE = "stale"          # 卡死（仅告警标记，detect-only）

# 告警级别（写入 alerts.log 的行前缀）
_ALERT_STALE = "STALE"
_ALERT_TIMEOUT = "TIMEOUT"
_ALERT_FAILED = "FAILED"
_ALERT_RESTART = "RESTART"      # 进程重启 / 从崩溃中恢复
_ALERT_LAUNCH = "LAUNCH_FAIL"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# 目录结构（对齐 ARIS watchdog）
# --------------------------------------------------------------------------- #

def get_paths(base_dir: Path) -> dict[str, Path]:
    """返回守护进程目录结构下的各文件路径。"""
    base = Path(base_dir)
    return {
        "base": base,
        "pid": base / "watchdog.pid",
        "tasks": base / "tasks.json",
        "alerts": base / "alerts.log",
        "status_dir": base / "status",
    }


def _atomic_write(path: Path, data: str) -> None:
    """临时文件 + os.replace 原子写（单 writer 契约）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _append_alert(base_dir: Path, level: str, msg: str) -> None:
    """追加一行告警到 alerts.log。"""
    paths = get_paths(base_dir)
    paths["alerts"].parent.mkdir(parents=True, exist_ok=True)
    with paths["alerts"].open("a", encoding="utf-8") as f:
        f.write(f"{utcnow()} [{level}] {msg}\n")


# --------------------------------------------------------------------------- #
# 任务队列（tasks.json）
# --------------------------------------------------------------------------- #

@dataclass
class WatchTask:
    """一个待守护的 PDCA 任务（可持久化到 tasks.json）。"""

    name: str                                  # 唯一任务名
    spec: str                                  # 需求/任务描述
    workdir: str = ""                          # 工作目录（空 = 守护进程所在目录）
    mock: bool = False                         # 是否 mock 模式（无平台兜底）
    task_id: str = ""                          # 断点续跑用的平台任务 ID（空 = 首次生成）
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    stale_after: int = DEFAULT_STALE_AFTER     # 卡死阈值（秒）
    task_timeout: int = DEFAULT_TASK_TIMEOUT   # 单任务整体超时（秒）
    status: str = PENDING
    attempts: int = 0
    last_error: str = ""
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)
    started_at: str = ""                       # 首次拉起时间

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "spec": self.spec,
            "workdir": self.workdir,
            "mock": self.mock,
            "task_id": self.task_id,
            "max_attempts": self.max_attempts,
            "stale_after": self.stale_after,
            "task_timeout": self.task_timeout,
            "status": self.status,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WatchTask":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def load_tasks(base_dir: Path) -> list[WatchTask]:
    """读取任务队列；文件不存在/损坏时返回空队列（不阻塞守护）。"""
    p = get_paths(base_dir)["tasks"]
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return [WatchTask.from_dict(x) for x in raw]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []


def save_tasks(base_dir: Path, tasks: list[WatchTask]) -> None:
    data = json.dumps([t.to_dict() for t in tasks], ensure_ascii=False, indent=2)
    _atomic_write(get_paths(base_dir)["tasks"], data)


def register_task(base_dir: Path, task: WatchTask) -> WatchTask:
    """注册任务：同名覆盖（保留原 task_id 以便断点续跑）。"""
    tasks = load_tasks(base_dir)
    replaced = False
    for i, t in enumerate(tasks):
        if t.name == task.name:
            if not task.task_id:
                task.task_id = t.task_id  # 保留已生成的平台任务 ID
            if t.status in (RUNNING, PENDING):
                task.started_at = t.started_at
            tasks[i] = task
            replaced = True
            break
    if not replaced:
        tasks.append(task)
    save_tasks(base_dir, tasks)
    return task


def unregister_task(base_dir: Path, name: str) -> bool:
    tasks = load_tasks(base_dir)
    kept = [t for t in tasks if t.name != name]
    if len(kept) == len(tasks):
        return False
    save_tasks(base_dir, kept)
    return True


# --------------------------------------------------------------------------- #
# 执行器
# --------------------------------------------------------------------------- #

AsyncRunner = Callable[[WatchTask], Awaitable[dict[str, Any]]]


async def default_runner(task: WatchTask) -> dict[str, Any]:
    """默认执行器：跑 run_pdca_task。

    - 首次：task_id 为空 → 生成并写回队列（watchdog 负责）
    - 断点续跑：以同一 task_id 启动，AgentTeamsLoop 读 delegation.json resume forward
    """
    from loop.agentteams_loop import run_pdca_task

    workdir = Path(task.workdir) if task.workdir else Path.cwd()
    state = await run_pdca_task(
        spec=task.spec,
        workdir=workdir,
        mock=task.mock,
        task_id=task.task_id,
    )
    from loop.state import Milestone

    done = "RETROSPECT_DONE" in state.milestones
    return {
        "status": COMPLETED if done else RUNNING,
        "task_id": task.task_id,
        "milestones": sorted(state.milestones.keys()),
        "state": state.state.value,
    }


# --------------------------------------------------------------------------- #
# 守护进程
# --------------------------------------------------------------------------- #

class Watchdog:
    """周期扫描任务队列 → 拉起执行器 → 断点续跑 → 失败重试 → 卡死/超时告警。"""

    def __init__(
        self,
        base_dir: Path | str,
        interval: int = DEFAULT_INTERVAL,
        runner: AsyncRunner | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.interval = interval
        self.runner = runner or default_runner
        self._active: dict[str, asyncio.Task] = {}      # name -> 运行中的执行器任务
        self._stop = asyncio.Event()

    # ---- 生命周期 ----

    def write_pid(self) -> None:
        paths = get_paths(self.base_dir)
        paths["base"].mkdir(parents=True, exist_ok=True)
        paths["pid"].write_text(str(os.getpid()), encoding="utf-8")

    def clear_pid(self) -> None:
        p = get_paths(self.base_dir)["pid"]
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        """前台守护主循环。Ctrl+C / SIGTERM 优雅退出。"""
        self.write_pid()
        try:
            while not self._stop.is_set():
                try:
                    await self.tick()
                except Exception as e:  # 单轮异常不致命，记录后继续
                    _append_alert(self.base_dir, "ERROR", f"tick 异常: {e}")
                # 等待 interval 或收到停止信号
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self._drain_active()
            self.clear_pid()

    async def _drain_active(self) -> None:
        """停止时等待运行中任务优雅收尾（最多 5s）。"""
        pending = [t for t in self._active.values() if not t.done()]
        if not pending:
            return
        done, _ = await asyncio.wait(pending, timeout=5)
        for t in pending:
            if not t.done():
                t.cancel()

    # ---- 单轮调度 ----

    async def tick(self) -> None:
        """单轮调度：扫描队列，拉起应启动的任务，记录完成/失败。"""
        tasks = load_tasks(self.base_dir)
        changed = False
        now = time.time()

        for task in tasks:
            act = self._active.get(task.name)
            if act is not None and not act.done():
                # 正在运行 → 卡死检测（detect-only）
                self._check_stall(task, now)
                continue

            # 上一轮的执行器已结束 → 处理结果
            if act is not None:
                self._active.pop(task.name, None)
                changed |= await self._handle_result(task, act)
                # result 处理后任务可能已 completed/failed，跳过拉起
                if task.status in (COMPLETED, FAILED):
                    continue
                task.status = PENDING  # 允许重试/续跑

            # 拉起新任务（pending / 需要续跑）
            if task.status == PENDING:
                changed |= await self._launch(task)

        if changed:
            save_tasks(self.base_dir, tasks)

        self.write_summary()

    async def _launch(self, task: WatchTask) -> bool:
        """拉起执行器。生成 task_id、递增 attempts、更新状态。"""
        if not task.task_id:
            task.task_id = f"pdca-{int(time.time())}"
        task.attempts += 1
        task.status = RUNNING
        task.updated_at = utcnow()
        if not task.started_at:
            task.started_at = task.updated_at

        loop = asyncio.get_running_loop()
        fut = asyncio.ensure_future(self._run_guarded(task))
        self._active[task.name] = fut
        return True

    async def _run_guarded(self, task: WatchTask) -> dict[str, Any]:
        """带超时保护的执行包装：异常/超时不外抛，转成结果 dict。"""
        try:
            return await asyncio.wait_for(self.runner(task), timeout=task.task_timeout)
        except asyncio.TimeoutError:
            return {"status": TIMEOUT, "error": f"任务超时（>{task.task_timeout}s）"}
        except Exception as e:  # noqa: BLE001 - 任何异常都收进结果，避免守护崩溃
            return {"status": FAILED, "error": f"{type(e).__name__}: {e}"}

    async def _handle_result(self, task: WatchTask, fut: asyncio.Task) -> bool:
        """执行器结束后回写状态：completed / 重试 / 超限失败。"""
        result = fut.result()  # _run_guarded 保证不抛
        task.updated_at = utcnow()
        status = result.get("status", FAILED)
        error = result.get("error", "")

        if status == COMPLETED:
            task.status = COMPLETED
            task.last_error = ""
            task.task_id = result.get("task_id") or task.task_id
            return True

        # 未完成（timeout / running 收尾 / 失败）→ 计数，决定重试还是放弃
        task.last_error = error or f"未闭环完成（最后状态: {result.get('state', '?')}）"
        if status == TIMEOUT:
            _append_alert(self.base_dir, _ALERT_TIMEOUT,
                          f"{task.name}: {task.last_error}（attempt {task.attempts}/{task.max_attempts}，"
                          f"下轮以同一 task_id={task.task_id} 续跑）")
            # 超时不是失败：保留 PENDING，下轮续跑（wait_for_task 超时恢复语义）
            task.status = PENDING
            return True

        if task.attempts >= task.max_attempts:
            task.status = FAILED
            _append_alert(self.base_dir, _ALERT_FAILED,
                          f"{task.name}: 已达最大尝试次数 {task.max_attempts}，放弃。最后错误: {task.last_error}")
            return True

        # 可重试
        task.status = PENDING
        return True

    # ---- 卡死检测（detect-only，对齐 ARIS check_loop） ----

    def _check_stall(self, task: WatchTask, now: float) -> None:
        """任务在跑但状态文件长时间无更新 → 写 STALE 告警（不干预）。

        进度信号 = 最近一次落盘文件（delegation.json / state.json / checkpoint）。
        """
        # mock 模式 / 无任务目录时跳过
        workdir = Path(task.workdir) if task.workdir else Path.cwd()
        task_dir = workdir / "shared" / "tasks" / task.task_id
        if not task_dir.exists():
            return

        latest_mtime = 0.0
        for name in ("delegation.json", "state.json"):
            p = task_dir / name
            if p.exists():
                latest_mtime = max(latest_mtime, p.stat().st_mtime)

        if latest_mtime <= 0:
            return
        idle = now - latest_mtime
        if idle > task.stale_after:
            _append_alert(self.base_dir, _ALERT_STALE,
                          f"{task.name}({task.task_id}): 已 {int(idle)}s 无进度（阈值 {task.stale_after}s）")

    # ---- 状态落盘 ----

    def write_status(self, task: WatchTask) -> None:
        paths = get_paths(self.base_dir)
        _atomic_write(
            paths["status_dir"] / f"{task.name}.json",
            json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
        )

    def write_summary(self) -> None:
        """summary.txt：一行一个任务（对齐 ARIS）。"""
        paths = get_paths(self.base_dir)
        tasks = load_tasks(self.base_dir)
        lines = []
        for t in sorted(tasks, key=lambda x: x.name):
            lines.append(f"{t.name:30s} {t.status:10s} attempts={t.attempts}/{t.max_attempts}"
                         + (f"  {t.last_error}" if t.last_error else ""))
            self.write_status(t)
        _atomic_write(paths["status_dir"] / "summary.txt", "\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="GAP-26 守护进程：任务队列 + 断点续跑 + 失败重试 + 卡死/超时告警")
    p.add_argument("--base-dir", default=DEFAULT_BASE_DIR, help="守护进程数据目录")
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="守护循环周期（秒）")
    p.add_argument("--register", metavar="JSON", help="注册任务，JSON 如 {\"name\":\"t1\",\"spec\":\"...\",\"mock\":true}")
    p.add_argument("--unregister", metavar="NAME", help="注销任务")
    p.add_argument("--status", action="store_true", help="打印任务队列状态")
    p.add_argument("--once", action="store_true", help="只跑一轮（用于手动触发/测试）")
    return p.parse_args(argv)


def _register_from_json(base_dir: Path, raw: str) -> WatchTask:
    d = json.loads(raw)
    if "name" not in d or "spec" not in d:
        raise ValueError("register JSON 必须包含 name 与 spec")
    return register_task(base_dir, WatchTask(
        name=d["name"],
        spec=d["spec"],
        workdir=d.get("workdir", ""),
        mock=bool(d.get("mock", False)),
        max_attempts=int(d.get("max_attempts", DEFAULT_MAX_ATTEMPTS)),
        stale_after=int(d.get("stale_after", DEFAULT_STALE_AFTER)),
        task_timeout=int(d.get("task_timeout", DEFAULT_TASK_TIMEOUT)),
    ))


async def _cmd_status(base_dir: Path) -> int:
    tasks = load_tasks(base_dir)
    if not tasks:
        print("（空队列）")
        return 0
    for t in sorted(tasks, key=lambda x: x.name):
        print(f"{t.name:30s} {t.status:10s} attempts={t.attempts}/{t.max_attempts}"
              + (f"  {t.last_error}" if t.last_error else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    base_dir = Path(args.base_dir)

    if args.register:
        task = _register_from_json(base_dir, args.register)
        print(f"已注册任务: {task.name}（task_id={task.task_id or '待生成'}）")
        return 0

    if args.unregister:
        ok = unregister_task(base_dir, args.unregister)
        print(f"注销 {args.unregister}: {'成功' if ok else '未找到'}")
        return 0

    if args.status:
        return asyncio.run(_cmd_status(base_dir))

    # 守护模式
    wd = Watchdog(base_dir=base_dir, interval=args.interval)
    if args.once:
        asyncio.run(wd.tick())
        print(f"已执行一轮。状态见 {base_dir}/status/summary.txt")
        return 0
    print(f"守护进程启动: base_dir={base_dir} interval={args.interval}s（Ctrl+C 退出）")
    try:
        asyncio.run(wd.run())
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在优雅退出...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
