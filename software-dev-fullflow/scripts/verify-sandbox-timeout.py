#!/usr/bin/env python3
"""verify-sandbox-timeout.py
阶段二「坏任务 3」验证：死循环应被 execute_shell_command 的 timeout 掐断，
且不影响其他组件。

在 copaw worker 容器内直接调用 shell 工具，验证：
  - 死循环 + timeout=3 → 约 3 秒后被 SIGKILL，返回 exit code -1 + 超时信息
  - 正常命令 → 秒回，不被误伤

用法（宿主机）：
  docker cp scripts/verify-sandbox-timeout.py agentteams-worker-fixer:/tmp/
  docker exec agentteams-worker-fixer sh -c '
    /opt/venv/standard/bin/python3 /tmp/verify-sandbox-timeout.py'
"""
import asyncio
import time

from copaw.agents.tools.shell import execute_shell_command


def _text(resp) -> str:
    try:
        blocks = resp.content
        return "\n".join(getattr(b, "text", str(b)) for b in blocks)
    except Exception:
        return str(resp)


async def main():
    print("== 坏任务 3：死循环应被 timeout 掐断 ==")
    t0 = time.monotonic()
    resp = await execute_shell_command("while true; do :; done", timeout=3)
    elapsed = time.monotonic() - t0
    text = _text(resp)
    timed_out = ("timeout" in text.lower() or "exit code -1" in text)
    print(f"elapsed = {elapsed:.2f}s (期望 ≈3s，而非无限)")
    print(f"timed_out_detected = {timed_out}")
    print("--- 工具返回 ---")
    print(text[:500])

    print()
    print("== 对照组：正常命令秒回 ==")
    t0 = time.monotonic()
    resp2 = await execute_shell_command("echo sandbox-ok && pwd", timeout=10)
    elapsed2 = time.monotonic() - t0
    text2 = _text(resp2)
    print(f"elapsed = {elapsed2:.2f}s")
    print("--- 工具返回 ---")
    print(text2[:300])

    print()
    print("=" * 60)
    ok = (1.5 <= elapsed <= 8.0) and timed_out and ("sandbox-ok" in text2)
    print(f"RESULT: {'PASS' if ok else 'FAIL'} "
          f"(死循环 {elapsed:.2f}s 被掐断={timed_out}, 正常命令含 sandbox-ok={('sandbox-ok' in text2)})")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
