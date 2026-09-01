"""评估脚本共用的数据格式和路径工具。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from statistics import mean, pstdev
from typing import Any


SAFE_NAME_RE = re.compile(r"[^a-z0-9]+")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 无效：{path}:{exc.lineno}:{exc.colno}") from exc


def safe_name(value: object, fallback: str) -> str:
    normalized = SAFE_NAME_RE.sub("-", str(value).strip().lower()).strip("-")
    return normalized[:80] or fallback


def validate_eval_set(
    path: Path,
    expected_skill_name: str | None = None,
    allow_empty: bool = False,
) -> dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError("evals 文件顶层必须是对象")
    skill_name = data.get("skill_name")
    if not isinstance(skill_name, str) or not skill_name.strip():
        raise ValueError("evals.skill_name 必须是非空字符串")
    if expected_skill_name and skill_name != expected_skill_name:
        raise ValueError(
            f"evals.skill_name 为 {skill_name!r}，与目标 Skill {expected_skill_name!r} 不一致"
        )
    evals = data.get("evals")
    if not isinstance(evals, list):
        raise ValueError("evals.evals 必须是数组")
    if not evals and not allow_empty:
        raise ValueError("evals.evals 必须包含至少一条测试")

    ids: set[str] = set()
    names: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(evals, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"evals[{index}] 必须是对象")
        allowed_keys = {
            "id",
            "name",
            "prompt",
            "expected_output",
            "files",
            "expectations",
        }
        unexpected = sorted(set(item) - allowed_keys)
        if unexpected:
            raise ValueError(
                f"evals[{index}] 包含不支持字段：{', '.join(unexpected)}"
            )
        eval_id = str(item.get("id", "")).strip()
        if not eval_id or eval_id in ids:
            raise ValueError(f"evals[{index}].id 缺失或重复")
        ids.add(eval_id)
        raw_name = item.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError(f"evals[{index}].name 必须是描述性名称")
        name = safe_name(raw_name, f"eval-{eval_id}")
        if name in names:
            raise ValueError(f"evals[{index}].name 规范化后重复：{name}")
        names.add(name)
        prompt = item.get("prompt")
        expected = item.get("expected_output")
        files = item.get("files", [])
        expectations = item.get("expectations", [])
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"evals[{index}].prompt 必须是非空字符串")
        if not isinstance(expected, str) or not expected.strip():
            raise ValueError(f"evals[{index}].expected_output 必须是非空字符串")
        if not isinstance(files, list) or not all(isinstance(value, str) for value in files):
            raise ValueError(f"evals[{index}].files 必须是字符串数组")
        if not isinstance(expectations, list) or not all(
            isinstance(value, str) and value.strip() for value in expectations
        ):
            raise ValueError(f"evals[{index}].expectations 必须是非空字符串数组")
        normalized.append(
            {
                "id": eval_id,
                "name": name,
                "prompt": prompt.strip(),
                "expected_output": expected.strip(),
                "files": files,
                "expectations": [value.strip() for value in expectations],
            }
        )
    return {"skill_name": skill_name, "evals": normalized}


def summarize(values: list[float | int]) -> dict[str, float | int | None]:
    if not values:
        return {"mean": None, "stddev": None, "count": 0}
    numeric = [float(value) for value in values]
    return {
        "mean": round(mean(numeric), 4),
        "stddev": round(pstdev(numeric), 4) if len(numeric) > 1 else 0.0,
        "count": len(numeric),
    }
