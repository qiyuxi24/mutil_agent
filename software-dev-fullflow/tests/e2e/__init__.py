"""E2E P0 端到端测试套件。

覆盖：
  - Web Dashboard API 契约测试（Starlette TestClient）
  - CLI run.py 管道端到端测试（subprocess）
  - Web Dashboard 浏览器测试（Playwright，可选）

运行方式（在 software-dev-fullflow 根目录）：
    # 全部 E2E 测试
    python -m pytest tests/e2e/ -v

    # 仅 API E2E（不依赖浏览器）
    python -m pytest tests/e2e/test_api_e2e.py -v

    # 仅 CLI 管道 E2E
    python -m pytest tests/e2e/test_cli_pipeline_e2e.py -v

    # 仅浏览器 E2E（需先 playwright install chromium）
    python -m pytest tests/e2e/test_web_browser_e2e.py -v
"""