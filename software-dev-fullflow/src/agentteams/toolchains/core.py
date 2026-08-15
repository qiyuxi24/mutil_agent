# -*- coding: utf-8 -*-
"""
core.py —— 工具链共享确定性内核

把 skills/code-gen/scripts/check-patch-integrity.py 与
skills/test-generation/scripts/verify_test_gate.py 的确定性逻辑提炼为可复用纯函数，
供 code_scan_service / test_platform_service 作为业务内核调用。

设计原则：确定性优先（无 LLM 参与），所有判定都是可重复、可验证的机器逻辑。
这是 AgentTeams 平台「确定性验证闸门」的核心：Fixer 扫描 → Tester 测试 → 判定 PASS/FAIL。

仅依赖标准库。
"""

from __future__ import annotations

import json
import os
import py_compile
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Optional

# 敏感文件/路径片段（与沙箱 file_guard 对齐），改动即判越界
SENSITIVE_PATTERNS = (
    ".env",
    "credentials",
    "providers.json",
    "config.json",
    ".secret",
    "id_rsa",
    "id_ed25519",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
)

PYTEST_SUMMARY_RE = re.compile(
    r"(?P<passed>\d+)\s+passed(?:\s*,\s*(?P<failed>\d+)\s+failed)?"
)


# ============================================================
# 代码扫描内核（复用 check-patch-integrity.py）
# ============================================================

@dataclass
class ScanReport:
    """一次代码扫描的确定性结果。"""
    repo: str
    branch: str
    integrity: str = "skip"  # "pass" | "fail" | "skip"
    checks: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "branch": self.branch,
            "integrity": self.integrity,
            "checks": self.checks,
            "issues": self.issues,
            "errors": self.errors,
        }


def load_fix_json(path: Optional[str]) -> dict:
    """读取 fix-summary.json，返回 dict；缺失字段给默认值。"""
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def check_file_exists(changed_files: list, workspace: str) -> dict:
    """检查 changed_files 是否都存在于工作区。"""
    if not changed_files:
        return {"status": "skip", "detail": "changed_files 为空，跳过存在性检查"}
    missing = []
    for f in changed_files:
        fp = os.path.join(workspace, f)
        if not os.path.isfile(fp):
            missing.append(f)
    if missing:
        return {"status": "fail", "missing": missing}
    return {"status": "pass", "checked": len(changed_files)}


def check_sensitive(changed_files: list) -> dict:
    """检查改动文件是否触碰敏感文件。"""
    if not changed_files:
        return {"status": "skip", "detail": "changed_files 为空"}
    hits = []
    for f in changed_files:
        lower = f.lower()
        for pat in SENSITIVE_PATTERNS:
            if pat in lower:
                hits.append(f)
                break
    if hits:
        return {"status": "fail", "sensitive_files": hits}
    return {"status": "pass", "checked": len(changed_files)}


def parse_diff_stats(patch_text: str) -> Optional[dict]:
    """解析 unified diff 文本，返回 {files, additions, deletions}。"""
    if not patch_text:
        return None
    stats = {"files": 0, "additions": 0, "deletions": 0}
    files = set()
    for line in patch_text.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target.startswith("b/"):
                target = target[2:]
            files.add(target)
        elif line.startswith("+") and not line.startswith("+++"):
            stats["additions"] += 1
        elif line.startswith("-") and not line.startswith("---"):
            stats["deletions"] += 1
    stats["files"] = len(files)
    return stats


def check_diff_consistency(declared: dict, patch_text: str) -> dict:
    """对比 fix.json 声明的 diff_stats 与补丁实际统计。"""
    actual = parse_diff_stats(patch_text)
    if actual is None:
        return {"status": "skip", "detail": "无补丁文本，跳过 diff 一致性检查"}
    if not declared:
        return {"status": "skip", "detail": "fix.json 未声明 diff_stats，跳过对比"}
    mismatches = []
    for key in ("files", "additions", "deletions"):
        decl_val = declared.get(key)
        if decl_val is None:
            continue
        if int(decl_val) != actual[key]:
            mismatches.append({"field": key, "declared": int(decl_val), "actual": actual[key]})
    if mismatches:
        return {"status": "fail", "mismatches": mismatches, "actual": actual}
    return {"status": "pass", "actual": actual}


def check_syntax(changed_files: list, workspace: str) -> dict:
    """对 Python 文件做 py_compile 语法检查。"""
    py_files = [f for f in changed_files if f.endswith(".py")]
    if not py_files:
        return {"status": "skip", "detail": "无 Python 文件，跳过语法检查"}
    failed = []
    for f in py_files:
        fp = os.path.join(workspace, f)
        if not os.path.isfile(fp):
            continue
        try:
            py_compile.compile(fp, cfile=tempfile.NamedTemporaryFile(delete=True).name, doraise=True)
        except py_compile.PyCompileError as e:
            failed.append({"file": f, "error": str(e)})
    if failed:
        return {"status": "fail", "failed": failed}
    return {"status": "pass", "checked": len(py_files)}


