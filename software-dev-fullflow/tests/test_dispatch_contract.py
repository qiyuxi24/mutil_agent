# -*- coding: utf-8 -*-
"""dispatch-contract Skill 的独立测试（Coordinator 协同路由员）。

覆盖（对应 skills/dispatch-contract/ 的声明式机制）：
  1. 派发哨兵 fail-closed：缺 outcome/checks/scope/stop_when/returns → BLOCKED
  2. 路由校验：target 不在名册 → BLOCKED；role 与 target 错配 → BLOCKED
  3. 完整派发包 → PASS
  4. 独立复审包协议：缺四要素任一 → REJECTED；齐全 → ACCEPTED
  5. 角色-模型映射表自洽：WORKER_TO_ROLE 反查一致
  6. CLI 冒烟：role-map / schema / template-brief 可执行

去耦合承诺：本模块自包含，仅导入 dispatch_cli.py，不依赖项目内部模块；
不改变现有 Worker 行为与状态机。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "dispatch-contract"
SCRIPT = SKILL_DIR / "scripts" / "dispatch_cli.py"
sys.path.insert(0, str(SCRIPT.parent))

from dispatch_cli import (  # noqa: E402
    BRIEF_FIELDS,
    REVIEW_FIELDS,
    ROLE_MAP,
    WORKER_ROSTER,
    WORKER_TO_ROLE,
    build_brief,
    validate_brief,
    validate_review,
)

GOOD_BRIEF = {
    "version": "1.0",
    "outcome": "修复登录接口空用户名返回 500，pytest 全绿",
    "benefit": "Backend 持有鉴权代码所有权与开发日志",
    "sources": ["logs/login/2026-08-31.log", "src/api/login.py"],
    "scope": "仅后端鉴权逻辑，不动前端与数据库表结构",
    "checks": ["pytest tests/test_login.py -q"],
    "stop_when": "测试通过或 3 轮尝试后仍未通过",
    "returns": "shared/tasks/{id}/fix/patch.diff + brief.md",
    "target": "backend",
    "role": "executor",
}

GOOD_REVIEW = {
    "risk": "空用户名绕过校验直接进数据库查询",
    "evidence": "src/api/login.py:42 未判空；复现日志 logs/login/500.txt",
    "passed_checks": ["pytest tests/test_login.py 8 passed"],
    "stop_when": "定位到证据可复现，或 2 轮深挖后仍无结论",
}


# ---------------------------------------------------------------- #
# 1. 派发哨兵 fail-closed
# ---------------------------------------------------------------- #

def test_brief_full_passes():
    result = validate_brief(dict(GOOD_BRIEF))
    assert result["ok"] is True
    assert result["verdict"] == "PASS"
    assert result["blocks"] == []


@pytest.mark.parametrize(
    "field",
    ["outcome", "checks", "scope", "stop_when", "returns"],
)
def test_brief_missing_required_blocked(field):
    brief = dict(GOOD_BRIEF)
    brief[field] = "" if field != "checks" else []
    result = validate_brief(brief)
    assert result["ok"] is False
    assert result["verdict"] == "BLOCKED"
    assert any(c.startswith("BLOCKED") for c in result["blocks"])


def test_brief_empty_checks_blocked():
    """无验收标准即拒（fail-closed 核心）。"""
    brief = dict(GOOD_BRIEF)
    brief["checks"] = []
    result = validate_brief(brief)
    assert result["ok"] is False
    assert "BLOCKED-03" in result["blocks"]


def test_brief_unknown_target_blocked():
    brief = dict(GOOD_BRIEF)
    brief["target"] = "nobody"
    result = validate_brief(brief)
    assert result["ok"] is False
    assert "BLOCKED-06" in result["blocks"]


def test_brief_role_mismatch_blocked():
    """Reviewer 收到写代码派发 → BLOCKED-07（裁判不写被评审的代码）。"""
    brief = dict(GOOD_BRIEF)
    brief["target"] = "tester"
    brief["role"] = "executor"
    result = validate_brief(brief)
    assert result["ok"] is False
    assert "BLOCKED-07" in result["blocks"]


def test_brief_missing_version_blocked():
    brief = dict(GOOD_BRIEF)
    brief["version"] = ""
    result = validate_brief(brief)
    assert result["ok"] is False
    assert "BLOCKED-01" in result["blocks"]


# ---------------------------------------------------------------- #
# 2. 软性提示（不阻塞）
# ---------------------------------------------------------------- #

def test_brief_warns_do_not_block():
    brief = dict(GOOD_BRIEF)
    brief["benefit"] = ""
    brief["sources"] = []
    result = validate_brief(brief)
    assert result["ok"] is True
    assert "WARN-01" in result["warns"]
    assert "WARN-03" in result["warns"]


# ---------------------------------------------------------------- #
# 3. 独立复审包协议
# ---------------------------------------------------------------- #

def test_review_full_accepted():
    result = validate_review(dict(GOOD_REVIEW))
    assert result["ok"] is True
    assert result["verdict"] == "ACCEPTED"


@pytest.mark.parametrize("field", ["risk", "evidence", "passed_checks", "stop_when"])
def test_review_missing_rejected(field):
    review = dict(GOOD_REVIEW)
    review[field] = "" if field != "passed_checks" else []
    result = validate_review(review)
    assert result["ok"] is False
    assert result["verdict"] == "REJECTED"
    assert result["missing"] == [field]


def test_review_no_evidence_rejected():
    """无证据的复审不成立（REVIEW-02）。"""
    review = dict(GOOD_REVIEW)
    review["evidence"] = ""
    result = validate_review(review)
    assert result["ok"] is False
    assert "REVIEW-02" in result["rejected"]


# ---------------------------------------------------------------- #
# 4. 角色-模型映射自洽
# ---------------------------------------------------------------- #

def test_role_map_consistency():
    for role, cfg in ROLE_MAP.items():
        for worker in cfg["workers"]:
            assert WORKER_TO_ROLE[worker] == role
            assert worker in WORKER_ROSTER


def test_roster_has_11_workers():
    assert len(WORKER_ROSTER) == 11
    assert "coordinator" in WORKER_ROSTER


def test_brief_fields_schema_matches_docs():
    """七要素 schema：必填字段与 references 文档一致（防漂移）。"""
    required = [f for f, m in BRIEF_FIELDS.items() if m["required"]]
    assert set(required) == {
        "version", "outcome", "scope", "checks", "stop_when", "returns", "target", "role",
    }
    assert set(REVIEW_FIELDS) == {"risk", "evidence", "passed_checks", "stop_when"}


# ---------------------------------------------------------------- #
# 5. CLI 冒烟
# ---------------------------------------------------------------- #

def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cli_role_map(tmp_path):
    proc = _run_cli("role-map")
    assert proc.returncode == 0
    assert "coordinator" in proc.stdout


def test_cli_schema():
    proc = _run_cli("schema")
    assert proc.returncode == 0
    assert "outcome" in proc.stdout and "evidence" in proc.stdout


def test_cli_validate_brief_blocked(tmp_path):
    brief = dict(GOOD_BRIEF)
    brief["checks"] = []
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    proc = _run_cli("validate-brief", str(p))
    assert proc.returncode == 2
    assert "BLOCKED" in proc.stdout


def test_cli_validate_brief_pass(tmp_path):
    p = tmp_path / "good.json"
    p.write_text(json.dumps({"brief": GOOD_BRIEF}, ensure_ascii=False), encoding="utf-8")
    proc = _run_cli("validate-brief", str(p))
    assert proc.returncode == 0
    assert "PASS" in proc.stdout


def test_cli_template_brief(tmp_path):
    proc = _run_cli(
        "template-brief",
        "--outcome", "X", "--target", "backend", "--role", "executor",
        "--scope", "Y", "--checks", '["pytest tests -q"]',
        "--stop-when", "Z", "--returns", "R",
    )
    assert proc.returncode == 0
    assert "派发包" in proc.stdout


def test_cli_validate_review_rejected(tmp_path):
    p = tmp_path / "rev.json"
    p.write_text(json.dumps({"risk": "x"}, ensure_ascii=False), encoding="utf-8")
    proc = _run_cli("validate-review", str(p))
    assert proc.returncode == 2
    assert "REJECTED" in proc.stdout


def test_skill_smoke():
    """Skill 目录关键文件存在（防误删）。"""
    for name in [
        "SKILL.md",
        "scripts/dispatch_cli.py",
        "references/DISPATCH-BRIEF-SCHEMA.md",
        "references/ROLE-MODEL-MAP.md",
        "references/SENTINEL-RULES.md",
        "references/REVIEW-PACKAGE.md",
        "references/ADAPTATION-NOTES.md",
    ]:
        assert (SKILL_DIR / name).exists(), f"missing {name}"
