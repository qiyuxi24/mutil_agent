# -*- coding: utf-8 -*-
"""GAP-26 守护进程测试：任务队列注册、周期拉起、失败重试、卡死/超时告警、断点续跑。

注：Watchdog.tick() 是非阻塞单轮调度 —— 拉起执行器后结果在下一轮 tick 收集，
测试用 _drive() 推进多轮（模拟真实守护循环的 interval 轮询）。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from loop.watchdog import (
    Watchdog,
    WatchTask,
    load_tasks,
    register_task,
    unregister_task,
)


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

async def _drive(wd: Watchdog, rounds: int = 6, settle: float = 0.05) -> None:
    """推进多轮 tick + 让执行器有时间完成（模拟守护循环轮询）。"""
    for _ in range(rounds):
        await wd.tick()
        await asyncio.sleep(settle)


def _task(**overrides) -> WatchTask:
    base = dict(name="t1", spec="修复登录接口500", mock=True)
    base.update(overrides)
    return WatchTask(**base)


# --------------------------------------------------------------------------- #
# 任务队列：注册 / 注销 / 持久化
# --------------------------------------------------------------------------- #

async def test_register_persists(tmp_path: Path) -> None:
    register_task(tmp_path, _task())

    loaded = load_tasks(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].name == "t1"
    assert loaded[0].status == "pending"
    # 落盘可读
    raw = json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
    assert raw[0]["spec"] == "修复登录接口500"


async def test_register_same_name_preserves_task_id(tmp_path: Path) -> None:
    """同名覆盖时保留原 task_id（断点续跑依据）。"""
    register_task(tmp_path, _task(task_id="pdca-123"))
    register_task(tmp_path, _task(spec="新需求"))

    loaded = load_tasks(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].task_id == "pdca-123"
    assert loaded[0].spec == "新需求"


async def test_unregister(tmp_path: Path) -> None:
    register_task(tmp_path, _task())
    assert unregister_task(tmp_path, "t1") is True
    assert load_tasks(tmp_path) == []
    assert unregister_task(tmp_path, "t1") is False


# --------------------------------------------------------------------------- #
# 守护主循环：拉起 → 完成
# --------------------------------------------------------------------------- #

async def test_tick_completes_task(tmp_path: Path) -> None:
    register_task(tmp_path, _task())

    async def runner(task: WatchTask) -> dict:
        return {"status": "completed", "task_id": task.task_id,
                "milestones": ["RETROSPECT_DONE"], "state": "RETROSPECT"}

    wd = Watchdog(tmp_path, interval=1, runner=runner)
    await _drive(wd)

    loaded = load_tasks(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].status == "completed"
    assert loaded[0].attempts == 1
    assert loaded[0].last_error == ""


async def test_tick_launches_and_generates_task_id(tmp_path: Path) -> None:
    """首次拉起自动生成 task_id 并写回队列。"""
    register_task(tmp_path, _task())
    seen: list[str] = []

    async def runner(task: WatchTask) -> dict:
        seen.append(task.task_id)
        return {"status": "completed", "task_id": task.task_id,
                "milestones": ["RETROSPECT_DONE"], "state": "RETROSPECT"}

    wd = Watchdog(tmp_path, runner=runner)
    await _drive(wd)

    assert seen, "执行器应被拉起"
    loaded = load_tasks(tmp_path)
    assert loaded[0].task_id.startswith("pdca-")
    assert loaded[0].status == "completed"


async def test_completed_task_not_relaunched(tmp_path: Path) -> None:
    """任务完成后不再重复拉起。"""
    register_task(tmp_path, _task())

    calls = 0
    async def runner(task: WatchTask) -> dict:
        nonlocal calls
        calls += 1
        return {"status": "completed", "task_id": task.task_id,
                "milestones": ["RETROSPECT_DONE"], "state": "RETROSPECT"}

    wd = Watchdog(tmp_path, interval=0.01, runner=runner)
    await _drive(wd, rounds=4)

    assert calls == 1, f"已完成的任务不应重复拉起，实际 {calls}"
    assert load_tasks(tmp_path)[0].status == "completed"


# --------------------------------------------------------------------------- #
# 失败重试
# --------------------------------------------------------------------------- #

async def test_retry_until_failed(tmp_path: Path) -> None:
    """执行器抛异常 → 重试 → 达 max_attempts 标记 FAILED + 告警。"""
    register_task(tmp_path, _task(max_attempts=3))

    calls = 0
    async def runner(task: WatchTask) -> dict:
        nonlocal calls
        calls += 1
        raise RuntimeError("平台不可用")

    wd = Watchdog(tmp_path, runner=runner)
    await _drive(wd, rounds=10)

    assert calls == 3, f"应恰好尝试 3 次，实际 {calls}"
    loaded = load_tasks(tmp_path)
    assert loaded[0].status == "failed"
    assert loaded[0].attempts == 3
    assert "RuntimeError" in loaded[0].last_error

    alerts = (tmp_path / "alerts.log").read_text(encoding="utf-8")
    assert "[FAILED]" in alerts
    assert "t1" in alerts


async def test_retry_on_runner_error_then_success(tmp_path: Path) -> None:
    """前两次失败、第三次成功 → 最终 completed。"""
    register_task(tmp_path, _task(max_attempts=5))

    calls = 0
    async def runner(task: WatchTask) -> dict:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("断网")
        return {"status": "completed", "task_id": task.task_id,
                "milestones": ["RETROSPECT_DONE"], "state": "RETROSPECT"}

    wd = Watchdog(tmp_path, runner=runner)
    await _drive(wd, rounds=10)

    assert calls == 3
    loaded = load_tasks(tmp_path)
    assert loaded[0].status == "completed"


# --------------------------------------------------------------------------- #
# 超时：整体超时 → 告警，下轮续跑（对齐 wait_for_task 超时恢复语义）
# --------------------------------------------------------------------------- #

async def test_task_timeout_alerts_and_resumes(tmp_path: Path) -> None:
    """执行器挂起超时 → TIMEOUT 告警 → 任务保留，下轮以同一 task_id 续跑。"""
    register_task(tmp_path, _task(task_timeout=0.05))

    # 第一次跑：挂起触发超时；之后记录 task_id 后立即完成
    first = True
    seen_ids: list[str] = []

    async def runner(task: WatchTask) -> dict:
        nonlocal first
        seen_ids.append(task.task_id)
        if first:
            first = False
            await asyncio.sleep(10)
        return {"status": "completed", "task_id": task.task_id,
                "milestones": ["RETROSPECT_DONE"], "state": "RETROSPECT"}

    wd = Watchdog(tmp_path, runner=runner)
    await _drive(wd, rounds=6, settle=0.1)

    alerts = (tmp_path / "alerts.log").read_text(encoding="utf-8")
    assert "[TIMEOUT]" in alerts

    loaded = load_tasks(tmp_path)
    assert loaded[0].status == "completed"
    assert loaded[0].attempts == 2
    # 断点续跑：两轮使用同一 task_id
    assert len(set(seen_ids)) == 1, f"续跑应复用同一 task_id，实际 {seen_ids}"


# --------------------------------------------------------------------------- #
# 卡死检测（detect-only）
# --------------------------------------------------------------------------- #

async def test_stale_alert_detect_only(tmp_path: Path) -> None:
    """任务在跑但状态文件长时间无更新 → STALE 告警（不干预、不杀任务）。"""
    # 预置一个"很久没更新"的 delegation.json（模拟真实任务目录）
    task_id = "pdca-999"
    task_dir = tmp_path / "shared" / "tasks" / task_id
    task_dir.mkdir(parents=True)
    delegation = task_dir / "delegation.json"
    delegation.write_text(json.dumps({"task_id": task_id, "status": "running"}), encoding="utf-8")
    old = time.time() - 7200
    os.utime(delegation, (old, old))

    register_task(tmp_path, _task(workdir=str(tmp_path), task_id=task_id,
                                  stale_after=1, task_timeout=60))

    async def runner(task: WatchTask) -> dict:
        await asyncio.sleep(5)  # 长跑任务（卡住）
        return {"status": "completed", "task_id": task.task_id,
                "milestones": ["RETROSPECT_DONE"], "state": "RETROSPECT"}

    wd = Watchdog(tmp_path, runner=runner)
    await wd.tick()          # 拉起任务
    await asyncio.sleep(0.05)
    await wd.tick()          # 第二轮到 _check_stall：detect-only 告警

    alerts = (tmp_path / "alerts.log").read_text(encoding="utf-8")
    assert "[STALE]" in alerts
    assert task_id in alerts
    # detect-only：任务状态仍 running（未被打断、未重试）
    loaded = load_tasks(tmp_path)
    assert loaded[0].status == "running"


# --------------------------------------------------------------------------- #
# summary / status 落盘
# --------------------------------------------------------------------------- #

async def test_summary_and_status_files(tmp_path: Path) -> None:
    register_task(tmp_path, _task())

    async def runner(task: WatchTask) -> dict:
        return {"status": "completed", "task_id": task.task_id,
                "milestones": ["RETROSPECT_DONE"], "state": "RETROSPECT"}

    wd = Watchdog(tmp_path, runner=runner)
    await _drive(wd)

    summary = (tmp_path / "status" / "summary.txt").read_text(encoding="utf-8")
    assert "t1" in summary and "completed" in summary

    status = json.loads((tmp_path / "status" / "t1.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"


async def test_pid_file(tmp_path: Path) -> None:
    wd = Watchdog(tmp_path)
    wd.write_pid()
    assert (tmp_path / "watchdog.pid").exists()
    wd.clear_pid()
    assert not (tmp_path / "watchdog.pid").exists()
