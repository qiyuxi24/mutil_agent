# -*- coding: utf-8 -*-
"""邮箱收信工具链测试（email_service）：纯函数 + FakeIMAP 模拟 + MCP 协议。

运行方式（software-dev-fullflow 根目录）：
    demo\.venv\Scripts\python.exe -m pytest tests/test_email_service.py -q
"""

import email
import email.policy
import json
import re
from email.header import Header

import pytest

from src.agentteams.toolchains import email_service
from src.agentteams.toolchains.mcp_adapter import McpAdapter

_EMAIL_POLICY = email.policy.default


# --------------------------------------------------------------------------- #
# FakeIMAP：不连真实邮箱，模拟 imaplib.IMAP4_SSL
# --------------------------------------------------------------------------- #

class FakeIMAP:
    """最小 IMAP 模拟：search 支持 UNSEEN / TEXT "xx" 过滤，fetch 返回原包。

    注意：messages/unseen 用类属性共享，因为工具每次调用会新建连接实例
    （模拟真实 IMAP 服务器是全局状态）。
    """

    messages = {}   # uid -> raw bytes（类级共享）
    unseen = set()  # uid -> 未读标记（类级共享）
    instances = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.logged_in = None
        self.folder = None
        FakeIMAP.instances.append(self)

    def login(self, account, code):
        self.logged_in = (account, code)
        return ("OK", [b"LOGIN ok"])

    def select(self, folder, readonly=True):
        self.folder = folder
        return ("OK", [1])

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            crit = ""
            for a in args:
                if isinstance(a, str):
                    crit = a
            return ("OK", [self._do_search(crit).encode()])
        if cmd == "FETCH":
            uid = int(args[0])
            raw = self.messages.get(uid)
            if raw is None:
                return ("NO", [b"not found"])
            return ("OK", [(b"%d (RFC822 {%d}" % (uid, len(raw)), raw)])
        raise AssertionError(f"unexpected uid cmd: {cmd} {args}")

    def logout(self):
        return ("OK", [b"BYE"])

    def _do_search(self, crit: str) -> str:
        c = crit.upper()
        matched = []
        for uid in sorted(self.messages):
            if "UNSEEN" in c:
                if uid in self.unseen:
                    matched.append(uid)
            elif "TEXT" in c:
                m = re.search(r'TEXT "([^"]*)"', crit, re.I)
                q = m.group(1).lower() if m else ""
                msg = email.message_from_bytes(self.messages[uid])
                subj = email_service._decode_header_value(msg.get("Subject")) or ""
                if q and q in subj.lower():
                    matched.append(uid)
            else:
                matched.append(uid)
        return " ".join(str(u) for u in matched)


@pytest.fixture(autouse=True)
def _clean_ctx_and_fake():
    """每个用例前清空 contextvar 与 FakeIMAP 共享状态，并让服务用 FakeIMAP。"""
    email_service._ctx_account.set(None)
    email_service._ctx_auth.set(None)
    FakeIMAP.messages.clear()
    FakeIMAP.unseen.clear()
    FakeIMAP.instances = []
    import imaplib
    imaplib.IMAP4_SSL = FakeIMAP
    yield
    email_service._ctx_account.set(None)
    email_service._ctx_auth.set(None)


def make_msg(uid, subject, sender="tester@example.com", body="邮件正文",
             unseen=True, attachment=False, date="Mon, 01 Sep 2026 10:00:00 +0800"):
    """构造一封简单邮件字节流。"""
    m = email.message.EmailMessage()
    m["Subject"] = subject
    m["From"] = sender
    m["Date"] = date
    m.set_content(body)
    if attachment:
        m.add_attachment(b"report", maintype="text", subtype="plain",
                         filename="report.txt")
    raw = m.as_bytes()
    if not FakeIMAP.instances:
        _new_fake()
    fake = FakeIMAP.instances[-1]
    fake.messages[uid] = raw
    if unseen:
        fake.unseen.add(uid)
    return raw


def _new_fake():
    fake = FakeIMAP("imap.qq.com", 993)
    FakeIMAP.instances.append(fake)
    return fake


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #

