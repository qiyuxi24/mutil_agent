"""AgentTeams Matrix 协议客户端 —— 官方 replay-task.sh 的 Python 版。

官方与 Manager/Worker 的交互走 Matrix（/rooms/{id}/send/m.room.message），
而非 agt CLI。本模块是 `scripts/replay-task.sh` + `tests/lib/matrix-client.sh`
的 Python 等价实现，以 mixin 形式提供，由 AgentTeamsClient 组合使用。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any


class MatrixClientMixin:
    """Matrix 客户端混入。

    依赖宿主实例提供：
      - matrix_url / matrix_domain / admin_user / admin_password / manager_user
      - _token（登录后缓存）
    使用方（AgentTeamsClient）在 __init__ 中设置以上属性即可。
    """

    # 子类需实现/提供以下属性，这里声明默认以规避 linter
    matrix_url: str = ""
    matrix_domain: str = ""
    manager_user: str = ""

    def _matrix_api(self, method: str, path: str, data: Any = None) -> Any:
        """执行 Matrix API 调用。阻塞式（内部用同步 urllib）。"""
        url = f"{self.matrix_url}{path}"
        headers = {}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        token = getattr(self, "_token", "") or ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Matrix API {method} {path} 失败: {e.code} {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Matrix API {method} {path} 连接失败: {e.reason}")

    def matrix_login(self) -> str:
        """以 admin 登录 Matrix，缓存并返回 access_token。"""
        if getattr(self, "_token", ""):
            return self._token
        if not self.admin_password:
            raise RuntimeError("AGENTTEAMS_ADMIN_PASSWORD 未设置，无法登录 Matrix")
        data = self._matrix_api(
            "POST",
            "/_matrix/client/v3/login",
            {
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": self.admin_user},
                "password": self.admin_password,
            },
        )
        self._token = data.get("access_token", "")
        if not self._token:
            raise RuntimeError("Matrix 登录失败：未返回 access_token")
        return self._token

    def _urlencode_room(self, room_id: str) -> str:
        return urllib.parse.quote(room_id, safe="")

    def get_joined_rooms(self) -> list[str]:
        """获取 admin 已加入的所有房间。"""
        data = self._matrix_api("GET", "/_matrix/client/v3/joined_rooms")
        return data.get("joined_rooms", [])

    def get_room_members(self, room_id: str) -> list[str]:
        """获取房间成员（state_key 列表）。"""
        data = self._matrix_api(
            "GET", f"/_matrix/client/v3/rooms/{self._urlencode_room(room_id)}/members"
        )
        return [m.get("state_key", "") for m in data.get("chunk", [])]

    def find_manager_room(self) -> str:
        """查找与 Manager 的 DM 房间（恰好 2 成员且含 @manager）。"""
        manager_full = f"@{self.manager_user}:{self.matrix_domain}"
        for room_id in self.get_joined_rooms():
            try:
                members = self.get_room_members(room_id)
            except RuntimeError:
                continue
            if len(members) == 2 and any(manager_full in m for m in members):
                return room_id
        return ""

    def create_dm_room(self) -> str:
        """创建与 Manager 的 DM 房间。"""
        manager_full = f"@{self.manager_user}:{self.matrix_domain}"
        data = self._matrix_api(
            "POST",
            "/_matrix/client/v3/createRoom",
            {
                "is_direct": True,
                "invite": [manager_full],
                "preset": "trusted_private_chat",
            },
        )
        return data.get("room_id", "")

    def ensure_manager_room(self) -> str:
        """确保存在与 Manager 的 DM 房间，返回 room_id。"""
        room = self.find_manager_room()
        if not room:
            room = self.create_dm_room()
        if not room:
            raise RuntimeError("无法建立与 Manager 的 DM 房间")
        return room

    def find_worker_room(self, worker: str) -> str:
        """查找与指定 Worker 的 DM 房间（2 成员且含 @worker）。"""
        worker_full = f"@{worker}:{self.matrix_domain}"
        for room_id in self.get_joined_rooms():
            try:
                members = self.get_room_members(room_id)
            except RuntimeError:
                continue
            if len(members) == 2 and any(worker_full in m for m in members):
                return room_id
        return ""

    def create_worker_dm_room(self, worker: str) -> str:
        """创建与指定 Worker 的 DM 房间。"""
        worker_full = f"@{worker}:{self.matrix_domain}"
        data = self._matrix_api(
            "POST",
            "/_matrix/client/v3/createRoom",
            {
                "is_direct": True,
                "invite": [worker_full],
                "preset": "trusted_private_chat",
            },
        )
        return data.get("room_id", "")

    def ensure_worker_room(self, worker: str) -> str:
        """确保存在与指定 Worker 的 DM 房间，返回 room_id。"""
        room = self.find_worker_room(worker)
        if not room:
            room = self.create_worker_dm_room(worker)
        if not room:
            raise RuntimeError(f"无法建立与 Worker {worker} 的 DM 房间")
        return room

    def read_worker_reply(self, worker: str, baseline_event: str = "") -> str:
        """读取指定 Worker 房间里该 Worker 最新一条回复文本。"""
        room_id = self.ensure_worker_room(worker)
        msgs = self.read_room_messages(room_id, 20)
        worker_full = f"@{worker}:{self.matrix_domain}"
        for m in reversed(msgs):  # 最新优先
            if worker_full in m["sender"] and m["event_id"] != baseline_event:
                return m["content"]
        return ""

    def send_matrix_message(self, room_id: str, body: str) -> None:
        """向房间发一条文本消息（m.room.message）。"""
        txn_id = f"pdca_{int(time.time() * 1000)}"
        self._matrix_api(
            "PUT",
            f"/_matrix/client/v3/rooms/{self._urlencode_room(room_id)}"
            f"/send/m.room.message/{txn_id}",
            {"msgtype": "m.text", "body": body},
        )

    def read_room_messages(self, room_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """读取房间最近消息（dir=b 最新优先），返回按时间正序的 m.room.message 列表。"""
        data = self._matrix_api(
            "GET",
            f"/_matrix/client/v3/rooms/{self._urlencode_room(room_id)}/messages"
            f"?dir=b&limit={limit}",
        )
        chunk = data.get("chunk", [])
        msgs = [
            {
                "sender": m.get("sender", ""),
                "content": (m.get("content", {}) or {}).get("body", ""),
                "event_id": m.get("event_id", ""),
                "ts": m.get("origin_server_ts", 0),
            }
            for m in chunk
            if m.get("type") == "m.room.message"
            and (m.get("content", {}) or {}).get("body")
        ]
        msgs.sort(key=lambda m: m["ts"])
        return msgs
