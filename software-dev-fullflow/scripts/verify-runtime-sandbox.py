#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
沙箱阶段三验证：AgentScope Runtime Sandbox（BaseSandbox + Docker 后端）。

对应 TODO GAP-18「沙箱阶段三：AgentScope Runtime 沙箱接入（agentscope-runtime + runtime-sandbox-mcp）」。
本脚本跑通 SDK 直连的最小闭环：启动沙箱容器 → IPython 代码执行（含变量跨 cell 持久）→
Shell 命令执行 → workspace 目录双向映射 → 工具清单 → 容器清理。

前置条件：
  1. Docker 已启动（docker ps 可用）
  2. `demo\.venv` 已安装 agentscope-runtime（pip install agentscope-runtime）
  3. 已拉取镜像（大陆建议阿里云 ACR，见下方用法示例）

用法（Windows PowerShell，在项目根 software-dev-fullflow 下执行）：
  $env:RUNTIME_SANDBOX_REGISTRY = "agentscope-registry.ap-southeast-1.cr.aliyuncs.com"
  demo\.venv\Scripts\python.exe scripts\verify-runtime-sandbox.py

可选参数：
  --workspace <dir>   指定宿主机 workspace 目录（默认 data/runtime-sandbox-ws，自动创建）
  --keep              结束后保留容器不清理（排障用）

