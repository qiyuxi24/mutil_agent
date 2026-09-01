# -*- coding: utf-8 -*-
"""
email_service.py —— 团队「邮箱收信」工具链（IMAP 只读：未读 / 搜索 / 读信）

让 AgentTeams 的 Worker（隔离容器）通过 MCP 读取团队邮箱邮件：
  - list_unread   列出某文件夹的未读邮件（主题 / 发件人 / 日期 / uid）
  - search_emails 按关键词搜索邮件（优先 IMAP 搜索，失败自动降级本地过滤）
  - read_email    按 uid 读取单封邮件正文（纯文本优先，HTML 自动剥标签）
  - email_health  检查服务配置健康（不连邮箱）

接入方式：本服务原生就是 MCP Streamable HTTP Server → 走 proxy 模式（对齐 host-tools）
  register-mcp.ps1 -Name email -Mode proxy `
    -Url http://host.docker.internal:9400/mcp -Transport http `
    -Header "Authorization: Bearer <QQ邮箱授权码>"

凭据设计（安全边界，Worker 永远看不到真实凭据）：
  - 授权码：网关在调用时通过 `Authorization: Bearer <accessToken>` 注入
    （register-mcp.ps1 -Header 固定头；服务端解析 Bearer 作为 IMAP 授权码）
  - 账号：服务端环境变量 EMAIL_ACCOUNT；也支持请求头 X-Email-Account 覆盖（多账号场景）
  - 兜底：环境变量 EMAIL_AUTH_CODE 也可直接作为授权码（未配 header 时）

端点（对齐 host-tools 协议）：
  GET  /health                存活探针
  GET  /mcp                   MCP Streamable HTTP 会话初始化
  POST /mcp                   MCP JSON-RPC 消息处理（tools/list, tools/call）
  DELETE /mcp                 会话终止
  POST /v1/email/unread       REST 便捷端点（调试/自检，body: {"limit":10,"folder":"INBOX"}）
  POST /v1/email/search       REST 便捷端点（body: {"query":"xx","folder":"INBOX","limit":20})
  POST /v1/email/read         REST 便捷端点（body: {"uid":123,"folder":"INBOX","max_chars":5000})

运行（在宿主机 Windows，software-dev-fullflow 目录）：
  cd software-dev-fullflow
  python -m src.agentteams.toolchains.email_service        # 默认 0.0.0.0:9400

环境变量：
  EMAIL_SERVICE_PORT   服务端口（默认 9400）
  EMAIL_IMAP_HOST      IMAP 服务器（默认 imap.qq.com）
  EMAIL_IMAP_PORT      IMAP SSL 端口（默认 993）
  EMAIL_ACCOUNT        邮箱账号（必填，如 xxxx@qq.com）
  EMAIL_AUTH_CODE      邮箱授权码（兜底；推荐走网关 header 注入）
  EMAIL_IMAP_TIMEOUT   IMAP 连接超时秒数（默认 15）

注意：QQ 邮箱需先在网页端开启 IMAP 服务并生成「授权码」，登录密码不是授权码。
"""

from __future__ import annotations

import contextvars
import email
import email.policy
import imaplib
import os
import re
import socket
from email.header import decode_header
from email.message import Message
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .mcp_adapter import McpAdapter

# 统一用 default policy 解析邮件（中文/charset/CTE 自动解码，兼容 compat32 兜底）
_EMAIL_POLICY = email.policy.default

# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #

PORT = int(os.environ.get("EMAIL_SERVICE_PORT", "9400"))
IMAP_HOST = os.environ.get("EMAIL_IMAP_HOST", "imap.qq.com")
IMAP_PORT = int(os.environ.get("EMAIL_IMAP_PORT", "993"))
DEFAULT_ACCOUNT = os.environ.get("EMAIL_ACCOUNT", "")
DEFAULT_AUTH_CODE = os.environ.get("EMAIL_AUTH_CODE", "")
IMAP_TIMEOUT = float(os.environ.get("EMAIL_IMAP_TIMEOUT", "15"))

# 请求级凭据（MCP 适配层无状态，用 contextvar 把网关注入的 header 传给工具函数）
_ctx_account: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "email_account", default=None)
_ctx_auth: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "email_auth", default=None)


# --------------------------------------------------------------------------- #
# 凭据解析
# --------------------------------------------------------------------------- #

def resolve_credentials(account: str | None = None, auth_code: str | None = None) -> tuple[str, str]:
    """按优先级合并凭据：显式传参 > 请求头(contextvar) > 环境变量（实时读取）。"""
    acc = account or _ctx_account.get() or os.environ.get("EMAIL_ACCOUNT", "") or DEFAULT_ACCOUNT
    code = auth_code or _ctx_auth.get() or os.environ.get("EMAIL_AUTH_CODE", "") or DEFAULT_AUTH_CODE
    if not acc or not code:
        raise ValueError(
            "缺少邮箱凭据：请配置 EMAIL_ACCOUNT/EMAIL_AUTH_CODE 环境变量，"
            "或在网关注册时用 -Header 'Authorization: Bearer <授权码>' 注入"
        )
    return acc, code