def run_code_scan(
    repo: str,
    branch: str = "main",
    workspace: Optional[str] = None,
    changed_files: Optional[list] = None,
    diff_stats: Optional[dict] = None,
    patch_text: Optional[str] = None,
) -> ScanReport:
    """
    对仓库做确定性代码扫描（补丁完整性静态检查）。

    Args:
        repo: 仓库名，如 org/repo。
        branch: 分支名。
        workspace: 工作区根目录（提供后做文件存在性/语法检查）。
        changed_files: 改动的文件列表。
        diff_stats: fix.json 声明的 diff 统计 {files, additions, deletions}。
        patch_text: unified diff 文本（提供后做 diff 一致性检查）。
    """
    report = ScanReport(repo=repo, branch=branch)
    checks = {}

    if workspace and os.path.isdir(workspace):
        cf = changed_files or []
        checks["file_exists"] = check_file_exists(cf, workspace)
        checks["sensitive_scan"] = check_sensitive(cf)
        checks["syntax_check"] = check_syntax(cf, workspace)
    checks["diff_consistency"] = check_diff_consistency(diff_stats or {}, patch_text or "")

    errors = []
    issues = []
    for name, result in checks.items():
        if result.get("status") == "fail":
            errors.append({name: result})
            for key in ("missing", "sensitive_files", "failed", "mismatches"):
                if key in result:
                    issues.append({name: key, "data": result[key]})

    report.checks = checks
    report.errors = errors
    report.issues = issues
    report.integrity = "fail" if errors else "pass"
    return report


# ============================================================
# 测试平台内核（复用 verify_test_gate.py）
# ============================================================

def run_test_cmd(cmd: str, timeout: int = 120, cwd: Optional[str] = None) -> dict:
    """执行测试命令，返回 {ok, returncode, passed, failed, timed_out, output}。"""
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "timed_out": True, "returncode": None,
                "passed": 0, "failed": 0, "output": "timeout"}
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    passed, failed = 0, 0
    m = PYTEST_SUMMARY_RE.search(output)
    if m:
        passed = int(m.group("passed"))
        failed = int(m.group("failed") or 0)
    ok = (proc.returncode == 0) and (failed == 0)
    return {"ok": ok, "timed_out": False, "returncode": proc.returncode,
            "passed": passed, "failed": failed, "output": output}


def evaluate_test_gate(
    cmd: Optional[str] = None,
    result_json: Optional[dict] = None,
    timeout: int = 120,
    coverage_threshold: float = 0.0,
    cwd: Optional[str] = None,
) -> dict:
    """
    汇总命令/结果两种模式，输出确定性判定（PASS/FAIL）。

    Args:
        cmd: 要执行的测试命令（如 "pytest -q"）。
        result_json: 测试结果摘要 {total, passed, failed, coverage}。
        timeout: 测试命令超时秒数。
        coverage_threshold: 覆盖率阈值 0~1（0 表示不强制）。
        cwd: 执行测试命令的工作目录。
    """
    reasons = []
    summary = {"total": 0, "passed": 0, "failed": 0, "coverage": None}

    if cmd:
        r = run_test_cmd(cmd, timeout, cwd)
        summary["passed"] = r["passed"]
        summary["failed"] = r["failed"]
        summary["total"] = r["passed"] + r["failed"]
        if r.get("timed_out"):
            reasons.append(f"测试命令超时（>{timeout}s）")
        elif r["returncode"] != 0:
            reasons.append(f"测试命令退出码非 0（{r['returncode']}）")
        if r["failed"] > 0:
            reasons.append(f"{r['failed']} 个用例失败")

    if result_json:
        s = result_json or {}
        summary = {
            "total": s.get("total", 0),
            "passed": s.get("passed", 0),
            "failed": s.get("failed", 0),
            "coverage": s.get("coverage"),
        }
        if s.get("failed") and int(s["failed"]) > 0:
            reasons.append(f"{s['failed']} 个用例失败")

    if coverage_threshold > 0:
        cov = summary.get("coverage")
        if cov is None:
            reasons.append("未提供覆盖率数据，无法满足覆盖率门禁")
        elif float(cov) < coverage_threshold:
            reasons.append(f"覆盖率 {cov} 低于阈值 {coverage_threshold}")

    verdict = "FAIL" if reasons else "PASS"
    return {"verdict": verdict, "summary": summary, "reasons": reasons}


# 内存任务/结果存储（服务进程内，重启即清空；真实接入可换 PolarDB/RocketMQ）
SCAN_STORE: dict[str, dict] = {}
TEST_STORE: dict[str, dict] = {}
_COUNTER = {"scan": 0, "test": 0}


def _next_id(prefix: str) -> str:
    _COUNTER[prefix] += 1
    return f"{prefix}-{_COUNTER[prefix]:04d}"
