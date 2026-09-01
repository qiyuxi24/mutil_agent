#!/usr/bin/env python3
"""打包 GOAI 赛道三参赛代码包（2026-08-16 新版，对齐"一套班子 + 固定 Leader"架构）。

用法：
    python scripts/package-submission.py            # 生成到 提交包/GOAI-赛道三-软件研发全流程协同-代码包.zip
    python scripts/package-submission.py --out <path>   # 自定义输出路径

思路（沿用 2026-08-15 打包模式）：
    1) git ls-files software-dev-fullflow          # 已跟踪的参赛文件
    2) 去掉已删除的文件（team-leader.yaml 等）
    3) 补入未跟踪的参赛文件（新 skill / 新 worker / 新测试 / requirements.txt 等）
    4) 排除废弃文件（reverse_gateway.py / workbuddy_client.py）与敏感/运行时数据
    5) 打 zip
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # .../mutil_agent
PROJ = ROOT / "software-dev-fullflow"               # 项目根
GIT = "git"

# 已跟踪文件（git ls-files），相对项目根
def git_ls_files() -> list[str]:
    r = subprocess.run(
        [GIT, "-C", str(ROOT), "-c", "core.quotepath=false", "ls-files", "software-dev-fullflow"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if r.returncode != 0:
        sys.exit(f"git ls-files 失败: {r.stderr}")
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]

# 未跟踪参赛文件（相对项目根）；这些是新架构落地新增、尚未 commit 的文件
UNTRACKED_PATHS = [
    # 声明/配置
    "software-dev-fullflow/Dockerfile.client",
    "software-dev-fullflow/requirements.txt",
    "software-dev-fullflow/TOOLCHAIN-PRODUCTION-PLAN.md",
    # 设计文档
    "software-dev-fullflow/design/TEAM-ECOSYSTEM-RESTRUCTURE.md",
    "software-dev-fullflow/design/TEAM-REFACTOR-SINGLE-BANCHANG.md",
    # 脚本
    "software-dev-fullflow/scripts/ci-pipeline-simulator.ps1",
    "software-dev-fullflow/scripts/team-by-project.ps1",
    "software-dev-fullflow/scripts/verify-worker-single-source.py",
    # Skill（新协同/搭建能力）
    "software-dev-fullflow/skills/agent-memory",
    "software-dev-fullflow/skills/backend-impl",
    "software-dev-fullflow/skills/deploy-runtime",
    "software-dev-fullflow/skills/dynamic-hiring",
    "software-dev-fullflow/skills/project-management",
    "software-dev-fullflow/skills/site-design",
    "software-dev-fullflow/skills/task-coordination",
    "software-dev-fullflow/skills/team-comm",
    "software-dev-fullflow/skills/team-management",
    # Worker 详细设计（SOUL.md）
    "software-dev-fullflow/src/agentteams/workers/backend",
    "software-dev-fullflow/src/agentteams/workers/frontend",
    "software-dev-fullflow/src/agentteams/workers/leader",
    # 工具链 MCP 适配
    "software-dev-fullflow/src/agentteams/toolchains/mcp_adapter.py",
    # 上下文事件常量
    "software-dev-fullflow/src/loop/context/events.py",
    # 测试
    "software-dev-fullflow/tests/test_knowledge_tracker.py",
    "software-dev-fullflow/tests/test_memory_registry.py",
    "software-dev-fullflow/tests/test_task_route.py",
    "software-dev-fullflow/tests/test_team_comm.py",
]

# 已删除（不再打包）的文件，相对项目根
DELETED_PATHS = {
    "software-dev-fullflow/src/agentteams/team-leader.yaml",
}

# 废弃文件（逆向 CodeBuddy/网关适配，非参赛内容，绝不打包）
DEPRECATED_PATHS = {
    "software-dev-fullflow/src/loop/reverse_gateway.py",
    "software-dev-fullflow/src/loop/workbuddy_client.py",
}

# 任何路径含这些关键字的排除（运行时/敏感/中间产物）
# 注意：不含 ".env" 整体，避免误伤 .env.example 模板；.env 单独精确判断。
EXCLUDE_KEYWORDS = [
    "__pycache__", ".venv", ".pytest_cache", ".mypy_cache",
    "controller-env-", "data/", "/shared/", "shared/",
    ".log", ".err", ".out", "reports/", "eval_reference", ".codebuddy",
    "mbti-site-e2e-", "e2e-log-", "loop-delegated", "web-demo-",
]


def is_excluded(rel: str) -> bool:
    low = rel.lower()
    # .env.example 模板保留；真正的 .env（配置密钥）排除
    if low.endswith(".env.example"):
        return False
    if any(k in low for k in EXCLUDE_KEYWORDS):
        return True
    if low.endswith(".pyc") or low.endswith(".pyo"):
        return True
    if low.endswith(".env"):
        return True
    return False


def collect_files() -> list[str]:
    files: set[str] = set()
    for p in git_ls_files():
        files.add(p)
    # 补未跟踪参赛文件（目录展开）
    for p in UNTRACKED_PATHS:
        absp = ROOT / p
        if not absp.exists():
            continue
        if absp.is_dir():
            for f in absp.rglob("*"):
                if f.is_file():
                    files.add(str(f.relative_to(ROOT)).replace("\\", "/"))
        else:
            files.add(p)
    # 移除已删除/废弃
    files -= DELETED_PATHS
    files -= DEPRECATED_PATHS
    # 过滤排除项
    return sorted(f for f in files if not is_excluded(f))


def main() -> None:
    out_arg = None
    if "--out" in sys.argv:
        out_arg = sys.argv[sys.argv.index("--out") + 1]
    out_path = Path(out_arg) if out_arg else ROOT / "提交包" / "GOAI-赛道三-软件研发全流程协同-代码包.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    files = collect_files()
    if not files:
        sys.exit("未收集到任何文件")

    if out_path.exists():
        out_path.unlink()

    n = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            src = ROOT / f
            if not src.exists():
                continue
            zf.write(src, f)
            n += 1

    size = out_path.stat().st_size
    print(f"✅ 已生成: {out_path}")
    print(f"   文件数: {n}  |  大小: {size/1024:.1f} KB")

    # 敏感信息校验
    print("\n--- 敏感信息校验（zip 内 .env / controller-env）---")
    env_hits, cred_hits = 0, 0
    with zipfile.ZipFile(out_path, "r") as zf:
        names = zf.namelist()
        for nm in names:
            b = os.path.basename(nm)
            if b == ".env" or nm.endswith(".env"):
                env_hits += 1
            if "controller-env" in b:
                cred_hits += 1
    print(f"   .env 匹配: {env_hits}（应为 0，模板 .env.example 除外）")
    print(f"   controller-env 匹配: {cred_hits}（应为 0）")


if __name__ == "__main__":
    main()