def parse_bearer(authorization: str | None) -> str | None:
    """从 'Bearer <token>' 里取 token；没有则返回 None。"""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].strip().lower() == "bearer":
        return parts[1].strip()
    # 兼容裸 token 形式
    return authorization.strip() or None


def _set_ctx_from_request(request: Request) -> None:
    """从请求头提取凭据写入 contextvar（网关注入的 Authorization / X-Email-Account）。"""
    auth = request.headers.get("Authorization")
    if auth:
        _ctx_auth.set(parse_bearer(auth))
    acc = request.headers.get("X-Email-Account")
    if acc:
        _ctx_account.set(acc.strip())


# --------------------------------------------------------------------------- #
# IMAP 连接
# --------------------------------------------------------------------------- #

def _connect(account: str, auth_code: str) -> imaplib.IMAP4_SSL:
    """建立只读 IMAP SSL 连接。"""
    socket.setdefaulttimeout(IMAP_TIMEOUT)
    conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    conn.login(account, auth_code)
    return conn


def _safe_logout(conn: imaplib.IMAP4_SSL | None) -> None:
    if conn is None:
        return
    try:
        conn.logout()
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# 邮件解析（纯函数，可单测）
# --------------------------------------------------------------------------- #

def _decode_header_value(raw: Any) -> str:
    """解码 RFC2047 头（Subject/From/Date），支持 base64 / quoted-printable / 中文。"""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        parts = decode_header(str(raw))
    except Exception:  # noqa: BLE001
        return str(raw)
    out: list[str] = []
    for text, enc in parts:
        if isinstance(text, bytes):
            encodings = [enc] if enc else []
            encodings += ["utf-8", "gb18030", "gbk", "big5"]
            for e in encodings:
                try:
                    out.append(text.decode(e))
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _decode_payload(part: Message, max_chars: int) -> str:
    """解码邮件正文 payload（兼容 bytes / str，按 charset 逐个尝试）。"""
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    if isinstance(payload, str):
        # compat32 策略下无 CTE 的 part 直接返回 str
        text = payload
    else:
        charset = part.get_content_charset() or "utf-8"
        for enc in [charset, "utf-8", "gb18030", "gbk", "big5"]:
            try:
                text = payload.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            text = payload.decode("utf-8", errors="replace")
    return text[:max_chars]


def _strip_html(html: str) -> str:
    """去掉 HTML 标签/脚本/样式，压缩空白，返回纯文本。"""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</p>|</div>|</tr>|</li>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in html.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _part_text(part: Message, max_chars: int) -> str:
    """取单个 part 的文本。

    Python 3.11 的 email 库对「无 Content-Transfer-Encoding 的中文 str payload」
    调用 get_payload(decode=True) 时会做 unicode-escape 编码，把中文变成字面
    \\uXXXX 文本。因此这里绕开该路径：
      - 无 CTE → 直接取原始 str payload（default policy 下已是正确解码的中文）
      - 有 CTE（base64/quoted-printable）→ 走 get_content() 自动 CTE+charset 解码
      - payload 为 bytes → 退到多编码硬解
    """
    cte = (part.get("content-transfer-encoding") or "").strip().lower()
    if not cte:
        payload = part.get_payload(decode=False)
        if isinstance(payload, str):
            return payload[:max_chars]
        return _decode_payload(part, max_chars)
    get_content = getattr(part, "get_content", None)
    if callable(get_content):
        try:
            return str(get_content())[:max_chars]
        except (LookupError, UnicodeDecodeError, ValueError):
            pass
    return _decode_payload(part, max_chars)


