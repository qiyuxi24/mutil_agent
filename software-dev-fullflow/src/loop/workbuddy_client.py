"""⚠️ ⚠️ ⚠️  [DEPRECATED / 已废弃，仅保留作参考]  ⚠️ ⚠️ ⚠️

本模块：WorkBuddy (CodeBuddy) API 客户端 —— 逆向自腾讯 CodeBuddy 桌面版

【废弃原因】
  参赛主路径已切换为 AgentTeams 官方平台 + DeepSeek API Key 直连（OpenAI 兼容协议原生支持），
  不再需要通过逆向 CodeBuddy 桌面版作为模型通道。本文件仅保留给后续若需接入非标准模型端点时参考。

【当前状态】
  - 不被 run.py、agentteams_loop.py、loop/__init__.py 等参赛主路径模块 import
  - 仅 reverse_gateway.py（同样 DEPRECATED）、test_context_with_api.py、verify_reverse_api.py
    等手工调试脚本会引用
  - 不随参赛代码包的单元测试、集成测试、演示脚本加载执行

================================================================================
WorkBuddy (CodeBuddy) API 客户端 —— 逆向自腾讯 CodeBuddy 桌面版。

认证方式：
  1. 默认从本地 auth 文件读取凭据（需已安装 CodeBuddy 桌面版并登录）
  2. 支持 .env 配置覆盖

用法：
  from workbuddy_client import WorkBuddyClient
  client = WorkBuddyClient()
  resp, prompt_tokens, completion_tokens = client.chat(
      model="deepseek-v4-flash",
      messages=[{"role": "user", "content": "Hello"}],
  )
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# 自动加载 .env
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)


class WorkBuddyClient:
    """对接 CodeBuddy 后端 v2 API（OpenAI 兼容流式协议）。

    关键发现（逆向结果）：
      - 后端: https://copilot.tencent.com/v2/chat/completions
      - 协议: OpenAI 兼容，但 stream=true 是必需的（否则 11101 错误）
      - 认证: Bearer token + X-User-Id + X-Domain
      - 凭据位置: %LOCALAPPDATA%\\CodeBuddyExtension\\Data\\Public\\auth\\*.info
      - 可用模型: deepseek-v4-flash (默认), deepseek-v4-pro, hunyuan-2.0-instruct
    """

    # 默认配置（可从 .env 覆盖）
    BACKEND = os.getenv("WORKBUDDY_BASE_URL", "https://copilot.tencent.com")
    CHAT_PATH = os.getenv("WORKBUDDY_CHAT_PATH", "/v2/chat/completions")
    DEFAULT_MODEL = os.getenv("WORKBUDDY_MODEL", "deepseek-v4-flash")
    REASONING_MODEL = os.getenv("WORKBUDDY_REASONING_MODEL", "deepseek-v4-pro")

    def __init__(self, model: str | None = None):
        self.model = model or self.DEFAULT_MODEL
        self._token = ""
        self._uid = ""
        self._domain = ""
        self._load_auth()

    # ------------------------------------------------------------------ #
    # 认证
    # ------------------------------------------------------------------ #

    def _load_auth(self) -> None:
        """从本地 CodeBuddy auth 文件加载凭据。"""
        auth_mode = os.getenv("WORKBUDDY_AUTH_MODE", "local_file")

        if auth_mode == "local_file":
            auth_dir = self._find_auth_dir()
            if not auth_dir:
                raise RuntimeError(
                    "未找到 CodeBuddy auth 目录。请确保已安装 CodeBuddy/WorkBuddy 桌面版并已登录。\n"
                    "auth 路径: %LOCALAPPDATA%\\CodeBuddyExtension\\Data\\Public\\auth\\"
                )
            auth_files = sorted(auth_dir.glob("*.info"))
            if not auth_files:
                raise RuntimeError(f"auth 目录为空: {auth_dir}")

            data = json.loads(auth_files[0].read_text(encoding="utf-8"))
            auth = data.get("auth", {})
            account = data.get("account", {})
            self._token = auth.get("accessToken", "")
            self._uid = account.get("uid", "")
            self._domain = auth.get("domain", "www.codebuddy.cn")
        else:
            # 直接使用环境变量中的 token
            self._token = os.getenv("WORKBUDDY_ACCESS_TOKEN", "")
            self._uid = os.getenv("WORKBUDDY_USER_ID", "")
            self._domain = os.getenv("WORKBUDDY_DOMAIN", "www.codebuddy.cn")

        if not self._token:
            raise RuntimeError("未找到有效的 accessToken")

    @staticmethod
    def _find_auth_dir() -> Path | None:
        """跨平台查找 CodeBuddy auth 目录。"""
        if sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            if local_appdata:
                p = Path(local_appdata) / "CodeBuddyExtension" / "Data" / "Public" / "auth"
                if p.exists():
                    return p
        # macOS / Linux
        home = Path.home()
        xdg = os.environ.get("XDG_DATA_HOME", "")
        candidates = [
            Path(xdg) / "CodeBuddyExtension" / "Data" / "Public" / "auth" if xdg else None,
            home / ".local" / "share" / "CodeBuddyExtension" / "Data" / "Public" / "auth",
        ]
        for p in candidates:
            if p and p.exists():
                return p
        return None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "X-User-Id": self._uid,
            "X-Domain": self._domain,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    # API 调用
    # ------------------------------------------------------------------ #

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int = 500,
        temperature: float = 0.3,
    ) -> tuple[str, int, int]:
        """调用 Chat Completions API。

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            model: 模型名，默认 deepseek-v4-flash
            max_tokens: 最大输出 token
            temperature: 温度

        Returns:
            (response_text, prompt_tokens, completion_tokens)
        """
        body = {
            "model": model or self.model,
            "messages": messages,
            "stream": True,  # 必需！否则 11101 错误
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        url = f"{self.BACKEND}{self.CHAT_PATH}"
        r = requests.post(url, headers=self._headers(), json=body, timeout=120, stream=True)

        if r.status_code != 200:
            raise RuntimeError(f"API error {r.status_code}: {r.text[:300]}")

        full_text = ""
        prompt_tokens = 0
        completion_tokens = 0

        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
                usage = chunk.get("usage", {})
                if usage:
                    prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                    completion_tokens = usage.get("completion_tokens", completion_tokens)
                choices = chunk.get("choices", [])
                if choices and choices[0] is not None:
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content", "")
                    if content:
                        full_text += content
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass

        return full_text.strip(), prompt_tokens, completion_tokens

    # ------------------------------------------------------------------ #
    # 工具方法
    # ------------------------------------------------------------------ #

    def check_connectivity(self) -> tuple[bool, str]:
        """快速连通性测试。"""
        try:
            resp, _, _ = self.chat(
                messages=[{"role": "user", "content": "Say hi"}],
                max_tokens=20,
            )
            return True, resp[:50]
        except Exception as e:
            return False, str(e)[:200]

    @property
    def info(self) -> dict[str, Any]:
        return {
            "backend": self.BACKEND,
            "chat_path": self.CHAT_PATH,
            "model": self.model,
            "uid": self._uid[:12] + "..." if self._uid else "N/A",
            "domain": self._domain,
        }


# ========================================================================== #
# 自检
# ========================================================================== #

if __name__ == "__main__":
    print("=== WorkBuddy Client 自检 ===")

    client = WorkBuddyClient()
    print(f"backend: {client.BACKEND}")
    print(f"model: {client.model}")
    print(f"uid: {client._uid[:12]}...")
    print(f"domain: {client._domain}")

    ok, msg = client.check_connectivity()
    if ok:
        print(f"✓ 连通: {msg}")
    else:
        print(f"✘ 不通: {msg}")
        sys.exit(1)

    # 测试代码生成
    print("\n--- 测试代码生成 ---")
    resp, pt, ct = client.chat(
        messages=[{
            "role": "user",
            "content": "用 Python 写一个函数 is_prime(n) 判断素数，只输出代码不要解释",
        }],
        max_tokens=200,
    )
    print(f"prompt_tokens={pt}, completion_tokens={ct}")
    print(f"response:\n{resp[:200]}")

    print("\n✓ 全部通过")