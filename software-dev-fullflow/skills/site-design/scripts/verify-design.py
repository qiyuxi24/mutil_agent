"""verify-design.py — 校验 site-design 产出的 design.md 是否覆盖必要字段。

用法:
    python verify-design.py <design.md 路径>
退出码:
    0 = 通过（页面清单 + 接口/数据 + 启动方式齐备）
    1 = 失败（缺失必要字段）

用途: Architect 产出 design.md 后自检，或 Manager/Tester 校验设计契约完整性。
"""
import sys
import json
import re
from pathlib import Path


REQUIRED_SECTIONS = {
    "pages": ["页面", "page", "index", "目录"],
    "apis": ["接口", "api", "POST", "GET", "路由"],
    "data": ["数据", "data", "字段", "model", "存储"],
    "stack": ["技术栈", "stack", "python", "node", "框架"],
    "run": ["启动", "run", "端口", "port", "命令"],
}


def verify(design_path: str) -> tuple[bool, list[str]]:
    """返回 (是否通过, 缺失项列表)。"""
    path = Path(design_path)
    if not path.exists():
        return False, [f"design.md 不存在: {design_path}"]

    text = path.read_text(encoding="utf-8", errors="replace").lower()
    missing = []
    for section, keywords in REQUIRED_SECTIONS.items():
        found = any(kw.lower() in text for kw in keywords)
        if not found:
            missing.append(section)
    return (not missing), missing


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python verify-design.py <design.md 路径>")
        return 2
    ok, missing = verify(sys.argv[1])
    if ok:
        print("✓ design.md 设计契约完整：页面 + 接口 + 数据 + 技术栈 + 启动方式")
        return 0
    print(f"✘ design.md 缺失必要章节: {missing}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
