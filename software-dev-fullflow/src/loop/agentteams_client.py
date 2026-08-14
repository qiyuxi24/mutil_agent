"""AgentTeams 平台客户端 —— 封装 agt CLI，提供 Python 原生调用接口。

AgentTeams 框架的核心概念：
  - Manager: LLM 驱动的调度者，接收用户任务，自动匹配 Worker/Team
  - Worker:  声明式 Agent（YAML CRD），有 soul/agents/skills/mcpServers
  - Team:    一组 Worker 的协作单元，有 Leader 负责拆解与委派
  - Matrix 房间: Worker 之间通过 @mention 在 Matrix 房间中接力协作

本模块封装 agt CLI 的所有操作，让 Python 代码可以：
  1. 创建/查询/更新/删除 Worker
  2. 创建/查询 Team
  3. 给 Manager 发任务并监控进度
  4. 查询 Matrix 房间中的消息（里程碑追踪）
  5. 管理 Skills 和 MCP 服务器

与旧 loop 的关系：
  - 旧 manager.py 用 MAF 的 Agent 类手动调度 → 新 AgentTeamsClient 用 agt CLI 委托给 AgentTeams 平台
  - 旧 fixer_loop.py 内部自我迭代 → AgentTeams 的 Fixer Worker 自带 skill 能力
  - 旧 context.py 内存预算管理 → AgentTeams 的 shared/knowledge + MinIO 持久化
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


# ========================================================================== #
# 1. CLI 执行器
# ========================================================================== #

class AgtCLI:
    """agt CLI 命令执行器。

    支持两种模式：
      - docker:  docker exec agentteams-controller agt ...
      - local:   agt ...（本地安装）
    """

    MODE = os.environ.get("AGT_MODE", "docker")  # docker | local
    CONTROLLER = os.environ.get("AGT_CONTROLLER", "agentteams-controller")

    @classmethod
    async def run(cls, *args: str, timeout: int = 60) -> tuple[int, str, str]:
        """执行 agt 命令，返回 (exit_code, stdout, stderr)。"""
        if cls.MODE == "docker":
            cmd = ["docker", "exec", cls.CONTROLLER, "agt"] + list(args)
        else:
            cmd = ["agt"] + list(args)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"agt 命令超时 ({timeout}s): {' '.join(cmd)}")

        return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    @classmethod
    def run_sync(cls, *args: str, timeout: int = 60) -> tuple[int, str, str]:
        """同步执行 agt 命令。"""
        if cls.MODE == "docker":
            cmd = ["docker", "exec", cls.CONTROLLER, "agt"] + list(args)
        else:
            cmd = ["agt"] + list(args)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr


# ========================================================================== #
# 2. 数据模型
# ========================================================================== #

@dataclass
class WorkerInfo:
    """Worker 运行时信息。"""
    name: str
    model: str = ""
    runtime: str = ""
    state: str = "Unknown"
    skills: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)

    @classmethod
    def from_agt_output(cls, name: str, output: str) -> "WorkerInfo":
        """从 agt get worker 的 YAML 输出解析。"""
        info = cls(name=name)
        # 简单解析 key: value 行
        current_key = ""
        for line in output.split("\n"):
            stripped = line.strip()
            if ":" in stripped and not stripped.startswith("-") and not stripped.startswith(" "):
                key, _, val = stripped.partition(":")
                key, val = key.strip(), val.strip().strip('"')
                if key == "model":
                    info.model = val
                elif key == "runtime":
                    info.runtime = val
                elif key == "state":
                    info.state = val
            elif stripped.startswith("- ") and current_key == "skills":
                info.skills.append(stripped[2:].strip())
            elif stripped.startswith("- ") and current_key == "mcpServers":
                info.mcp_servers.append(stripped[2:].strip())
            elif "skills:" in stripped:
                current_key = "skills"
            elif "mcpServers:" in stripped:
                current_key = "mcpServers"
        return info


@dataclass
class TaskInfo:
    """任务运行时信息。"""
    task_id: str
    spec: str
    state: str = "pending"
    current_worker: str = ""
    milestone: str = ""
    created_at: float = field(default_factory=time.time)

    def elapsed(self) -> float:
        return time.time() - self.created_at


# ========================================================================== #
# 3. AgentTeamsClient —— 核心客户端
# ========================================================================== #

class AgentTeamsClient:
    """AgentTeams 平台的 Python 客户端。

    封装所有 agt CLI 操作，提供：
      - Worker 生命周期管理
      - Team 管理
      - 任务派发与状态追踪
      - Matrix 房间消息查询
      - Skills 和 MCP 管理

    用法：
        client = AgentTeamsClient()
        await client.ping()                    # 检查平台状态
        workers = await client.list_workers()  # 获取所有 Worker
        task = await client.create_task(       # 创建 PDCA 任务
            spec="修复登录页面空指针异常",
            pipeline=["aggregator", "rootcause", "fixer", "tester", "releaser", "retrospector"]
        )
        result = await client.wait_for_task(task.task_id)  # 等待任务完成
    """

    # PDCA 流水线的 6 个 Worker（与 src/agentteams/workers.yaml 对齐）
    PDCA_WORKERS = ["aggregator", "rootcause", "fixer", "tester", "releaser", "retrospector"]

    # 里程碑词 → 下一个 Worker 的映射
    MILESTONE_NEXT: dict[str, str] = {
        "TASK_SPEC_READY": "rootcause",
        "ROOT_CAUSE_FOUND": "fixer",
        "FIX_APPLIED": "tester",
        "TEST_PASSED": "releaser",
        "TEST_FAILED": "fixer",          # 打回
        "RELEASE_OK": "retrospector",
        "RELEASE_ROLLED_BACK": "fixer",  # 打回
        "RETROSPECT_DONE": "",           # 闭环结束
    }

    def __init__(self, mode: str = ""):
        if mode:
            AgtCLI.MODE = mode
        # Matrix 相关配置（与官方 replay-task.sh 对齐）
        self.matrix_url = os.environ.get(
            "AGENTTEAMS_MATRIX_URL", "http://127.0.0.1:18080"
        ).rstrip("/")
        self.matrix_domain = os.environ.get(
            "AGENTTEAMS_MATRIX_DOMAIN", "matrix-local.agentteams.io:18080"
        )
        self.admin_user = os.environ.get("AGENTTEAMS_ADMIN_USER", "admin")
        self.admin_password = os.environ.get("AGENTTEAMS_ADMIN_PASSWORD", "")
        self.manager_user = os.environ.get("AGENTTEAMS_MANAGER_USER", "manager")
        self._token: str = ""
        self._http = httpx.AsyncClient(trust_env=False, timeout=30)

    # ------------------------------------------------------------------ #
    # Matrix 协议客户端（官方 replay-task.sh 的 Python 版）
    #  官方与 Manager/Worker 的交互走 Matrix（/rooms/{id}/send/m.room.message），
    #  而非 agt CLI。本类是 `scripts/replay-task.sh` + `tests/lib/matrix-client.sh`
    #  的 Python 等价实现。
    # ------------------------------------------------------------------ #
    def _matrix_api(self, method: str, path: str, data: Any = None) -> Any:
        """执行 Matrix API 调用。阻塞式（内部用同步 urllib）。"""
        url = f"{self.matrix_url}{path}"
        headers = {}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
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
        if self._token:
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

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ #
    # 连接检查
    # ------------------------------------------------------------------ #

    async def ping(self) -> bool:
        """检查 AgentTeams 平台是否可用。"""
        code, stdout, stderr = await AgtCLI.run("get", "managers", timeout=10)
        return code == 0 and "Running" in stdout

    async def status(self) -> dict[str, Any]:
        """获取平台整体状态。"""
        managers = await self._list_resource("managers")
        workers = await self._list_resource("workers")
        teams = await self._list_resource("teams")
        return {
            "managers": managers,
            "workers": workers,
            "teams": teams,
            "pdca_workers_ready": all(
                w in workers for w in self.PDCA_WORKERS
            ),
        }

    # ------------------------------------------------------------------ #
    # Worker 管理
    # ------------------------------------------------------------------ #

    async def list_workers(self) -> list[WorkerInfo]:
        """列出所有 Worker。"""
        code, stdout, _ = await AgtCLI.run("get", "workers")
        if code != 0:
            return []
        workers = []
        for name in re.findall(r"name:\s*(\S+)", stdout):
            # 获取详细信息
            _, detail, _ = await AgtCLI.run("get", "worker", name, "-o", "yaml")
            workers.append(WorkerInfo.from_agt_output(name, detail))
        return workers

    async def get_worker(self, name: str) -> WorkerInfo | None:
        """获取单个 Worker 详情。"""
        code, stdout, _ = await AgtCLI.run("get", "worker", name, "-o", "yaml")
        if code != 0:
            return None
        return WorkerInfo.from_agt_output(name, stdout)

    async def create_worker(
        self,
        name: str,
        soul_file: str,
        model: str = "deepseek-v4-flash",
        runtime: str = "copaw",
        skills: list[str] | None = None,
        mcp_servers: list[str] | None = None,
    ) -> bool:
        """创建 Worker。"""
        args = [
            "create", "worker",
            "--name", name,
            "--soul-file", soul_file,
            "--model", model,
            "--runtime", runtime,
        ]
        if skills:
            for s in skills:
                args.extend(["--skills", s])
        if mcp_servers:
            for m in mcp_servers:
                args.extend(["--mcpServers", m])

        code, stdout, stderr = await AgtCLI.run(*args, timeout=30)
        return code == 0

    async def update_worker(
        self,
        name: str,
        model: str = "",
        soul_file: str = "",
        skills: list[str] | None = None,
        state: str = "",
    ) -> bool:
        """更新 Worker 配置。"""
        args = ["update", "worker", "--name", name]
        if model:
            args.extend(["--model", model])
        if soul_file:
            args.extend(["--soul-file", soul_file])
        if skills:
            for s in skills:
                args.extend(["--skills", s])
        if state:
            args.extend(["--state", state])

        code, _, _ = await AgtCLI.run(*args, timeout=30)
        return code == 0

    async def delete_worker(self, name: str) -> bool:
        """删除 Worker。"""
        code, _, _ = await AgtCLI.run("delete", "worker", "--name", name)
        return code == 0

    async def ensure_pdca_workers(self, workers_dir: str) -> dict[str, bool]:
        """确保 6 个 PDCA Worker 都已创建并 Running。

        Args:
            workers_dir: SOUL.md 文件所在目录（如 src/agentteams/workers/）

        Returns:
            {worker_name: is_ready}
        """
        existing = await self._list_resource("workers")
        results = {}

        for name in self.PDCA_WORKERS:
            if name in existing:
                results[name] = True
                continue

            soul_path = Path(workers_dir) / name / "SOUL.md"
            if not soul_path.exists():
                results[name] = False
                continue

            # 从 workers.yaml 读取对应配置
            skills = self._get_worker_skills(name)
            mcp = self._get_worker_mcp(name)

            ok = await self.create_worker(
                name=name,
                soul_file=str(soul_path),
                skills=skills,
                mcp_servers=mcp,
            )
            results[name] = ok

        return results

    # ------------------------------------------------------------------ #
    # Team 管理
    # ------------------------------------------------------------------ #

    async def create_team(
        self,
        name: str,
        members: list[str],
        leader: str = "",
    ) -> bool:
        """创建 Team。

        AgentTeams 的 Team 机制：
          - Leader 负责拆解任务并委派给成员
          - 成员之间通过 @mention 在 Matrix 房间中接力
        """
        args = ["create", "team", "--name", name]
        for m in members:
            args.extend(["--member", m])
        if leader:
            args.extend(["--leader", leader])

        code, _, _ = await AgtCLI.run(*args, timeout=30)
        return code == 0

    async def list_teams(self) -> list[str]:
        """列出所有 Team。"""
        return await self._list_resource("teams")

    # ------------------------------------------------------------------ #
    # 任务派发（核心：PDCA 闭环驱动）
    # ------------------------------------------------------------------ #

    async def create_task(
        self,
        spec: str,
        pipeline: list[str] | None = None,
        manager: str = "default",
    ) -> TaskInfo:
        """创建一个 PDCA 任务并派发给 Manager（通过 Matrix DM 房间）。

        AgentTeams 的任务派发走 Matrix 协议（官方 replay-task.sh 的做法）：
          1. admin 登录 Matrix
          2. 找到或创建与 @manager 的 DM 房间
          3. 向房间发任务消息（含 PDCA 流水线与里程碑协议）
          4. Manager（LLM 驱动）收到后自动匹配 Worker 并派单

        注意：官方 agt CLI **没有** `task`/`send`/`messages` 子命令，
        向 Manager 发任务必须走 Matrix。本方法是官方 `replay-task.sh` 的 Python 等价。

        Args:
            spec: 任务规格（自然语言描述）
            pipeline: PDCA 流水线 Worker 列表（默认 6 个）
            manager: Manager 名称（Matrix 用户 localpart）

        Returns:
            TaskInfo with task_id for tracking
        """
        pipeline = pipeline or self.PDCA_WORKERS
        self.manager_user = manager

        # 构造 PDCA 任务上下文（含里程碑握手协议）
        task_context = (
            f"【PDCA 闭环任务】\n\n"
            f"任务规格：\n{spec}\n\n"
            f"流水线：{' → '.join(pipeline)}\n\n"
            f"请按以下研发团队接力流程执行，每个 Worker 完成后 @mention 下一个并输出对应里程碑词：\n"
            f"- aggregator → TASK_SPEC_READY → @rootcause\n"
            f"- rootcause  → ROOT_CAUSE_FOUND → @fixer\n"
            f"- fixer      → FIX_APPLIED → @tester\n"
            f"- tester     → TEST_PASSED → @releaser（失败则 TEST_FAILED → @fixer）\n"
            f"- releaser   → RELEASE_OK → @retrospector（失败则 RELEASE_ROLLED_BACK → @fixer）\n"
            f"- retrospector → RETROSPECT_DONE → @manager（闭环结束）\n"
        )

        # 走 Matrix：登录 + 找/建 DM + 发任务
        self.matrix_login()
        room_id = self.ensure_manager_room()
        self.send_matrix_message(room_id, task_context)

        task_id = f"pdca-{int(time.time())}"
        return TaskInfo(task_id=task_id, spec=spec)

    # ------------------------------------------------------------------ #
    # 任务监控（里程碑追踪，走 Matrix 房间消息）
    # ------------------------------------------------------------------ #

    async def get_task_messages(self, task_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """获取与 Manager 的 DM 房间消息（追踪 PDCA 进度）。

        注意：官方没有 `agt messages`，通过 Matrix `read_room_messages` 读取。
        这里读取的是 admin 与 Manager 的 DM 房间消息（Worker 接力也会反映在该房间）。
        """
        try:
            self.matrix_login()
            room_id = self.ensure_manager_room()
        except RuntimeError as e:
            print(f"  ⚠ 读取消息失败: {e}")
            return []
        return self.read_room_messages(room_id, limit)

    async def detect_milestones(self, task_id: str) -> list[dict[str, str]]:
        """扫描 admin 所有已加入房间，检测里程碑词。

        官方 Manager 在 admin+manager+worker 的**三方房间**里驱动 Worker 接力，
        因此只轮询 manager DM 房间会漏掉 Worker 的里程碑。这里扫描所有房间。

        Returns:
            [{milestone: "TASK_SPEC_READY", worker: "aggregator", timestamp: ...}, ...]
        """
        milestones = []

        milestone_patterns = [
            "TASK_SPEC_READY", "ROOT_CAUSE_FOUND", "FIX_APPLIED",
            "TEST_PASSED", "TEST_FAILED",
            "RELEASE_OK", "RELEASE_ROLLED_BACK",
            "RETROSPECT_DONE",
        ]

        # 扫描所有 admin 已加入的房间
        try:
            self.matrix_login()
            rooms = self.get_joined_rooms()
        except RuntimeError as e:
            print(f"  ⚠ 检测里程碑失败: {e}")
            return milestones

        admin_full = f"@{self.admin_user}:{self.matrix_domain}"
        for room_id in rooms:
            try:
                msgs = self.read_room_messages(room_id, 50)
            except RuntimeError:
                continue
            for msg in msgs:
                # 排除 admin 自己发的消息（那是任务指令，不是 Worker 产出）
                if admin_full in msg["sender"]:
                    continue
                for m in milestone_patterns:
                    if m in msg["content"]:
                        milestones.append({
                            "milestone": m,
                            "worker": msg["sender"],
                            "content": msg["content"][:200],
                        })
                        break
        return milestones

    async def wait_for_task(
        self,
        task_id: str,
        timeout: float = 600,
        poll_interval: float = 10,
    ) -> dict[str, Any]:
        """等待任务完成，轮询里程碑进度。

        Args:
            task_id: 任务 ID
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）

        Returns:
            {
                "status": "completed" | "failed" | "timeout",
                "milestones": [...],
                "elapsed": float,
            }
        """
        start = time.time()
        seen_milestones: set[str] = set()

        while time.time() - start < timeout:
            await asyncio.sleep(poll_interval)

            milestones = await self.detect_milestones(task_id)
            new_milestones = [m for m in milestones if m["milestone"] not in seen_milestones]

            for m in new_milestones:
                seen_milestones.add(m["milestone"])
                print(f"  [AgentTeams] 检测到里程碑: {m['milestone']} ← @{m['worker']}")

            # 检查是否闭环完成
            if "RETROSPECT_DONE" in seen_milestones:
                return {
                    "status": "completed",
                    "milestones": milestones,
                    "elapsed": time.time() - start,
                }

            # 检查是否失败
            if "TEST_FAILED" in seen_milestones or "RELEASE_ROLLED_BACK" in seen_milestones:
                # 打回后继续等待（可能会有 FIX_APPLIED 的再次出现）
                pass

        return {
            "status": "timeout",
            "milestones": list(seen_milestones),
            "elapsed": time.time() - start,
        }

    # ------------------------------------------------------------------ #
    # Skill 管理
    # ------------------------------------------------------------------ #

    async def push_skills(self, worker_name: str, skill_names: list[str]) -> bool:
        """给 Worker 推送 Skills（通过 push-worker-skills.sh）。"""
        args = ["skills", "push", "--worker", worker_name]
        for s in skill_names:
            args.extend(["--skill", s])

        code, _, _ = await AgtCLI.run(*args, timeout=30)
        return code == 0

    async def list_skills(self) -> list[str]:
        """列出所有可用 Skill。"""
        return await self._list_resource("skills")

    # ------------------------------------------------------------------ #
    # 治理命令（对齐 evaluation.py 的评价 → 治理）
    # ------------------------------------------------------------------ #

    async def apply_governance(self, role: str, action: str) -> bool:
        """执行治理动作。

        Args:
            role: Worker 名称
            action: retain / coach / demote_or_fire
        """
        if action == "retain":
            return True   # 无需操作
        if action == "coach":
            # 培训：换模型 + 换 SOUL
            ok1 = await self.update_worker(role, model="deepseek-v4-pro")
            ok2 = await self.update_worker(role, soul_file=f"workers/{role}/SOUL.md")
            return ok1 and ok2
        if action == "demote_or_fire":
            # 裁员：先归档记忆，再删除
            await self._archive_worker_knowledge(role)
            return await self.delete_worker(role)
        return False

    # ------------------------------------------------------------------ #
    # Human 介入接口（Phase 3.3）
    # ------------------------------------------------------------------ #

    async def approve_release(self, task_id: str, approved: bool = True,
                              reason: str = "") -> bool:
        """人工审批发布。

        AgentTeams 的 Human CRD 允许人工介入审批。
        此方法通过 Matrix 向 Manager 发送审批结果。

        Args:
            task_id: 任务 ID
            approved: 是否批准
            reason: 审批理由
        """
        self.matrix_login()
        room_id = self.ensure_manager_room()

        if approved:
            msg = (
                f"[Human 审批] 任务 {task_id} 发布审批：通过\n"
                f"审批理由: {reason or '人工确认通过'}\n"
                f"请继续发布流程。"
            )
        else:
            msg = (
                f"[Human 审批] 任务 {task_id} 发布审批：驳回\n"
                f"驳回理由: {reason or '人工审批不通过'}\n"
                f"请打回修复流程。"
            )

        self.send_matrix_message(room_id, msg)
        return True

    async def request_human_intervention(self, task_id: str, reason: str,
                                         urgency: str = "normal") -> bool:
        """请求人工介入。

        当系统检测到需要人工决策的场景时（如高风险发布、数据迁移确认等），
        通过此方法向人工操作员发送介入请求。

        Args:
            task_id: 任务 ID
            reason: 介入原因
            urgency: 紧急程度（low / normal / high / critical）
        """
        self.matrix_login()
        room_id = self.ensure_manager_room()

        urgency_prefix = {
            "low": "[低优先级]",
            "normal": "",
            "high": "[高优先级]",
            "critical": "[紧急]",
        }.get(urgency, "")

        msg = (
            f"{urgency_prefix} [Human 介入请求] 任务 {task_id}\n\n"
            f"原因: {reason}\n"
            f"紧急程度: {urgency}\n\n"
            f"请人工操作员尽快介入处理。"
        )

        self.send_matrix_message(room_id, msg)
        return True

    async def send_human_feedback(self, task_id: str, worker_name: str,
                                  feedback: str) -> bool:
        """向指定 Worker 发送人工反馈。

        人工操作员可以针对某个 Worker 的产出提供反馈，
        反馈会通过 Matrix 发送给 Manager，由 Manager 转达给 Worker。

        Args:
            task_id: 任务 ID
            worker_name: 目标 Worker
            feedback: 反馈内容
        """
        self.matrix_login()
        room_id = self.ensure_manager_room()

        msg = (
            f"[Human 反馈] 任务 {task_id} → @{worker_name}\n\n"
            f"反馈内容:\n{feedback}\n\n"
            f"请 Manager 将以上反馈转达给 {worker_name}。"
        )

        self.send_matrix_message(room_id, msg)
        return True

    async def override_worker_state(self, worker_name: str,
                                    new_state: str) -> bool:
        """人工覆盖 Worker 状态。

        允许人工操作员直接修改 Worker 状态（如暂停/恢复/重启）。

        Args:
            worker_name: Worker 名称
            new_state: 新状态（Running / Stopped / Paused）
        """
        return await self.update_worker(worker_name, state=new_state)

    async def get_human_tasks(self) -> list[dict[str, Any]]:
        """获取所有需要人工介入的任务。

        扫描 Manager 房间消息，识别包含 Human 介入请求的消息。
        """
        try:
            self.matrix_login()
            room_id = self.ensure_manager_room()
            msgs = self.read_room_messages(room_id, 50)
        except RuntimeError:
            return []

        human_tasks = []
        for msg in msgs:
            content = msg.get("content", "")
            if "[Human 介入请求]" in content or "[Human 审批]" in content:
                human_tasks.append({
                    "sender": msg.get("sender", ""),
                    "content": content,
                    "timestamp": msg.get("ts", 0),
                })
        return human_tasks

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #

    async def _list_resource(self, resource: str) -> list[str]:
        """通用资源列表查询。"""
        code, stdout, _ = await AgtCLI.run("get", resource)
        if code != 0:
            return []
        return re.findall(r"name:\s*(\S+)", stdout)

    def _get_worker_skills(self, name: str) -> list[str]:
        """从 workers.yaml 获取 Worker 的默认 skills。"""
        defaults = {
            "aggregator": ["issue-parsing", "knowledge-rag", "evidence-log"],
            "rootcause": ["root-cause-analysis", "impact-analysis", "git-operations",
                          "repo-context", "code-search", "knowledge-rag", "evidence-log"],
            "fixer": ["code-gen", "git-operations", "repo-context", "code-search", "evidence-log"],
            "tester": ["test-generation", "evidence-log"],
            "releaser": ["release-gate", "evidence-log"],
            "retrospector": ["retrospective", "knowledge-rag", "evidence-log"],
        }
        return defaults.get(name, [])

    def _get_worker_mcp(self, name: str) -> list[str]:
        """从 workers.yaml 获取 Worker 的默认 MCP 服务器。"""
        defaults = {
            "aggregator": ["github"],
            "rootcause": ["github"],
            "fixer": ["github", "code-scan"],
            "tester": ["test-platform"],
            "releaser": ["ci"],
            "retrospector": [],
        }
        return defaults.get(name, [])

    async def _archive_worker_knowledge(self, name: str) -> None:
        """归档 Worker 的知识到 shared/knowledge。"""
        await AgtCLI.run("knowledge", "export", "--worker", name, timeout=30)


# ========================================================================== #
# 4. 自检
# ========================================================================== #

async def _self_test():
    """快速自检：验证 AgentTeams 平台连通性。"""
    print("=== AgentTeamsClient 自检 ===")

    client = AgentTeamsClient()

    # 1. 连通性
    try:
        ok = await client.ping()
        print(f"{'✓' if ok else '✘'} 平台连通性: {ok}")
    except Exception as e:
        print(f"✘ 平台连通性: {e}（可能 AgentTeams 未启动）")

    # 2. 状态
    try:
        status = await client.status()
        print(f"  Managers: {status['managers']}")
        print(f"  Workers: {status['workers']}")
        print(f"  Teams: {status['teams']}")
        print(f"  PDCA Workers Ready: {status['pdca_workers_ready']}")
    except Exception as e:
        print(f"  ✘ 状态查询失败: {e}")

    # 3. 数据模型
    wi = WorkerInfo(name="test", model="deepseek-v4-flash", state="Running")
    assert wi.name == "test"
    ti = TaskInfo(task_id="t-001", spec="test spec")
    assert ti.task_id == "t-001"
    print("✓ 数据模型")

    print("=== 自检完成 ===")


if __name__ == "__main__":
    asyncio.run(_self_test())