"""统一 .env 加载器（纯 stdlib，零第三方依赖）。

项目运行配置的「唯一真相源」是根目录 `.env`（模板见根目录 `.env.example`）。
本模块在入口最早处调用 `load_dotenv()`，把 `.env` 里的键值注入 `os.environ`，
使各模块既有的 `os.environ.get("XXX", 默认值)` 全部生效，无需逐个改代码。

设计原则：
  - 只做「注入」，不覆盖已存在的真实环境变量（环境变量优先级 > .env）。
  - 纯 stdlib（open + 简单解析），不引入 python-dotenv，避免新增依赖。
  - 幂等：重复调用不重复注入。

用法：
    from loop.config import load_dotenv
    load_dotenv()
"""

from __future__ import annotations

import os
from pathlib import Path

# 已注入标记（进程内幂等）
_LOADED = False


def _find_env_file() -> Path | None:
    """自下而上查找项目根目录的 .env（优先当前文件所在仓库根，可被调用方显式指定）。"""
    # 从本文件（src/loop/config.py）向上回溯到软件项目根
    for base in [Path(__file__).resolve().parent.parent.parent,
                 Path(__file__).resolve().parent.parent]:
        candidate = base / ".env"
        if candidate.is_file():
            return candidate
    return None


def _parse_dotenv(text: str) -> dict[str, str]:
    """解析 .env 文本为 dict。支持：# 注释、KEY=VALUE、引号包裹、KEY= 空值。"""
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        # 跳过空行与注释
        if not line or line.startswith("#"):
            continue
        # 只处理 KEY=VALUE 形式
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # 去除首尾配对的引号
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # 去掉行内尾注释（仅对无引号值处理；有引号保留原样）
        elif "#" in value:
            value = value.split("#", 1)[0].strip()
        result[key] = value
    return result


def load_dotenv(path: str | os.PathLike | None = None) -> bool:
    """把 .env 注入 os.environ（不覆盖已存在变量）。返回是否找到并加载了 .env。

    Args:
        path: 显式指定 .env 路径；省略则自项目根自动查找。
    """
    global _LOADED
    if _LOADED and path is None:
        return True

    env_path = Path(path).resolve() if path else _find_env_file()
    if env_path is None or not env_path.is_file():
        return False

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False

    loaded: dict[str, str] = _parse_dotenv(text)
    for key, value in loaded.items():
        # 不覆盖真实环境变量（进程注入优先级更高）
        if key not in os.environ:
            os.environ[key] = value

    _LOADED = True
    return True


def getenv(key: str, default: str = "") -> str:
    """读取配置：优先环境变量，回退默认值（等价 os.environ.get，但语义更清晰）。"""
    return os.environ.get(key, default)
