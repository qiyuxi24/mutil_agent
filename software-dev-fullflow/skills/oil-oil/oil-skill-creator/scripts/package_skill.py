#!/usr/bin/env python3
"""校验并创建能够重复生成的 .skill 归档。"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
import zipfile
from pathlib import Path

try:
    from .validate_skill import audit_skill, parse_frontmatter
except ImportError:  # 直接运行脚本时使用同目录导入。
    from validate_skill import audit_skill, parse_frontmatter


EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist"}
EXCLUDED_FILES = {".DS_Store"}
EXCLUDED_GLOBS = {"*.pyc", "*.pyo", "*.tmp", "*.log"}
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _is_excluded(relative: Path, include_evals: bool) -> bool:
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True
    if not include_evals and relative.parts and relative.parts[0] == "evals":
        return True
    if relative.name in EXCLUDED_FILES:
        return True
    return any(fnmatch.fnmatch(relative.name, pattern) for pattern in EXCLUDED_GLOBS)


def _skill_name(skill_path: Path) -> str:
    raw = (skill_path / "SKILL.md").read_text(encoding="utf-8")
    frontmatter, _ = parse_frontmatter(raw)
    return frontmatter["name"]


def package_skill(
    skill_path: str | Path,
    output_dir: str | Path | None = None,
    public: bool = False,
    strict: bool = False,
    weak_model: bool = False,
    universal: bool = False,
    include_evals: bool = False,
    replace: bool = False,
) -> tuple[Path, str, list[str]]:
    path = Path(skill_path).expanduser().resolve()
    report = audit_skill(
        path,
        public=public,
        weak_model=weak_model,
        universal=universal,
    )
    if not report.passed(strict):
        raise ValueError(
            f"校验失败：{len(report.errors)} 个错误，{len(report.warnings)} 个警告"
        )

    name = _skill_name(path)
    destination = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else path.parent / "dist"
    )
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{name}.skill"
    if archive.exists() and not replace:
        raise FileExistsError(f"目标包已存在，拒绝覆盖：{archive}")
    if archive.exists():
        archive.unlink()

    files: list[Path] = []
    for item in sorted(path.rglob("*"), key=lambda value: value.as_posix()):
        if item.is_symlink():
            raise ValueError(f"发布包不接受符号链接：{item}")
        if not item.is_file():
            continue
        relative = item.relative_to(path)
        if not _is_excluded(relative, include_evals):
            files.append(item)

    added: list[str] = []
    with zipfile.ZipFile(
        archive, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as bundle:
        for item in files:
            relative = item.relative_to(path)
            archive_name = (Path(name) / relative).as_posix()
            info = zipfile.ZipInfo(archive_name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            executable = item.suffix.lower() in {".py", ".sh", ".ps1"}
            permissions = 0o755 if executable else 0o644
            info.external_attr = permissions << 16
            bundle.writestr(info, item.read_bytes())
            added.append(archive_name)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, digest, added


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校验并打包；相同文件会生成相同的 .skill 包")
    parser.add_argument("skill_path", help="Skill 目录")
    parser.add_argument("--output-dir", help="输出目录，默认是 Skill 同级 dist/")
    parser.add_argument("--public", action="store_true", help="执行公开 README 检查")
    parser.add_argument("--strict", action="store_true", help="warning 也阻止打包")
    parser.add_argument(
        "--weak-model",
        action="store_true",
        help="使用面向较弱模型的严格结构门槛",
    )
    parser.add_argument(
        "--universal",
        action="store_true",
        help="打包前拒绝在通用流程中写死具体宿主品牌",
    )
    parser.add_argument("--include-evals", action="store_true", help="将 evals/ 放入包中")
    parser.add_argument("--replace", action="store_true", help="明确覆盖已有同名包")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        archive, digest, added = package_skill(
            args.skill_path,
            output_dir=args.output_dir,
            public=args.public,
            strict=args.strict,
            weak_model=args.weak_model,
            universal=args.universal,
            include_evals=args.include_evals,
            replace=args.replace,
        )
    except (ValueError, FileExistsError, KeyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = {
        "archive": str(archive),
        "sha256": digest,
        "files": added,
    }
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"已创建：{archive}")
        print(f"SHA-256：{digest}")
        print(f"文件数：{len(added)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
