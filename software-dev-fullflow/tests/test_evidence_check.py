"""批次1 · 证据预检（Evidence Check）单元测试。

覆盖验收前对「被引用的证据」做确定性预检的契约（ARIS evidence_check 移植）：
  - path_missing：引用的源文件不存在
  - value_not_found：文件存在但值不在其中
  - verified：数字（整数/小数/千分位/科学计数/尾随%）与普通字符串命中
  - 数字 0 正常检查（value is None 才 unparseable，0 不跳过）
  - glob 源（results/*.json）命中
  - 复合构造 fail-closed：日期/版本/时间戳不误判 verified
  - check_batch 的 summary 统计
  - main() CLI：--value/--source 与 --batch 退出码
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from loop.evidence_check import check_claim, check_batch, main


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    d = tmp_path / "proj"
    d.mkdir()
    (d / "results").mkdir()
    (d / "results" / "eval.json").write_text(
        '{"pass_rate": 73.2, "total": 1000, "errors": 0, '
        '"note": "SOTA on COCO achieved at 95", "sci": 1.5e3}',
        encoding="utf-8",
    )
    return d


# ── 1. path_missing ──────────────────────────────────────────────────────────
def test_path_missing(workdir: Path):
    res = check_claim("73.2", "results/missing.json", str(workdir))
    assert res["status"] == "path_missing"
    # glob 一个也不存在 → 同样 path_missing
    assert check_claim("73.2", "nope/*.json", str(workdir))["status"] == "path_missing"


# ── 2. value_not_found ──────────────────────────────────────────────────────
def test_value_not_found(workdir: Path):
    res = check_claim("42", "results/eval.json", str(workdir))
    assert res["status"] == "value_not_found"


# ── 3. verified：数字与字符串 ───────────────────────────────────────────────
@pytest.mark.parametrize(
    "value",
    [
        "73.2",      # 小数
        "1000",      # 整数（源里以 1,000 千分位形式出现）
        "1.5e3",     # 科学计数
        "SOTA on COCO",  # 普通字符串
    ],
)
def test_verified_values(workdir: Path, value: str):
    res = check_claim(value, "results/eval.json", str(workdir))
    assert res["status"] == "verified", res


def test_verified_trailing_percent(workdir: Path):
    # 源里没有 % 形式的数字；构造一个带 % 的临时文件验证 % 一致性与命中
    f = workdir / "pct.txt"
    f.write_text("accuracy: 73.2%", encoding="utf-8")
    assert check_claim("73.2%", "pct.txt", str(workdir))["status"] == "verified"
    # % 标志不一致 → fail-closed（73.2 不匹配 73.2%）
    assert check_claim("73.2", "pct.txt", str(workdir))["status"] == "value_not_found"


# ── 4. 数字 0 正常检查（0 不是 falsy）───────────────────────────────────────
def test_zero_is_checked(workdir: Path):
    assert check_claim("0", "results/eval.json", str(workdir))["status"] == "verified"


def test_batch_unparseable_vs_zero(workdir: Path):
    # value is None → unparseable；value 是 "0" → 正常检查
    claims = [
        {"id": "a", "value": None, "source": "results/eval.json"},
        {"id": "b", "value": "0", "source": "results/eval.json"},
        {"id": "c", "value": "", "source": "results/eval.json"},
        {"id": "d", "value": "73.2", "source": None},
    ]
    out = check_batch(claims, str(workdir))
    by_id = {r["id"]: r["status"] for r in out["results"]}
    assert by_id == {"a": "unparseable", "b": "verified", "c": "unparseable", "d": "unparseable"}


# ── 5. glob 源命中 ──────────────────────────────────────────────────────────
def test_glob_source(workdir: Path):
    (workdir / "results" / "a.json").write_text('{"score": 88}', encoding="utf-8")
    (workdir / "results" / "b.json").write_text('{"score": 99}', encoding="utf-8")
    res = check_claim("99", "results/*.json", str(workdir))
    assert res["status"] == "verified"
    assert "b.json" in res["source"]


# ── 6. 复合构造 fail-closed：日期/版本/时间戳不误判 verified ───────────────
def test_compound_constructs_fail_closed(workdir: Path):
    f = workdir / "meta.txt"
    f.write_text(
        "date: 2024-05-30, version: 1.2.3, ts: 1727000000.123",
        encoding="utf-8",
    )
    # 声称的数字在复合构造里 → 不产生 false verified
    assert check_claim("2024", "meta.txt", str(workdir))["status"] == "value_not_found"
    assert check_claim("1.2", "meta.txt", str(workdir))["status"] == "value_not_found"
    assert check_claim("1727000000", "meta.txt", str(workdir))["status"] == "value_not_found"
    # 完整字面量命中仍应 verified（整串是日期时按字符串处理）
    assert check_claim("2024-05-30", "meta.txt", str(workdir))["status"] == "verified"


# ── 7. check_batch summary 统计 ─────────────────────────────────────────────
def test_check_batch_summary(workdir: Path):
    claims = [
        {"id": "ok", "value": "73.2", "source": "results/eval.json"},   # verified
        {"id": "nf", "value": "999", "source": "results/eval.json"},    # value_not_found
        {"id": "pm", "value": "1", "source": "missing.json"},           # path_missing
        {"id": "un", "value": None, "source": "x.json"},                # unparseable
    ]
    out = check_batch(claims, str(workdir))
    assert out["summary"] == {
        "verified": 1,
        "value_not_found": 1,
        "path_missing": 1,
        "unparseable": 1,
    }


# ── 8. main() CLI：退出码 ───────────────────────────────────────────────────
def test_main_cli_verified(workdir: Path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["evidence_check", str(workdir),
                                      "--value", "73.2", "--source", "results/eval.json"])
    assert main() == 0


def test_main_cli_fail(workdir: Path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["evidence_check", str(workdir),
                                      "--value", "42", "--source", "results/eval.json"])
    assert main() == 1


def test_main_batch_exit_codes(workdir: Path, monkeypatch):
    good = workdir / "good.json"
    good.write_text(json.dumps([{"value": "73.2", "source": "results/eval.json"}]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["evidence_check", str(workdir), "--batch", str(good)])
    assert main() == 0

    bad = workdir / "bad.json"
    bad.write_text(
        json.dumps([
            {"value": "73.2", "source": "results/eval.json"},
            {"value": "42", "source": "results/eval.json"},
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["evidence_check", str(workdir), "--batch", str(bad)])
    assert main() == 1