def _extract_body(msg: Message, max_chars: int) -> str:
    """提取正文：text/plain 优先，其次 text/html（剥标签）。"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return _part_text(part, max_chars)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return _strip_html(_part_text(part, max_chars))
        return ""
    if msg.get_content_type() == "text/html":
        return _strip_html(_part_text(msg, max_chars))
    return _part_text(msg, max_chars)


def _has_attachment(msg: Message) -> bool:
    for part in msg.walk():
        if part.get_content_disposition() == "attachment" or part.get_filename():
            return True
    return False


def build_imap_search(query: str, unread_only: bool) -> list[str]:
    """构建 IMAP SEARCH 键列表（纯函数）。

    - unread_only → 加 UNSEEN
    - query → 加 TEXT "xxx"（走 CHARSET UTF-8，QQ 邮箱支持）
    - 空查询 → ALL
    """
    keys: list[str] = []
    if unread_only:
        keys.append("UNSEEN")
    q = (query or "").strip()
    if q:
        escaped = q.replace("\\", "\\\\").replace('"', '\\"')
        keys.append(f'TEXT "{escaped}"')
    return keys or ["ALL"]


# --------------------------------------------------------------------------- #
# IMAP 取数
# --------------------------------------------------------------------------- #

def _fetch_summary(conn: imaplib.IMAP4_SSL, uid: int) -> dict:
    """按 uid 取邮件概要（主题/发件人/日期），失败返回 None。"""
    typ, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
    if typ != "OK" or not data or not data[0]:
        return None  # type: ignore[return-value]
    msg = email.message_from_bytes(data[0][1], policy=_EMAIL_POLICY)
    return {
        "uid": uid,
        "subject": _decode_header_value(msg.get("Subject")) or "(无主题)",
        "from": _decode_header_value(msg.get("From")),
        "date": _decode_header_value(msg.get("Date")),
    }


def _search_uids(conn: imaplib.IMAP4_SSL, keys: list[str]) -> list[int]:
    """执行 UID SEARCH（先试 CHARSET UTF-8，失败降级普通搜索）。"""
    crit = " ".join(keys)
    for attempt in (("CHARSET", "UTF-8", crit), (None, crit)):
        try:
            if attempt[0]:
                typ, data = conn.uid("SEARCH", attempt[0], attempt[1], attempt[2])
            else:
                typ, data = conn.uid("SEARCH", None, attempt[1])
        except Exception:  # noqa: BLE001
            continue
        if typ == "OK":
            break
    else:
        return []
    if not data or not data[0]:
        return []
    return [int(x) for x in data[0].split()]


def _local_filter(conn: imaplib.IMAP4_SSL, uids: list[int], query: str, limit: int) -> list[dict]:
    """降级路径：拉最近一批概要，本地关键词过滤（不依赖服务器搜索能力）。"""
    ql = query.lower()
    pool = uids[-max(limit * 5, 100):]
    matched: list[dict] = []
    for u in pool:
        item = _fetch_summary(conn, u)
        if item and (ql in item["subject"].lower() or ql in item["from"].lower()):
            matched.append(item)
    return matched[-limit:]


# --------------------------------------------------------------------------- #
# 工具实现
# --------------------------------------------------------------------------- #

def tool_list_unread(limit: int = 10, folder: str = "INBOX") -> dict:
    """列出文件夹中的未读邮件（默认收件箱，最新在前）。"""
    try:
        account, auth_code = resolve_credentials()
        limit = max(1, min(int(limit), 100))
        conn = _connect(account, auth_code)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            return {"error": f"无法打开文件夹: {folder}"}
        uids = _search_uids(conn, ["UNSEEN"])
        items: list[dict] = []
        for u in uids[-limit:]:
            item = _fetch_summary(conn, u)
            if item:
                items.append(item)
        return {
            "folder": folder,
            "unread": len(uids),
            "count": len(items),
            "items": items,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        _safe_logout(conn)


def tool_search_emails(query: str = "", folder: str = "INBOX", limit: int = 20,
                       unread_only: bool = False) -> dict:
    """按关键词搜索邮件（匹配主题/正文/发件人，走 IMAP TEXT 搜索，失败自动降级）。"""
    try:
        account, auth_code = resolve_credentials()
        limit = max(1, min(int(limit), 100))
        conn = _connect(account, auth_code)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            return {"error": f"无法打开文件夹: {folder}"}
        keys = build_imap_search(query, unread_only)
        uids = _search_uids(conn, keys)
        if query and not uids:
            # IMAP 搜索无结果或失败 → 本地降级过滤
            all_uids = _search_uids(conn, build_imap_search("", False))
            items = _local_filter(conn, all_uids, query, limit)
            return {"folder": folder, "query": query, "count": len(items),
                    "mode": "local_filter", "items": items}
        items: list[dict] = []
        for u in uids[-limit:]:
            item = _fetch_summary(conn, u)
            if item:
                items.append(item)
        return {"folder": folder, "query": query, "count": len(items),
                "mode": "imap_search", "items": items}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        _safe_logout(conn)


def tool_read_email(uid: int, folder: str = "INBOX", max_chars: int = 5000) -> dict:
    """按 uid 读取一封邮件的完整正文（纯文本优先，HTML 自动剥标签）。"""
    try:
        account, auth_code = resolve_credentials()
        max_chars = max(200, min(int(max_chars), 20000))
        conn = _connect(account, auth_code)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    try:
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            return {"error": f"无法打开文件夹: {folder}"}
        typ, data = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if typ != "OK" or not data or not data[0]:
            return {"error": f"uid={uid} 读取失败（可能已删除）"}
        msg = email.message_from_bytes(data[0][1], policy=_EMAIL_POLICY)
        return {
            "uid": uid,
            "folder": folder,
            "subject": _decode_header_value(msg.get("Subject")) or "(无主题)",
            "from": _decode_header_value(msg.get("From")),
            "to": _decode_header_value(msg.get("To")),
            "date": _decode_header_value(msg.get("Date")),
            "has_attachment": _has_attachment(msg),
            "body": _extract_body(msg, max_chars),
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        _safe_logout(conn)


def tool_email_health() -> dict:
    """检查邮箱服务配置健康（不连接邮箱服务器）。"""
    acc = _ctx_account.get() or os.environ.get("EMAIL_ACCOUNT", "") or DEFAULT_ACCOUNT
    code = _ctx_auth.get() or os.environ.get("EMAIL_AUTH_CODE", "") or DEFAULT_AUTH_CODE
    return {
        "status": "ok",
        "imap_host": IMAP_HOST,
        "imap_port": IMAP_PORT,
        "account_configured": bool(acc),
        "auth_code_configured": bool(code),
        "server_name": "email",
    }


# --------------------------------------------------------------------------- #
# FastAPI 应用
# --------------------------------------------------------------------------- #

def _register_mcp_tools(mcp: McpAdapter) -> None:
    mcp.register_tool(
        "list_unread", "列出邮箱收件箱中的未读邮件（返回主题/发件人/日期/uid）",
        {"limit": {"type": "number", "description": "最多返回条数，默认 10，最大 100"},
         "folder": {"type": "string", "description": "邮箱文件夹，默认 INBOX"}},
        [], tool_list_unread)
    mcp.register_tool(
        "search_emails", "按关键词搜索邮件（匹配主题/正文/发件人）",
        {"query": {"type": "string", "description": "搜索关键词（中英文均可）"},
         "folder": {"type": "string", "description": "邮箱文件夹，默认 INBOX"},
         "limit": {"type": "number", "description": "最多返回条数，默认 20，最大 100"},
         "unread_only": {"type": "boolean", "description": "仅搜未读，默认 false"}},
        ["query"], tool_search_emails)
    mcp.register_tool(
        "read_email", "按 uid 读取一封邮件的完整正文（纯文本优先，HTML 自动剥标签）",
        {"uid": {"type": "number", "description": "邮件 uid（来自 list_unread/search_emails）"},
         "folder": {"type": "string", "description": "邮箱文件夹，默认 INBOX"},
         "max_chars": {"type": "number", "description": "正文最大字符数，默认 5000，最大 20000"}},
        ["uid"], tool_read_email)
    mcp.register_tool(
        "email_health", "检查邮箱服务配置健康（不连接邮箱服务器）", {}, [], tool_email_health)


def build_app():
    app = FastAPI(title="AgentTeams Email Tools (邮箱收信)", version="1.0.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    mcp = McpAdapter(server_name="email", server_version="1.0.0")
    _register_mcp_tools(mcp)

    _sessions: dict[str, str] = {}

    @app.get("/mcp")
    def mcp_get():
        session_id = mcp.create_session_id()
        _sessions[session_id] = "active"
        return JSONResponse(
            content={"status": "ok", "server": "email"},
            headers={"Mcp-Session-Id": session_id},
        )

    @app.post("/mcp")
    async def mcp_post(request: Request):
        body = await request.json()
        _set_ctx_from_request(request)
        result = mcp.handle_jsonrpc(body)
        if result is None:
            return Response(status_code=202)
        return result

    @app.delete("/mcp")
    def mcp_delete():
        return Response(status_code=204)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "email", "imap_host": IMAP_HOST}

    # ---- 本机可直接调用的 REST 便捷端点（调试/自检，凭据同样走 header） ----
    @app.post("/v1/email/unread")
    async def rest_unread(request: Request, payload: dict):
        _set_ctx_from_request(request)
        return tool_list_unread(limit=int(payload.get("limit", 10)),
                                folder=payload.get("folder", "INBOX"))

    @app.post("/v1/email/search")
    async def rest_search(request: Request, payload: dict):
        _set_ctx_from_request(request)
        return tool_search_emails(
            query=payload.get("query", ""),
            folder=payload.get("folder", "INBOX"),
            limit=int(payload.get("limit", 20)),
            unread_only=bool(payload.get("unread_only", False)))

    @app.post("/v1/email/read")
    async def rest_read(request: Request, payload: dict):
        _set_ctx_from_request(request)
        return tool_read_email(uid=int(payload.get("uid", 0)),
                               folder=payload.get("folder", "INBOX"),
                               max_chars=int(payload.get("max_chars", 5000)))

    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
