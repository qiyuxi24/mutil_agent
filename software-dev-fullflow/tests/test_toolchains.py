# -*- coding: utf-8 -*-
"""工具链确定性内核测试（GAP-01 落地：验证 `src.agentteams.toolchains.core` 可导入）。"""

import tempfile
from pathlib import Path

# 验证 GAP-01：相对导入包结构在 conftest 加 src/ 后可直接 `from ...` 导入
from src.agentteams.toolchains.core import (
    TEST_STORE,
    SCAN_STORE,
    check_diff_consistency,
    check_file_exists,
    check_sensitive,
    evaluate_test_gate,
    load_fix_json,
    parse_diff_stats,
    run_code_scan,
)


def test_load_fix_json_missing_returns_empty():
    assert load_fix_json(None) == {}
    assert load_fix_json("/no/such/path.json") == {}


def test_check_sensitive_detects_env_and_secrets():
    res = check_sensitive([".env", "main.py", "config.json"])
    assert res["status"] == "fail"
    assert ".env" in res["sensitive_files"]
    assert "config.json" in res["sensitive_files"]

    ok = check_sensitive(["main.py", "app/util.py"])
    assert ok["status"] == "pass"
    assert ok["checked"] == 2


def test_check_file_exists_missing():
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "a.py").write_text("x = 1\n", encoding="utf-8")
        res = check_file_exists(["a.py", "missing.py"], tmp)
        assert res["status"] == "fail"
        assert res["missing"] == ["missing.py"]


def test_parse_diff_stats_counts_lines_and_files():
    # diff 行必须以 + / - 开头才会被统计（`+++ b/` 头计入文件，`---` 头忽略）
    patch = "+++ b/login.py\n--- a/login.py\n-b\n+c\n+b2\n"
    stats = parse_diff_stats(patch)
    assert stats["files"] == 1
    assert stats["additions"] == 2
    assert stats["deletions"] == 1


def test_check_diff_consistency_mismatch():
    declared = {"files": 3, "additions": 10, "deletions": 1}
    patch = "+++ b/a.py\n" "  +b\n" "  -c\n"
    res = check_diff_consistency(declared, patch)
    assert res["status"] == "fail"
    assert res["actual"]["files"] == 1


def test_run_code_scan_marks_fail_on_sensitive():
    # 敏感扫描需要 workspace（否则跳过存在性/敏感/语法检查，仅做 diff_consistency）
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "main.py").write_text("x = 1\n", encoding="utf-8")
        report = run_code_scan(
            repo="org/repo",
            workspace=tmp,
            changed_files=[".env", "main.py"],
        )
        assert report.integrity == "fail"
        assert report.issues  # 有敏感文件问题


def test_run_code_scan_pass_without_workspace():
    report = run_code_scan(repo="org/repo")
    assert report.integrity == "pass"
    assert report.errors == []


def test_evaluate_test_gate_pass():
    gate = evaluate_test_gate(result_json={"total": 12, "passed": 12, "failed": 0})
    assert gate["verdict"] == "PASS"
    assert gate["reasons"] == []


def test_evaluate_test_gate_fail_on_failures():
    gate = evaluate_test_gate(result_json={"total": 12, "passed": 10, "failed": 2})
    assert gate["verdict"] == "FAIL"
    assert any("失败" in r for r in gate["reasons"])


def test_evaluate_test_gate_coverage_threshold():
    gate = evaluate_test_gate(
        result_json={"total": 12, "passed": 12, "failed": 0, "coverage": 0.6},
        coverage_threshold=0.8,
    )
    assert gate["verdict"] == "FAIL"
    assert any("覆盖率" in r for r in gate["reasons"])


def test_scan_store_isolated():
    # 内存 store 不应在两次扫描间泄漏状态（start 即用内存 dict）
    SCAN_STORE.clear()
    r = run_code_scan(repo="org/repo")
    assert len(SCAN_STORE) == 0  # run_code_scan 不写 store（由服务层 start_scan 写）
    assert r.integrity == "pass"
