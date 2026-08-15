#!/usr/bin/env python3
"""verify-umodel-model.py
研发 PDCA 统一数据模型（UModel）模型包完整性自检。

校验 `src/agentteams/umodel/` 下的 `.umodel` 模型包：
  1. 每个 YAML 可解析、kind 合法（entity_set / entity_set_link / minio）
  2. entity_set：metadata.name 唯一、spec.fields 非空、有 primary_key_fields
  3. entity_set_link：src/dest 引用的 entity_set 必须存在、name 唯一
  4. storage：kind 合法、有 endpoint

用法（宿主机）：
  python scripts/verify-umodel-model.py

输出为 JSON 摘要（退出码 0=全部符合预期）。
"""
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print(json.dumps({"status": "ERROR", "reason": "PyYAML 未安装"}, ensure_ascii=False))
    print("提示: pip install pyyaml 后重试。", file=sys.stderr)
    sys.exit(2)

BASE = Path(__file__).resolve().parent.parent / "src" / "agentteams" / "umodel"
VALID_KINDS = {"entity_set", "entity_set_link", "minio"}


def load_yamls(sub: str):
    """读取子目录下所有 .yaml，返回 (path, obj) 列表。"""
    files = sorted((BASE / sub).glob("*.yaml"))
    out = []
    for f in files:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            out.append((f, {"_parse_error": str(e)}))
            continue
        out.append((f, data or {}))
    return out


def main() -> int:
    failures = []

    entity_sets = {}
    entity_files = load_yamls("entity_set")
    for path, data in entity_files:
        if "_parse_error" in data:
            failures.append(f"[parse] {path.name}: {data['_parse_error']}")
            continue
        if data.get("kind") != "entity_set":
            failures.append(f"[kind] {path.name}: 期望 entity_set, 实际 {data.get('kind')}")
            continue
        name = (data.get("metadata") or {}).get("name")
        if not name:
            failures.append(f"[name] {path.name}: metadata.name 缺失")
            continue
        if name in entity_sets:
            failures.append(f"[dup] entity_set 重名: {name} ({path.name})")
        entity_sets[name] = path
        spec = data.get("spec") or {}
        if not spec.get("fields"):
            failures.append(f"[fields] {path.name}: spec.fields 为空")
        if not spec.get("primary_key_fields"):
            failures.append(f"[pk] {path.name}: spec.primary_key_fields 缺失")

    links = load_yamls("link")
    link_names = {}
    for path, data in links:
        if "_parse_error" in data:
            failures.append(f"[parse] {path.name}: {data['_parse_error']}")
            continue
        if data.get("kind") != "entity_set_link":
            failures.append(f"[kind] {path.name}: 期望 entity_set_link, 实际 {data.get('kind')}")
            continue
        name = (data.get("metadata") or {}).get("name")
        if not name:
            failures.append(f"[name] {path.name}: metadata.name 缺失")
            continue
        if name in link_names:
            failures.append(f"[dup] link 重名: {name} ({path.name})")
        link_names[name] = path
        spec = data.get("spec") or {}
        for side in ("src", "dest"):
            ref = (spec.get(side) or {}).get("name")
            if not ref:
                failures.append(f"[ref] {path.name}: spec.{side}.name 缺失")
            elif ref not in entity_sets:
                failures.append(f"[ref] {path.name}: 引用不存在的 entity_set '{ref}'")

    storages = load_yamls("storage")
    for path, data in storages:
        if "_parse_error" in data:
            failures.append(f"[parse] {path.name}: {data['_parse_error']}")
            continue
        if data.get("kind") not in VALID_KINDS:
            failures.append(f"[kind] {path.name}: kind {data.get('kind')} 非法")
        if not (data.get("spec") or {}).get("endpoint"):
            failures.append(f"[endpoint] {path.name}: spec.endpoint 缺失")

    summary = {
        "status": "FAIL" if failures else "PASS",
        "entity_sets": len(entity_sets),
        "links": len(link_names),
        "storages": len(storages),
        "failures": failures,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