class TestBuildImapSearch:
    def test_empty_query(self):
        assert email_service.build_imap_search("", False) == ["ALL"]

    def test_unread_only(self):
        assert email_service.build_imap_search("", True) == ["UNSEEN"]

    def test_query_text(self):
        assert email_service.build_imap_search("报告", False) == ['TEXT "报告"']

    def test_query_and_unread(self):
        assert email_service.build_imap_search("build", True) == ["UNSEEN", 'TEXT "build"']

    def test_quote_escaping(self):
        assert email_service.build_imap_search('say "hi"', False) == ['TEXT "say \\"hi\\""']


class TestParseBearer:
    def test_bearer(self):
        assert email_service.parse_bearer("Bearer abc123") == "abc123"

    def test_raw_token(self):
        assert email_service.parse_bearer("abc123") == "abc123"

    def test_none(self):
        assert email_service.parse_bearer(None) is None
        assert email_service.parse_bearer("") is None


class TestResolveCredentials:
    def test_contextvar_wins(self):
        email_service._ctx_account.set("ctx@qq.com")
        email_service._ctx_auth.set("ctx-code")
        assert email_service.resolve_credentials() == ("ctx@qq.com", "ctx-code")

    def test_env_fallback(self, monkeypatch):
        monkeypatch.setenv("EMAIL_ACCOUNT", "env@qq.com")
        monkeypatch.setenv("EMAIL_AUTH_CODE", "env-code")
        assert email_service.resolve_credentials() == ("env@qq.com", "env-code")

    def test_explicit_args_win(self, monkeypatch):
        monkeypatch.setenv("EMAIL_ACCOUNT", "env@qq.com")
        monkeypatch.setenv("EMAIL_AUTH_CODE", "env-code")
        assert email_service.resolve_credentials("a@qq.com", "c") == ("a@qq.com", "c")

    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("EMAIL_ACCOUNT", raising=False)
        monkeypatch.delenv("EMAIL_AUTH_CODE", raising=False)
        with pytest.raises(ValueError, match="缺少邮箱凭据"):
            email_service.resolve_credentials()


class TestHeaderDecode:
    def test_ascii(self):
        assert email_service._decode_header_value("Hello") == "Hello"

    def test_rfc2047_base64_chinese(self):
        h = str(Header("测试邮件", "utf-8"))  # =?utf-8?b?...?=
        assert email_service._decode_header_value(h) == "测试邮件"

    def test_none(self):
        assert email_service._decode_header_value(None) == ""


class TestBodyExtract:
    def test_plain_text(self):
        # 真实 QQ 邮件带 charset 声明 → get_content() 正常解码
        msg = email.message_from_string(
            "Subject: t\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n第一行正文\n第二行正文",
            policy=_EMAIL_POLICY)
        assert "第一行正文" in email_service._extract_body(msg, 5000)

    def test_plain_text_no_charset(self):
        # 无 charset 声明的中文邮件 → 兜底直接用原始 str payload（不产生 \\uXXXX 字面转义）
        msg = email.message_from_string(
            "Subject: t\r\n\r\n第一行正文\n第二行正文", policy=_EMAIL_POLICY)
        body = email_service._extract_body(msg, 5000)
        assert "第一行正文" in body
        assert "\\u" not in body

    def test_html_stripped(self):
        msg = email.message_from_string(
            "Subject: t\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
            "<html><body><script>bad()</script><p>你好 <b>团队</b></p></body></html>",
            policy=_EMAIL_POLICY)
        body = email_service._extract_body(msg, 5000)
        assert "bad" not in body
        assert "你好" in body
        assert "团队" in body

    def test_multipart_plain_preferred(self):
        msg = email.message.EmailMessage()
        msg["Subject"] = "t"
        msg.set_content("纯文本正文")
        msg.add_alternative("<html><body><p>HTML 正文</p></body></html>", subtype="html")
        body = email_service._extract_body(msg, 5000)
        assert "纯文本正文" in body
        assert "HTML" not in body

    def test_max_chars(self):
        msg = email.message_from_string("Subject: t\r\n\r\n" + "x" * 100,
                                        policy=_EMAIL_POLICY)
        assert len(email_service._extract_body(msg, 50)) <= 50


class TestAttachment:
    def test_has_attachment(self):
        m = email.message.EmailMessage()
        m["Subject"] = "t"
        m.set_content("body")
        m.add_attachment(b"report", maintype="text", subtype="plain", filename="r.txt")
        assert email_service._has_attachment(m) is True

    def test_no_attachment(self):
        m = email.message.EmailMessage()
        m["Subject"] = "t"
        m.set_content("body")
        assert email_service._has_attachment(m) is False


