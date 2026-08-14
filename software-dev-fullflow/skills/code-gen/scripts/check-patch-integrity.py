#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check-patch-integrity.py — code-gen Skill 的「补丁完整性静态检查」脚本

用途：在 Fixer 应用补丁后、提交前，做确定性静态自检（对应 SKILL.md 执行步骤第 4 步）。
不依赖任何第三方库，只用标准库，可在 Worker 沙箱容器（copaw）或本地直接运行。

检查项（全部确定性，无 LLM 参与）：
  1. file_exists    —— changed_files 是否真实存在于工作区
  2. diff_consistency —— diff 统计（additions/deletions）与补丁实际改动是否一致（提供 patch 时）
  3. syntax_check   —— Python 文件语法编译检查（py_compile）
  4. sensitive_scan —— 改动文件是否越界触碰敏感文件（.env/credentials/providers.json 等）

输出（JSON，退出码 0=pass / 1=fail / 2=参数错误）：
  {"integrity": "pass|fail", "checks": {...}, "errors": [...]}

用法：
  python3 check-patch-integrity.py --fix-json fix.json --workspace /path/to/repo
  python3 check-patch-integrity.py --patch fix.patch --workspace /path/to/repo
  python3 check-patch-integrity.py --fix-json fix.json --workspace . --patch fix.patch
"""

import argparse
import json
import os
import py_compile
import re
import sys
import tempfile

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

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def parse_args():
    p = argparse.ArgumentParser(description="code-gen 补丁完整性静态检查")
    p.add_argument("--fix-json", help="fix-summary.json 路径（含 changed_files/diff_stats）")
    p.add_argument("--patch", help="unified diff 补丁文件路径（可选）")
    p.add_argument("--workspace", required=True, help="仓库工作区根目录")
    return p.parse_args()


def load_fix_json(path):
    """读取 fix-summary.json，返回 dict；缺失字段给默认值。"""
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def check_file_exists(changed_files, workspace):
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


def check_sensitive(changed_files):
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


def parse_diff_stats(patch_path):
    """解析 unified diff，返回 {files, additions, deletions}。"""
    stats = {"files": 0, "additions": 0, "deletions": 0}
    if not patch_path or not os.path.isfile(patch_path):
        return None
    try:
        with open(patch_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None
    files = set()
    for line in lines:
        if line.startswith("+++ "):
            # +++ b/path 或 +++ path
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


def check_diff_consistency(declared, patch_path):
    """对比 fix.json 声明的 diff_stats 与补丁实际统计。"""
    actual = parse_diff_stats(patch_path)
    if actual is None:
        return {"status": "skip", "detail": "无补丁文件，跳过 diff 一致性检查"}
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


def check_syntax(changed_files, workspace):
    """对 Python 文件做 py_compile 语法检查。"""
    py_files = [f for f in changed_files if f.endswith(".py")]
    if not py_files:
        return {"status": "skip", "detail": "无 Python 文件，跳过语法检查"}
    failed = []
    for f in py_files:
        fp = os.path.join(workspace, f)
        if not os.path.isfile(fp):
            continue  # 存在性已单独检查，这里跳过不重复报错
        try:
            py_compile.compile(fp, cfile=tempfile.NamedTemporaryFile(delete=True).name, doraise=True)
        except py_compile.PyCompileError as e:
            failed.append({"file": f, "error": str(e)})
    if failed:
        return {"status": "fail", "failed": failed}
    return {"status": "pass", "checked": len(py_files)}


def main():
    args = parse_args()
    workspace = args.workspace
    if not os.path.isdir(workspace):
        print(json.dumps({"integrity": "fail", "errors": [f"workspace 不存在: {workspace}"]}, ensure_ascii=False))
        sys.exit(EXIT_USAGE)

    fix_data = load_fix_json(args.fix_json)
    changed_files = fix_data.get("changed_files", [])
    diff_stats = fix_data.get("diff_stats", {})

    checks = {}
    checks["file_exists"] = check_file_exists(changed_files, workspace)
    checks["sensitive_scan"] = check_sensitive(changed_files)
    checks["diff_consistency"] = check_diff_consistency(diff_stats, args.patch)
    checks["syntax_check"] = check_syntax(changed_files, workspace)

    errors = []
    for name, result in checks.items():
        if result.get("status") == "fail":
            errors.append({name: result})

    integrity = "fail" if errors else "pass"
    report = {
        "integrity": integrity,
        "checks": checks,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(EXIT_PASS if integrity == "pass" else EXIT_FAIL)


if __name__ == "__main__":
    main()
