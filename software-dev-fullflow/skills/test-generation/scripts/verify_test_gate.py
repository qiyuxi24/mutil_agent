#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_test_gate.py — test-generation Skill 的「确定性测试闸门」脚本

用途：作为质量门禁的确定性裁判（对应 SKILL.md 执行步骤第 3/4 步），
把 Tester 的「跑测试 → 判定 PASS/FAIL」从 LLM 自评换成机器判定。
不依赖第三方库，只用标准库，可在 Worker 沙箱容器（copaw）或本地运行。

两种模式（可同时给）：
  1. --cmd：实际执行测试命令（如 "pytest -q"），解析退出码 + 摘要输出
  2. --result-json：读取 test.json 的 summary（total/passed/failed/coverage）

判定规则（全部确定性）：
  - 有任一 failed 或 error → FAIL
  - 覆盖率低于 --coverage-threshold → FAIL
  - 测试命令执行超时 → FAIL
  - 命令退出码非 0 → FAIL
  - 否则 PASS

输出（JSON，退出码 0=PASS / 1=FAIL / 2=用法错误）：
  {"verdict": "PASS|FAIL", "summary": {...}, "reasons": [...]}

用法：
  python3 verify_test_gate.py --cmd "pytest -q" --timeout 120 --coverage-threshold 0.8
  python3 verify_test_gate.py --result-json test.json --coverage-threshold 0.8
"""

import argparse
import json
import os
import re
import subprocess
import sys

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

PYTEST_SUMMARY_RE = re.compile(
    r"(?P<passed>\d+)\s+passed(?:\s*,\s*(?P<failed>\d+)\s+failed)?"
)


def parse_args():
    p = argparse.ArgumentParser(description="test-generation 确定性测试闸门")
    p.add_argument("--cmd", help="要执行的测试命令（如 'pytest -q'）")
    p.add_argument("--result-json", help="test.json 路径（含 summary.total/passed/failed/coverage）")
    p.add_argument("--timeout", type=int, default=120, help="测试命令超时秒数（默认 120）")
    p.add_argument("--coverage-threshold", type=float, default=0.0,
                   help="覆盖率阈值 0~1（默认 0，即不强制）")
    p.add_argument("--cwd", default=None, help="执行测试命令的工作目录")
    return p.parse_args()


def run_tests(cmd, timeout, cwd):
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


def load_result_json(path):
    """读取 test.json 的 summary，返回 {total, passed, failed, coverage}。"""
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    return {
        "total": summary.get("total", 0),
        "passed": summary.get("passed", 0),
        "failed": summary.get("failed", 0),
        "coverage": summary.get("coverage"),
    }


def evaluate(cmd, timeout, cwd, result_json, coverage_threshold):
    """汇总两种模式结果，输出确定性判定。"""
    reasons = []
    summary = {"total": 0, "passed": 0, "failed": 0, "coverage": None}

    # 命令模式
    if cmd:
        r = run_tests(cmd, timeout, cwd)
        summary["passed"] = r["passed"]
        summary["failed"] = r["failed"]
        summary["total"] = r["passed"] + r["failed"]
        if r.get("timed_out"):
            reasons.append(f"测试命令超时（>{timeout}s）")
        elif r["returncode"] != 0:
            reasons.append(f"测试命令退出码非 0（{r['returncode']}）")
        if r["failed"] > 0:
            reasons.append(f"{r['failed']} 个用例失败")

    # 结果 JSON 模式
    if result_json:
        s = load_result_json(result_json)
        if s is None:
            reasons.append(f"无法读取 result-json: {result_json}")
        else:
            summary = s
            if s["failed"] and int(s["failed"]) > 0:
                reasons.append(f"{s['failed']} 个用例失败")

    # 覆盖率阈值判定
    if coverage_threshold > 0:
        cov = summary.get("coverage")
        if cov is None:
            reasons.append("未提供覆盖率数据，无法满足覆盖率门禁")
        elif float(cov) < coverage_threshold:
            reasons.append(f"覆盖率 {cov} 低于阈值 {coverage_threshold}")

    verdict = "FAIL" if reasons else "PASS"
    return {"verdict": verdict, "summary": summary, "reasons": reasons}


def main():
    args = parse_args()
    if not args.cmd and not args.result_json:
        print(json.dumps({"verdict": "FAIL", "reasons": ["必须提供 --cmd 或 --result-json 之一"]}, ensure_ascii=False))
        sys.exit(EXIT_USAGE)

    result = evaluate(args.cmd, args.timeout, args.cwd, args.result_json, args.coverage_threshold)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(EXIT_PASS if result["verdict"] == "PASS" else EXIT_FAIL)


if __name__ == "__main__":
    main()
