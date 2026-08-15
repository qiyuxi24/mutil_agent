"""pytest 共享配置：确保 `src/` 在 sys.path，使测试可 `from loop.xxx import ...`。

运行方式（在 software-dev-fullflow 根目录）：
    python -m pytest tests/ -v
"""

import sys
from pathlib import Path

# 把 src/ 加入 sys.path（loop 包根目录）
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