# --------------------------------------------------------------------------- #
# 工具函数（FakeIMAP）
# --------------------------------------------------------------------------- #

class TestTools:
    def test_list_unread(self):
        fake = _new_fake()
        make_msg(1, "未读邮件A")
        make_msg(2, "已读邮件B", unseen=False)
        email_service._ctx_account.set("a@qq.com")
        email_service._ctx_auth.set("code")
        result = email_service.tool_list_unread(limit=10)
        assert "error" not in result, result
        assert result["unread"] == 1
        assert result["items"][0]["uid"] == 1
        # 工具内部会新建连接实例，断言最后一次连接的登录凭据
        assert FakeIMAP.instances[-1].logged_in == ("a@qq.com", "code")
        assert FakeIMAP.instances[-1].folder == "INBOX"

    def test_list_unread_missing_creds(self):
        _new_fake()
        result = email_service.tool_list_unread()
        assert "error" in result
        assert "凭据" in result["error"]

    def test_search_emails_imap_path(self):
        fake = _new_fake()
        make_msg(1, "构建报告通过", body="p1")
        make_msg(2, "无关邮件", body="p2")
        email_service._ctx_account.set("a@qq.com")
        email_service._ctx_auth.set("code")
        result = email_service.tool_search_emails(query="报告")
        assert "error" not in result, result
        assert result["count"] == 1
        assert result["mode"] == "imap_search"
        assert result["items"][0]["uid"] == 1

    def test_read_email(self):
        fake = _new_fake()
        make_msg(7, "主题中文", sender="boss@example.com", body="重要正文内容",
                 attachment=True)
        email_service._ctx_account.set("a@qq.com")
        email_service._ctx_auth.set("code")
        result = email_service.tool_read_email(uid=7)
        assert "error" not in result, result
        assert result["subject"] == "主题中文"
        assert "重要正文内容" in result["body"]
        assert result["has_attachment"] is True

    def test_read_email_missing(self):
        _new_fake()
        email_service._ctx_account.set("a@qq.com")
        email_service._ctx_auth.set("code")
        result = email_service.tool_read_email(uid=999)
        assert "error" in result

    def test_health(self):
        result = email_service.tool_email_health()
        assert result["status"] == "ok"
        assert result["server_name"] == "email"


# --------------------------------------------------------------------------- #
# MCP 协议
# --------------------------------------------------------------------------- #

class TestMcpProtocol:
    def test_tools_list(self):
        mcp = McpAdapter(server_name="email", server_version="1.0.0")
        email_service._register_mcp_tools(mcp)
        resp = mcp.handle_jsonrpc({"jsonrpc": "2.0", "id": 1,
                                   "method": "tools/list", "params": {}})
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == {"list_unread", "search_emails", "read_email", "email_health"}
        # 必填参数声明检查
        schema = {t["name"]: t for t in resp["result"]["tools"]}
        assert schema["read_email"]["inputSchema"]["required"] == ["uid"]

    def test_tools_call_health(self):
        mcp = McpAdapter(server_name="email", server_version="1.0.0")
        email_service._register_mcp_tools(mcp)
        resp = mcp.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "email_health", "arguments": {}}})
        assert "error" not in resp, resp
        text = resp["result"]["content"][0]["text"]
        assert json.loads(text)["status"] == "ok"

    def test_initialize(self):
        mcp = McpAdapter(server_name="email", server_version="1.0.0")
        email_service._register_mcp_tools(mcp)
        resp = mcp.handle_jsonrpc({"jsonrpc": "2.0", "id": 3,
                                   "method": "initialize", "params": {}})
        assert resp["result"]["serverInfo"]["name"] == "email"
        assert resp["result"]["capabilities"]["tools"] == {}

    def test_unknown_tool(self):
        mcp = McpAdapter(server_name="email", server_version="1.0.0")
        email_service._register_mcp_tools(mcp)
        resp = mcp.handle_jsonrpc({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "nope", "arguments": {}}})
        assert "error" in resp
        assert resp["error"]["code"] == -32602


class TestRestEndpoints:
    def test_app_build_and_health(self):
        app = email_service.build_app()
        assert app.title == "AgentTeams Email Tools (邮箱收信)"
        # 路由存在性
        paths = {r.path for r in app.routes}
        for expected in ("/health", "/mcp", "/v1/email/unread",
                         "/v1/email/search", "/v1/email/read"):
            assert expected in paths
