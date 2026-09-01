"""health_check.py — 对已部署站点做健康检查（静态页 200 + POST 接口通）。

用法:
    python health_check.py --url http://localhost:8080
    python health_check.py --url http://localhost:8080 --post /api/submit

退出码:
    0 = 全部通过（GET 200 + POST 200）
    1 = 任一失败
"""
import argparse
import json
import sys
import urllib.request
import urllib.error


def http_status(method: str, url: str, body: dict | None = None, timeout: int = 5) -> int:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001 - 连接失败视作不可达
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="部署健康检查")
    parser.add_argument("--url", required=True, help="站点根地址，如 http://localhost:8080")
    parser.add_argument("--post", default="/api/submit", help="POST 接口路径")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    get_status = http_status("GET", f"{base}/")
    post_status = http_status("POST", f"{base}{args.post}", {"name": "t", "message": "health"})

    print(f"GET  {base}/              -> {get_status} (期望 200)")
    print(f"POST {base}{args.post}    -> {post_status} (期望 200)")

    ok = get_status == 200 and post_status == 200
    if ok:
        print("✓ 健康检查通过：静态页可访问 + POST 接口可达")
        return 0
    print(f"✘ 健康检查失败: GET={get_status} POST={post_status}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
