"""GAP-03 委托模式端到端验证：真实 AgentTeams 平台完整闭环留痕。

职责：
  1. 检测 AgentTeams 平台就绪状态
  2. 通过 `run_pdca_task(mock=False)` 走真实委托模式（_run_delegated）
  3. 完整闭环全链路：提交任务 → 轮询里程碑 → 同步状态机 → 生成评价报告
  4. 产出证据到 `data/e2e-<task_id>/`：
       - state.json（最终状态机）
       - audit/*.jsonl（结构化审计留痕）
       - scorecards/*.json（评价成绩单）
       - verify-report.json（验证报告：任务信息/里程碑/耗时/结论）

支持断点续传：本脚本依赖 AgentTeamsClient 的 TaskCheckpoint（GAP-07），
若首次运行超时未完成，checkpoint 已落盘，重跑同 task_id 会从断点继续。

用法（宿主执行，需 AgentTeams 平台 + LLM 网关可用）：
    cd software-dev-fullflow/src
    $env:AGENTTEAMS_ADMIN_PASSWORD = "AgentTeams2026!"
    python ..\\scripts\\verify-delegated-e2e.py "修复登录接口空用户名返回500"

参数：
    spec        ：任务规格（位置参数，默认内置演示任务）
    --task-id   ：指定 task_id（用于断点续传，默认 uuid hex[:8]）
    --mock      ：切到 mock 模式（仅验证客户端逻辑，不连平台）
    --no-export ：不导出证据目录（仅跑闭环）
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Windows 控制台默认 GBK 无法输出 UTF-8 emoji/特殊字符 → 强制 UTF-8（replace 兜底），
# 否则 print 含 emoji（如成绩单 report）会抛 OSError: [Errno 22]。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 把 src/ 加入 sys.path（loop 包根目录）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from loop.agentteams_client import AgentTeamsClient  # noqa: E402
from loop.agentteams_loop import run_pdca_task  # noqa: E402
from loop.state import State  # noqa: E402

DEFAULT_SPEC = "修复登录接口在空用户名时返回 500 的问题"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _collect_evidence(task_id: str, workdir: Path, out_dir: Path) -> dict:
    """收集闭环证据：state.json / audit / scorecards。"""
    evidence: dict[str, str | bool] = {}
    tasks_dir = workdir / "shared" / "tasks" / task_id

    # 1. 状态机
    state_path = tasks_dir / "state.json"
    if state_path.exists():
        data = json.loads(state_path.read_text(encoding="utf-8"))
        evidence["state.json"] = str(state_path)
        evidence["final_state"] = data.get("state", "")
        evidence["milestones"] = list(data.get("milestones", {}).keys())
        evidence["has_retrospect_done"] = "RETROSPECT_DONE" in data.get("milestones", {})

    # 2. 审计日志
    audit_dir = workdir / "shared" / "audit"
    audit_files = sorted(audit_dir.glob("*.jsonl")) if audit_dir.exists() else []
    evidence["audit_files"] = [str(p) for p in audit_files]

    # 3. 评价成绩单（落盘在 shared/agents/<name>/scorecard.json，递归 glob）
    agents_dir = workdir / "shared" / "agents"
    scorecards = sorted(agents_dir.rglob("*.json")) if agents_dir.exists() else []
    evidence["scorecards"] = [str(p) for p in scorecards]

    return evidence


async def main() -> None:
    args = [a for a in sys.argv[1:]]

    mock = "--mock" in args
    args = [a for a in args if a != "--mock"]
    no_export = "--no-export" in args
    args = [a for a in args if a != "--no-export"]

    task_id = ""
    for i, a in enumerate(args):
        if a == "--task-id" and i + 1 < len(args):
            task_id = args[i + 1]
            args = [args[j] for j in range(len(args)) if j != i and j != i + 1]
            break

    spec = " ".join(args).strip() if args else DEFAULT_SPEC
    if not task_id:
        task_id = uuid.uuid4().hex[:8]

    os.environ.setdefault("AGENTTEAMS_ADMIN_PASSWORD", "AgentTeams2026!")
    os.environ.setdefault("AGENTTEAMS_MANAGER_USER", "manager")

    workdir = Path(__file__).resolve().parent.parent / "src" / "data"
    workdir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("GAP-03 委托模式端到端验证")
    print(f"  task_id : {task_id}")
    print(f"  spec    : {spec}")
    print(f"  mock    : {mock}")
    print(f"  workdir : {workdir}")
    print("=" * 64)

    # 非 mock 模式先做平台就绪预检
    if not mock:
        client = AgentTeamsClient(mode="docker")
        try:
            st = await client.status()
            ready = st.get("pdca_workers_ready", False)
            print(f"[预检] PDCA Worker 就绪: {ready}  workers={st.get('workers', [])}")
            if not ready:
                print("  ⚠ Worker 未全部就绪，脚本会尝试确保（或直接跑，让 Manager 按需补齐）")
        except Exception as e:  # noqa: BLE001
            print(f"[预检] 平台状态查询失败: {e}")
            print("  → 委托模式需真实平台，请先启动 AgentTeams。降级可加 --mock 验证客户端逻辑。")
            return
        await client.close()

    # 跑完整委托模式闭环
    try:
        state = await run_pdca_task(spec=spec, workdir=workdir, mock=mock, task_id=task_id)
    except Exception as e:  # noqa: BLE001
        print(f"\n✘ 委托模式执行异常: {e}")
        print("  （若为 LLM 网关/平台问题，可检查 checkpoint 后重跑同 task_id 从断点继续）")
        return

    # 汇总结论
    final_state = state.state.value
    has_retrospect = "RETROSPECT_DONE" in state.milestones
    print("\n" + "=" * 64)
    print(f"最终状态   : {final_state}")
    print(f"闭环完成   : {'[OK] 是' if has_retrospect else '[X] 否'}")
    print(f"里程碑     : {list(state.milestones.keys())}")
    print("=" * 64)

    # 导出证据
    if not no_export:
        out_dir = workdir / "e2e" / f"e2e-{task_id}"
        out_dir.mkdir(parents=True, exist_ok=True)

        evidence = _collect_evidence(task_id, workdir, out_dir)
        report = {
            "task_id": task_id,
            "spec": spec,
            "mock": mock,
            "final_state": final_state,
            "closed_loop": has_retrospect,
            "milestones": list(state.milestones.keys()),
            "exported_at": _ts(),
            "evidence": evidence,
        }
        report_path = out_dir / "verify-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[EXPORT] 证据已导出: {out_dir}")
        print(f"   验证报告: {report_path}")
        for k, v in evidence.items():
            if isinstance(v, list):
                print(f"   {k}: {len(v)} 个文件")
            elif k in ("final_state", "has_retrospect_done"):
                print(f"   {k}: {v}")
        print(f"   完整闭环证据: {'是' if evidence.get('has_retrospect_done') else '否'}")

    # 退出码供 CI/脚本判断
    sys.exit(0 if has_retrospect else 1)


if __name__ == "__main__":
    asyncio.run(main())
