#!/usr/bin/env python3
"""读取当前 description，固定划分训练集和保留集，并计算触发结果。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    from .evaluation_common import load_json
    from .validate_skill import parse_frontmatter
except ImportError:
    from evaluation_common import load_json
    from validate_skill import parse_frontmatter


def _skill_identity(skill_path: str | Path) -> tuple[str, str]:
    root = Path(skill_path).expanduser().resolve()
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise ValueError(f"目标目录缺少 SKILL.md：{root}")
    frontmatter, _ = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
    name = frontmatter.get("name", "").strip()
    description = frontmatter.get("description", "").strip()
    if not name or not description:
        raise ValueError("SKILL.md 缺少 name 或 description")
    return name, description


def _cases_by_id(data: object, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise ValueError(f"{label}.cases 必须是数组")
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(data["cases"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{label}.cases[{index}] 必须是对象")
        case_id = str(item.get("id", "")).strip()
        if not case_id or case_id in result:
            raise ValueError(f"{label}.cases[{index}].id 缺失或重复")
        result[case_id] = item
    return result


def _trials(item: dict[str, Any], case_id: str, strict: bool) -> list[bool]:
    if isinstance(item.get("triggered"), bool):
        if strict:
            raise ValueError(f"严格模式要求 {case_id} 提供至少 3 次奇数 trials")
        return [item["triggered"]]
    trials = item.get("trials")
    if not isinstance(trials, list) or not trials or not all(
        isinstance(value, bool) for value in trials
    ):
        raise ValueError(f"结果 {case_id} 必须包含 triggered 布尔值或 trials 布尔数组")
    if strict and (len(trials) < 3 or len(trials) % 2 == 0):
        raise ValueError(f"严格模式要求 {case_id} 提供至少 3 次奇数 trials")
    return trials


def _eval_hash(cases: dict[str, dict[str, Any]]) -> str:
    canonical = [
        {
            "id": case_id,
            "query": item["query"],
            "should_trigger": item["should_trigger"],
        }
        for case_id, item in sorted(cases.items())
    ]
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _split_ids(
    cases: dict[str, dict[str, Any]], skill_name: str
) -> dict[str, str]:
    split: dict[str, str] = {}
    for expected in (True, False):
        selected = [
            case_id
            for case_id, item in cases.items()
            if item["should_trigger"] is expected
        ]
        selected.sort(
            key=lambda case_id: hashlib.sha256(
                f"{skill_name}:{case_id}".encode("utf-8")
            ).hexdigest()
        )
        holdout_count = max(1, (len(selected) * 4 + 9) // 10)
        holdout = set(selected[-holdout_count:])
        for case_id in selected:
            split[case_id] = "holdout" if case_id in holdout else "train"
    return split


def _metrics(records: list[dict[str, Any]]) -> dict[str, int | float]:
    tp = tn = fp = fn = 0
    stability_values: list[float] = []
    for item in records:
        expected = item["should_trigger"]
        actual = item["triggered"]
        stability_values.append(float(item["stability"]))
        if expected and actual:
            tp += 1
        elif not expected and not actual:
            tn += 1
        elif not expected and actual:
            fp += 1
        else:
            fn += 1
    total = len(records)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    return {
        "cases": total,
        "accuracy": round((tp + tn) / total, 4) if total else 0.0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "specificity": round(specificity, 4),
        "false_positive_rate": round(1 - specificity, 4),
        "stability": round(sum(stability_values) / total, 4) if total else 0.0,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def _compare_holdout(
    candidate: dict[str, Any], baseline_path: Path, eval_hash: str
) -> dict[str, Any]:
    baseline = load_json(baseline_path)
    if not isinstance(baseline, dict):
        raise ValueError("baseline report 顶层必须是对象")
    if baseline.get("phase") != "select":
        raise ValueError("基线报告必须由 select 阶段生成")
    if baseline.get("eval_set_sha256") != eval_hash:
        raise ValueError("候选版本与基线使用的触发测试集不一致")
    baseline_summary = baseline.get("summary", {}).get("holdout")
    candidate_summary = candidate["summary"]["holdout"]
    if not isinstance(baseline_summary, dict):
        raise ValueError("基线报告缺少保留集汇总")
    deltas = {
        metric: round(
            float(candidate_summary[metric]) - float(baseline_summary[metric]), 4
        )
        for metric in ("accuracy", "precision", "recall", "specificity", "stability")
    }
    regressions = [
        metric for metric in ("recall", "specificity") if deltas[metric] < 0
    ]
    recommended = deltas["accuracy"] > 0 and not regressions
    if recommended:
        decision = "holdout-improved"
    elif deltas["accuracy"] > 0:
        decision = "holdout-tradeoff"
    else:
        decision = "no-holdout-improvement"
    return {
        "baseline_description_sha256": baseline.get("description_sha256"),
        "holdout_delta": deltas,
        "regressions": regressions,
        "recommended": recommended,
        "decision": decision,
    }


def score_triggers(
    eval_set_path: str | Path,
    results_path: str | Path,
    skill_path: str | Path,
    strict: bool = False,
    baseline_report: str | Path | None = None,
    phase: str = "train",
) -> dict[str, Any]:
    eval_path = Path(eval_set_path).expanduser().resolve()
    result_path = Path(results_path).expanduser().resolve()
    eval_data = load_json(eval_path)
    result_data = load_json(result_path)
    eval_cases = _cases_by_id(eval_data, "eval_set")
    result_cases = _cases_by_id(result_data, "results")
    if phase not in {"train", "select"}:
        raise ValueError("phase 必须是 train 或 select")
    if phase == "train" and baseline_report is not None:
        raise ValueError("train 阶段不能读取基线报告")
    if set(eval_cases) != set(result_cases):
        missing = sorted(set(eval_cases) - set(result_cases))
        extra = sorted(set(result_cases) - set(eval_cases))
        raise ValueError(f"结果 ID 不匹配；缺少 {missing}，多出 {extra}")

    skill_name, description = _skill_identity(skill_path)
    if not isinstance(eval_data, dict) or eval_data.get("skill_name") != skill_name:
        raise ValueError("触发评测集的 skill_name 与目标 Skill 不一致")
    if not isinstance(result_data, dict) or result_data.get("description") != description:
        raise ValueError("结果中的 description 与目标 SKILL.md frontmatter 不一致")
    if result_data.get("skill_name") not in {None, skill_name}:
        raise ValueError("结果中的 skill_name 与目标 Skill 不一致")

    positives = negatives = 0
    for case_id, item in eval_cases.items():
        query = item.get("query")
        expected = item.get("should_trigger")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"eval_set {case_id}.query 必须是非空字符串")
        if not isinstance(expected, bool):
            raise ValueError(f"eval_set {case_id}.should_trigger 必须是布尔值")
        positives += int(expected)
        negatives += int(not expected)
    minimum = 8 if strict else 1
    if positives < minimum or negatives < minimum:
        raise ValueError(
            f"正反测试数量不足；当前 {positives}/{negatives}，要求各至少 {minimum}"
        )

    splits = _split_ids(eval_cases, skill_name)
    cases: list[dict[str, Any]] = []
    for case_id, item in sorted(eval_cases.items()):
        trials = _trials(result_cases[case_id], case_id, strict)
        rate = sum(trials) / len(trials)
        actual = rate >= 0.5
        cases.append(
            {
                "id": case_id,
                "split": splits[case_id],
                "should_trigger": item["should_trigger"],
                "trigger_rate": round(rate, 4),
                "triggered": actual,
                "passed": item["should_trigger"] == actual,
                "stability": round(max(rate, 1 - rate), 4),
            }
        )

    selected_split = "train" if phase == "train" else "holdout"
    selected_cases = [item for item in cases if item["split"] == selected_split]
    visible_cases = [
        {key: value for key, value in item.items() if key != "split"}
        for item in selected_cases
    ]
    summary_key = "train" if phase == "train" else "holdout"
    report: dict[str, Any] = {
        "schema_version": 2,
        "phase": phase,
        "skill_name": skill_name,
        "description": description,
        "description_sha256": hashlib.sha256(description.encode("utf-8")).hexdigest(),
        "eval_set_sha256": _eval_hash(eval_cases),
        "summary": {summary_key: _metrics(selected_cases)},
        "cases": visible_cases,
    }
    if baseline_report is not None:
        report["selection"] = _compare_holdout(
            report, Path(baseline_report).expanduser().resolve(), report["eval_set_sha256"]
        )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="测量并比较 Skill 触发说明的准确性")
    parser.add_argument("eval_set", help="固定触发测试集 JSON")
    parser.add_argument("results", help="当前 description 的实际触发结果 JSON")
    parser.add_argument("--skill-path", required=True, help="本轮实际加载的 Skill 目录")
    parser.add_argument(
        "--phase",
        choices=("train", "select"),
        required=True,
        help="train 只显示训练结果；select 才读取保留集并选择版本",
    )
    parser.add_argument("--strict", action="store_true", help="要求正反各 8 条且每条至少运行 3 次")
    parser.add_argument("--baseline-report", help="基线评分报告；选择版本时只使用保留集")
    parser.add_argument("--output", help="将完整报告写入 JSON 文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = score_triggers(
            args.eval_set,
            args.results,
            args.skill_path,
            strict=args.strict,
            baseline_report=args.baseline_report,
            phase=args.phase,
        )
        if args.output:
            output = Path(args.output).expanduser().resolve()
            if output.exists():
                raise FileExistsError(f"输出已存在，拒绝覆盖：{output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    except (ValueError, FileExistsError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