退出码：0=全部 PASS；1=存在 FAIL；2=前置条件不满足。
"""
import argparse
import os
import shutil
import subprocess
import sys
import traceback

# 允许从项目根直接运行
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str) -> None:
    """记录并打印一条检查结果。"""
    RESULTS.append((name, bool(passed), detail))
    tag = "PASS" if passed else "FAIL"
    print(f"[{tag}] {name}: {detail}")


def extract_text(resp) -> str:
    """从 MCP 协议响应中递归提取人类可读文本。"""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        parts = [extract_text(i) for i in resp]
        return "\n".join(p for p in parts if p)
    if isinstance(resp, dict):
        for key in ("text", "output", "result", "data", "content", "message", "value"):
            if key in resp:
                t = extract_text(resp[key])
                if t:
                    return t
        return ""
    return str(resp)


def docker_available() -> bool:
    """检查 Docker CLI 是否可用。"""
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return r.returncode == 0
    except Exception:
        return False


def docker_has_container(container_id: str) -> bool:
    """检查指定容器（或前缀）是否仍在运行。"""
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return any(line.strip().startswith(container_id[:12]) for line in r.stdout.splitlines())
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentScope Runtime Sandbox 阶段三验证")
    parser.add_argument("--workspace", default=None, help="宿主机 workspace 目录")
    parser.add_argument("--keep", action="store_true", help="结束后保留容器（排障）")
    args = parser.parse_args()

    # ---------- 前置检查 ----------
    if not docker_available():
        print("[FATAL] Docker 不可用，请先启动 Docker Desktop")
        return 2
    record("前置检查: Docker", True, "docker ps 正常")

    try:
        from agentscope_runtime.sandbox import BaseSandbox  # noqa: F401
    except ImportError as e:
        print(
            "[FATAL] 未安装 agentscope-runtime，请执行: "
            "demo\\.venv\\Scripts\\pip.exe install agentscope-runtime"
        )
        print(f"       原始错误: {e}")
        return 2
    record("前置检查: agentscope-runtime", True, "BaseSandbox 可导入")

    registry = os.getenv("RUNTIME_SANDBOX_REGISTRY", "")
    print(
        f"[INFO] 镜像源: {registry or 'Docker Hub (默认)'}"
        f" | 镜像: {os.getenv('RUNTIME_SANDBOX_IMAGE_NAMESPACE', 'agentscope')}"
        f"/runtime-sandbox-base:{os.getenv('RUNTIME_SANDBOX_IMAGE_TAG', 'latest')}"
    )

    # ---------- 初始化沙箱 ----------
    workspace = args.workspace or os.path.join(BASE_DIR, "data", "runtime-sandbox-ws")
    workspace = os.path.abspath(workspace)
    os.makedirs(workspace, exist_ok=True)

    sandbox = None
    try:
        sandbox = BaseSandbox(workspace_dir=workspace)
        sandbox.start()
        record("T1 沙箱启动", True, f"sandbox_id={sandbox.sandbox_id} | 模式=embedded(Docker)")

        # ---------- IPython 代码执行 ----------
        r = extract_text(sandbox.run_ipython_cell('print("Hello from AgentScope Sandbox!")'))
        ok = "Hello from AgentScope Sandbox!" in r
        record("T2 IPython hello", ok, r.strip().splitlines()[0] if r.strip() else "(空输出)")

        r = extract_text(
            sandbox.run_ipython_cell("_sum = sum(range(10))\nprint(_sum)")
        )
        ok = "45" in r
        record("T3 IPython 计算", ok, f"sum(range(10)) -> {r.strip()!r}")

        # 变量跨 cell 持久（会话保持）
        sandbox.run_ipython_cell("_x = 42")
        r = extract_text(sandbox.run_ipython_cell("print(_x * 2)"))
        ok = "84" in r
        record("T4 IPython 变量持久", ok, f"_x=42, 下一 cell 输出 _x*2 -> {r.strip()!r}")

        # ---------- Shell 命令执行 ----------
        r = extract_text(sandbox.run_shell_command("echo hello-shell"))
        ok = "hello-shell" in r
        record("T5 Shell echo", ok, r.strip().splitlines()[0] if r.strip() else "(空输出)")

        r = extract_text(sandbox.run_shell_command("uname -s && whoami && pwd"))
        lines = [ln.strip() for ln in r.strip().splitlines() if ln.strip()]
        # 注意：MCP 响应可能把退出码(0)拼在末尾，故只断言首行是 Linux
        ok = bool(lines) and lines[0] == "Linux"
        record("T6 环境隔离(Linux 容器)", ok, "; ".join(lines))

        # ---------- workspace 双向映射 ----------
        marker = "sandbox-phase3-workspace-marker"
        r = extract_text(
            sandbox.run_shell_command(f"echo {marker} > _ws_probe.txt && cat _ws_probe.txt")
        )
        ok = marker in r
        record("T7 Shell 写 workspace", ok, f"容器内写 _ws_probe.txt -> {r.strip()!r}")

        host_file = os.path.join(workspace, "_ws_probe.txt")
        ok = os.path.isfile(host_file) and marker in open(host_file, encoding="utf-8").read()
        record("T8 workspace 挂载(容器→宿主)", ok, f"宿主机可见: {host_file}")

        host_marker = f"host-{os.getpid()}"
        with open(host_file, "w", encoding="utf-8") as f:
            f.write(host_marker)
        r = extract_text(sandbox.run_shell_command("cat _ws_probe.txt"))
        ok = host_marker in r
        record("T9 workspace 挂载(宿主→容器)", ok, f"容器内读回: {r.strip()!r}")

        # ---------- 文件系统工具（fs API） ----------
        r = extract_text(sandbox.fs.read("_ws_probe.txt"))
        ok = host_marker in r
        record("T10 fs.read API", ok, f"sandbox.fs.read('_ws_probe.txt') -> {r.strip()!r}")

        sandbox.fs.write("data.json", '{"phase": 3, "ok": true}')
        r = extract_text(sandbox.run_shell_command("cat data.json"))
        ok = '"ok": true' in r
        record("T11 fs.write API", ok, f"sandbox.fs.write('data.json') -> {r.strip()!r}")

        # ---------- 工具清单 ----------
        try:
            tools = sandbox.list_tools()
            names = sorted(
                n for server in tools.values() for n in (server or {}).keys()
            ) if isinstance(tools, dict) else sorted(str(tools).split(","))
            ok = bool(names) and "run_ipython_cell" in names and "run_shell_command" in names
            record("T12 工具清单", ok, f"共 {len(names)} 个工具: {', '.join(names[:8])}...")
        except Exception as e:
            record("T12 工具清单", False, f"list_tools 异常: {e}")

        # ---------- 清理 ----------
        container_id = sandbox.sandbox_id
        if not args.keep:
            sandbox.close()
            gone = not docker_has_container(container_id)
            record("T13 容器清理", gone, f"容器 {container_id} 已移除" if gone else "容器仍在运行!")
        else:
            print(f"[INFO] --keep 已指定，保留容器 {container_id}")

    except Exception as e:
        record("沙箱执行", False, f"{type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        if sandbox is not None and not args.keep:
            try:
                sandbox.close()
            except Exception:
                pass

    # ---------- 汇总 ----------
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print(f"\n==== 结果汇总: {passed}/{len(RESULTS)} PASS, {failed} FAIL ====")
    for name, ok, detail in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
