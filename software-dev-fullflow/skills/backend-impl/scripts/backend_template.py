"""backend_template.py — 带 POST 接口的轻量后端模板（纯标准库，零依赖）。

Backend 角色可基于此模板按 design.md 修改，快速实现「带服务器的网站」的 POST 能力。
用 Python 标准库 http.server + JSON 文件存储，保证 tester/deployer 能真实起服务验证。

用法:
    python backend_template.py --port 8080

提供:
    GET  /            → 返回静态页 index.html（若同目录存在）或服务说明
    POST /api/submit  → 接收 {name, message} 等字段，校验 + 存储到 data.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data.json"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            index = ROOT / "index.html"
            if index.exists():
                self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            else:
                self._json(200, {"service": "backend running", "post": "/api/submit"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/api/submit":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            self._json(400, {"error": f"invalid request: {e}"})
            return

        # 字段校验（可按 design.md 扩展字段）
        name = str(payload.get("name", "")).strip()
        message = str(payload.get("message", "")).strip()
        if not name or not message:
            self._json(422, {"error": "name and message are required"})
            return

        # 数据落地（JSON 文件追加）
        records = []
        if DATA_FILE.exists():
            records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        records.append({"name": name, "message": message})
        DATA_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

        self._json(200, {"status": "ok", "received": {"name": name, "message": message}})

    def log_message(self, *args) -> None:  # 静默请求日志
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="轻量后端模板（POST /api/submit）")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    print(f"Starting backend on 0.0.0.0:{args.port} ...")
    print(f"POST /api/submit   (data -> {DATA_FILE})")
    HTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(0)
