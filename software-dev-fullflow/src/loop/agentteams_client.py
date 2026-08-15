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

模块拆分说明：
  - agentteams_matrix.py — Matrix 协议客户端（MatrixClientMixin，官方 replay-task.sh 的 Python 版）
  - agentteams_yaml.py   — workers.yaml 解析（单一数据源）
  - agentteams_client.py — AgtCLI + 数据模型 + AgentTeamsClient（组合 mixin）
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import httpx

from .agentteams_matrix import MatrixClientMixin
from . import agentteams_yaml


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
class TaskCheckpoint:
    """任务进度检查点（断点续传用）。"""
    task_id: str
    seen_milestones: list[dict[str, str]] = field(default_factory=list)  # 历史所有里程碑（含重复，支持打回场景）
    bound_room_id: str = ""          # 任务归属的三方房间（admin+manager+worker），首次检测到里程碑后绑定
    baseline_ts: int = 0             # 时间窗口下界（任务创建时间，ms），过滤历史消息
    last_poll_ts: float = 0.0        # 上次轮询时间戳
    elapsed: float = 0.0             # 已累计耗时（秒）
    status: str = "running"          # running | completed | timeout

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TaskCheckpoint":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def latest_milestone_set(self) -> set[str]:
        """取每个里程碑词的最新一次出现（用于去重显示，但不丢失打回历史）。"""
        latest: dict[str, dict[str, str]] = {}
        for m in self.seen_milestones:
            latest[m["milestone"]] = m
        return set(latest.keys())


@dataclass
class TaskInfo:
    """任务运行时信息。"""

    task_id: str
    spec: str
    state: str = "pending"
    current_worker: str = ""
    milestone: str = ""
    created_at: float = field(default_factory=time.time)
    # 任务归属：Manager 在 DM 收到任务后会为该任务创建独立三方房间（admin+manager+worker），
    # 首次检测到里程碑后绑定此房间，后续只扫该房间，避免多任务串台。
    bound_room_id: str = ""
    # 隐藏标记：在发任务时附带，作为多任务时的兜底过滤
    task_tag: str = ""

    def elapsed(self) -> float:
        return time.time() - self.created_at

    def to_dict(self) -> dict:
        return asdict(self)


# ========================================================================== #
# 3. AgentTeamsClient —— 核心客户端
# ========================================================================== #

class AgentTeamsClient(MatrixClientMixin):
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

    # Task 隐藏标记正则（发消息时嵌入，用于多任务过滤兜底）
    TASK_TAG_RE = re.compile(r"<!-- TASK_ID:([a-f0-9-]+) -->")

    # Checkpoint 根目录（可覆盖）
    CHECKPOINT_DIR: Path | None = None

    def __init__(self, mode: str = "", checkpoint_dir: Path | None = None):
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
        # Checkpoint 目录优先级：显式参数 > 类变量 > 默认 ./shared/checkpoints
        if checkpoint_dir:
            self._checkpoint_dir = checkpoint_dir
        elif self.CHECKPOINT_DIR:
            self._checkpoint_dir = self.CHECKPOINT_DIR
        else:
            self._checkpoint_dir = Path.cwd() / "shared" / "checkpoints"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

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
          3. 向房间发任务消息（含 PDCA 流水线与里程碑协议 + 隐藏 task_id 标记）
          4. Manager（LLM 驱动）收到后自动匹配 Worker 并派单

        Args:
            spec: 任务规格（自然语言描述）
            pipeline: PDCA 流水线 Worker 列表（默认 6 个）
            manager: Manager 名称（Matrix 用户 localpart）

        Returns:
            TaskInfo with task_id (UUID) for tracking
        """
        pipeline = pipeline or self.PDCA_WORKERS
        self.manager_user = manager

        # GAP-06: 用 UUID4 生成唯一 task_id（短版 12 字符 hex，并发不冲突）
        task_id = uuid.uuid4().hex[:12]
        task_tag = f"<!-- TASK_ID:{task_id} -->"

        # 构造 PDCA 任务上下文（含里程碑握手协议 + 末尾隐藏 task_id 标记）
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
            f"- retrospector → RETROSPECT_DONE → @manager（闭环结束）\n\n"
            f"{task_tag}"
        )

        # 走 Matrix：登录 + 找/建 DM + 发任务
        self.matrix_login()
        room_id = self.ensure_manager_room()
        self.send_matrix_message(room_id, task_context)

        task_info = TaskInfo(
            task_id=task_id,
            spec=spec,
            created_at=time.time(),
            task_tag=task_tag,
        )

        # GAP-07: 创建初始 checkpoint（baseline_ts 用 ms 时间戳，对齐 Matrix origin_server_ts）
        baseline_ts = int(task_info.created_at * 1000)
        cp = TaskCheckpoint(
            task_id=task_id,
            baseline_ts=baseline_ts,
            last_poll_ts=time.time(),
        )
        self._save_checkpoint(cp)

        return task_info

    # ------------------------------------------------------------------ #
    # 任务监控（里程碑追踪，走 Matrix 房间消息）
    # ------------------------------------------------------------------ #

    # ---- Checkpoint 辅助（断点续传 GAP-07） ----

    def _checkpoint_path(self, task_id: str) -> Path:
        return self._checkpoint_dir / f"task-{task_id}.json"

    def _load_checkpoint(self, task_id: str) -> TaskCheckpoint | None:
        p = self._checkpoint_path(task_id)
        if not p.exists():
            return None
        try:
            return TaskCheckpoint.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def _save_checkpoint(self, cp: TaskCheckpoint) -> None:
        p = self._checkpoint_path(cp.task_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cp.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def clear_checkpoint(self, task_id: str) -> None:
        """任务正常结束后清理 checkpoint。"""
        p = self._checkpoint_path(task_id)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    @staticmethod
    def _adaptive_poll_interval(elapsed: float, base: float = 10.0) -> float:
        """自适应轮询间隔：初期密集、后期稀疏，减少空请求。

        策略：
          - 0~5min: base (默认 10s)
          - 5~15min: base×2 (20s)
          - 15~30min: base×3 (30s)
          - 30min+: base×6 (60s，模型慢也合理)
        """
        if elapsed < 300:
            return base
        if elapsed < 900:
            return base * 2
        if elapsed < 1800:
            return base * 3
        return base * 6

    # ---- 里程碑检测 ----

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

    async def detect_milestones(self, task_id: str) -> tuple[list[dict[str, str]], str]:
        """GAP-05: 带三层过滤的里程碑检测。

        三层过滤策略（避免多任务串台）：
          ① 时间窗口：只看 ts ≥ checkpoint.baseline_ts（任务创建后的消息，过滤历史闭环）
          ② 归属房间：首次检测到里程碑后绑定三方房间，后续只扫该房间
          ③ 任务 tag：消息里含 <!-- TASK_ID:xxx --> 隐藏标记时强匹配，多任务兜底

        Returns:
            (milestones_list, bound_room_id)
            milestones_list: [{milestone, worker, content, ts_ms, room_id}, ...]
                按时间升序，**包含重复里程碑**（用于打回场景：TEST_FAILED → FIX_APPLIED → TEST_PASSED 再次出现）
            bound_room_id: 本轮检测到里程碑后绑定的三方房间 ID（空字符串表示还未绑定）
        """
        cp = self._load_checkpoint(task_id)
        baseline_ts = cp.baseline_ts if cp else 0
        bound_room_id = cp.bound_room_id if cp else ""

        # 如果 Manager 回复任务时引用了原始消息，task_tag 可能被保留；否则靠房间+时间过滤
        task_tag = f"<!-- TASK_ID:{task_id} -->"

        milestones: list[dict[str, str]] = []

        milestone_patterns = [
            "TASK_SPEC_READY", "ROOT_CAUSE_FOUND", "FIX_APPLIED",
            "TEST_PASSED", "TEST_FAILED",
            "RELEASE_OK", "RELEASE_ROLLED_BACK",
            "RETROSPECT_DONE",
        ]

        # GAP-05 过滤②：已绑定归属房间 → 只扫这一个（99% 场景），避免扫历史房间串台
        try:
            self.matrix_login()
            if bound_room_id:
                rooms_to_scan = [bound_room_id]
            else:
                rooms_to_scan = self.get_joined_rooms()
        except RuntimeError as e:
            print(f"  ⚠ 检测里程碑失败: {e}")
            return milestones, bound_room_id

        admin_full = f"@{self.admin_user}:{self.matrix_domain}"
        new_bound = bound_room_id

        for room_id in rooms_to_scan:
            try:
                msgs = self.read_room_messages(room_id, 100)  # 稍多抓一些，避免漏
            except RuntimeError:
                continue
            for msg in msgs:
                # 过滤①：时间窗口——丢弃任务创建之前的消息
                if baseline_ts and msg.get("ts", 0) < baseline_ts:
                    continue
                # 排除 admin 自己发的消息（任务指令，非 Worker 产出）
                if admin_full in msg["sender"]:
                    continue
                # 过滤③：如果这条消息带 TASK_ID 隐藏标记，必须匹配当前 task_id（多任务并发兜底）
                tag_match = self.TASK_TAG_RE.search(msg["content"])
                if tag_match and tag_match.group(1) != task_id and task_tag not in msg["content"]:
                    continue
                for m_name in milestone_patterns:
                    if m_name in msg["content"]:
                        # 归属房间绑定：首次检测到里程碑后，记录这个三方房间
                        if not new_bound:
                            new_bound = room_id
                        sender = msg["sender"]
                        worker = sender.lstrip("@").split(":", 1)[0]
                        milestones.append({
                            "milestone": m_name,
                            "worker": worker,
                            "content": msg["content"][:200],
                            "ts_ms": str(msg.get("ts", 0)),
                            "room_id": room_id,
                        })
                        break

        # 按时间升序（保证里程碑顺序正确）
        milestones.sort(key=lambda x: int(x.get("ts_ms", "0") or 0))
        return milestones, new_bound

    async def wait_for_task(
        self,
        task_id: str,
        timeout: float = 600,
        poll_interval: float = 10,
    ) -> dict[str, Any]:
        """GAP-05/07: 自适应轮询 + Checkpoint 断点续传。

        关键改进：
          1. 启动时先加载 checkpoint，恢复之前已检测到的里程碑与累计耗时
          2. 轮询间隔随 elapsed 自适应（初期密后期疏）
          3. 每检测到**新**里程碑，立刻落盘 checkpoint（防止超时前功尽弃）
          4. seen_milestones 改为「全部历史」列表 + 「去重显示」集合，保留打回场景
          5. 超时时 checkpoint 标记为 timeout，下次 wait_for_task 可从断点继续

        Args:
            task_id: 任务 ID（UUID）
            timeout: 本轮等待允许的**增量**超时时间（秒），与 checkpoint 累计耗时无关
            poll_interval: 基础轮询间隔（秒），自适应基于此倍增

        Returns:
            {
                "status": "completed" | "timeout",
                "milestones": [...],   # 完整里程碑历史（可含重复，用于打回）
                "elapsed": float,      # 总累计耗时
                "resumed": bool,       # 是否从 checkpoint 恢复
                "checkpoint_path": str,
            }
        """
        # ---- GAP-07: 恢复 checkpoint ----
        cp = self._load_checkpoint(task_id)
        resumed = False
        if cp is None:
            cp = TaskCheckpoint(
                task_id=task_id,
                baseline_ts=int((time.time() - 60) * 1000),  # 兜底：1 分钟前
            )
            self._save_checkpoint(cp)
        else:
            resumed = True
            latest = cp.latest_milestone_set()
            if latest:
                print(f"  ♻ 从断点恢复，已达 {len(latest)} 个里程碑: {', '.join(sorted(latest))}")
            if cp.status == "completed":
                return {
                    "status": "completed",
                    "milestones": cp.seen_milestones,
                    "elapsed": cp.elapsed,
                    "resumed": True,
                    "checkpoint_path": str(self._checkpoint_path(task_id)),
                }

        # 本轮等待开始时间 + 累计耗时
        round_start = time.time()
        total_elapsed = cp.elapsed
        displayed: set[tuple[str, int]] = set()  # (milestone, ts_ms) → 避免同一个事件打印两次

        while True:
            # ---- 增量超时判定 ----
            round_elapsed = time.time() - round_start
            if round_elapsed >= timeout:
                cp.status = "timeout"
                cp.elapsed = total_elapsed
                cp.last_poll_ts = time.time()
                self._save_checkpoint(cp)
                print(f"  ⏱ 本轮等待超时（本轮 {round_elapsed:.0f}s，累计 {total_elapsed:.0f}s）。"
                      f"重新调用 wait_for_task('{task_id}') 可从断点继续。")
                return {
                    "status": "timeout",
                    "milestones": cp.seen_milestones,
                    "elapsed": total_elapsed,
                    "resumed": resumed,
                    "checkpoint_path": str(self._checkpoint_path(task_id)),
                }

            # ---- 自适应 sleep ----
            current_interval = self._adaptive_poll_interval(total_elapsed, base=poll_interval)
            # 用更短的分段 sleep，保证 timeout 到时立即响应（不会多等一个完整 interval）
            sleep_segment = min(current_interval, max(1.0, timeout - round_elapsed))
            await asyncio.sleep(sleep_segment)
            total_elapsed = cp.elapsed + (time.time() - round_start)

            # ---- 轮询里程碑 ----
            milestones, new_bound = await self.detect_milestones(task_id)

            # ---- 与 checkpoint 合并：按 (milestone, ts_ms) 去重，保留历史 ----
            existing_keys = {
                (m["milestone"], m.get("ts_ms", "0"))
                for m in cp.seen_milestones
            }
            newly_added = False
            for m in milestones:
                key = (m["milestone"], m.get("ts_ms", "0"))
                if key in existing_keys:
                    continue
                cp.seen_milestones.append(m)
                existing_keys.add(key)
                newly_added = True
                # 打印新里程碑
                if key not in displayed:
                    displayed.add(key)
                    print(f"  [AgentTeams] 检测到里程碑: {m['milestone']} ← @{m['worker']}")

            # ---- 归属房间更新 ----
            if new_bound and new_bound != cp.bound_room_id:
                cp.bound_room_id = new_bound
                newly_added = True

            # ---- 有任何更新就落盘 checkpoint（保证崩溃/超时不丢进度） ----
            if newly_added:
                cp.last_poll_ts = time.time()
                cp.elapsed = total_elapsed
                self._save_checkpoint(cp)

            # ---- 判定闭环完成 ----
            if "RETROSPECT_DONE" in cp.latest_milestone_set():
                cp.status = "completed"
                cp.elapsed = total_elapsed
                self._save_checkpoint(cp)
                self.clear_checkpoint(task_id)  # 正常结束清理
                return {
                    "status": "completed",
                    "milestones": cp.seen_milestones,
                    "elapsed": total_elapsed,
                    "resumed": resumed,
                    "checkpoint_path": "",
                }

            # 打回场景（TEST_FAILED / RELEASE_ROLLED_BACK）：继续等待重新 FIX_APPLIED → TEST_PASSED
            # （无需特殊处理，因为 seen_milestones 保留全部历史 + 打印时按 key 去重）

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
        """人工审批发布。"""
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
        """请求人工介入。"""
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
        """向指定 Worker 发送人工反馈。"""
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
        """人工覆盖 Worker 状态。"""
        return await self.update_worker(worker_name, state=new_state)

    async def get_human_tasks(self) -> list[dict[str, Any]]:
        """获取所有需要人工介入的任务。"""
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

    # ---- workers.yaml 解析（委托给 agentteams_yaml 模块） ----

    async def apply_workers_yaml(self, yaml_path: str = "") -> bool:
        """通过 agt apply -f 批量创建/更新所有 Worker。

        这是推荐的 Worker 生命周期管理方式：workers.yaml 是单一数据源，
        AgentTeams 平台通过声明式 apply 管理 Worker 的创建和更新。

        Args:
            yaml_path: workers.yaml 的路径（默认 src/agentteams/workers.yaml）

        Returns:
            True 如果 apply 成功
        """
        path = yaml_path or str(agentteams_yaml.get_workers_yaml_path())
        if not Path(path).exists():
            print(f"  ⚠ workers.yaml 不存在: {path}")
            return False

        # 在 controller 容器内执行 apply
        docker_path = "/tmp/workers.yaml"
        # 先 cp 文件进容器
        subprocess.run(
            ["docker", "cp", path, f"{AgtCLI.CONTROLLER}:{docker_path}"],
            capture_output=True, timeout=30,
        )

        code, stdout, stderr = await AgtCLI.run("apply", "-f", docker_path, timeout=30)
        if code == 0:
            print(f"  ✓ workers.yaml apply 成功")
            # 清除缓存，下次重新解析
            agentteams_yaml.clear_cache()
            return True
        print(f"  ✘ workers.yaml apply 失败: {stderr[:200]}")
        return False

    async def ensure_pdca_workers(self, workers_dir: str) -> dict[str, bool]:
        """确保 6 个 PDCA Worker 都已创建并 Running。

        优先使用 workers.yaml apply（声明式批量创建），
        fallback 到逐个创建（使用 workers.yaml 解析的 skills/MCP）。

        Args:
            workers_dir: SOUL.md 文件所在目录（如 src/agentteams/workers/）

        Returns:
            {worker_name: is_ready}
        """
        existing = await self._list_resource("workers")
        results = {}

        # 检查是否所有 Worker 都已存在
        all_exist = all(name in existing for name in self.PDCA_WORKERS)
        if all_exist:
            return {name: True for name in self.PDCA_WORKERS}

        # 优先尝试 workers.yaml apply（声明式批量创建）
        yaml_path = str(agentteams_yaml.get_workers_yaml_path())
        if Path(yaml_path).exists():
            print("  → 使用 workers.yaml apply 批量创建 Worker...")
            ok = await self.apply_workers_yaml(yaml_path)
            if ok:
                # 重新检查
                existing = await self._list_resource("workers")
                for name in self.PDCA_WORKERS:
                    results[name] = name in existing
                return results

        # Fallback: 逐个创建（使用 workers.yaml 解析的 skills/MCP）
        print("  → workers.yaml apply 不可用，逐个创建 Worker...")
        for name in self.PDCA_WORKERS:
            if name in existing:
                results[name] = True
                continue

            soul_path = Path(workers_dir) / name / "SOUL.md"
            if not soul_path.exists():
                results[name] = False
                continue

            skills = agentteams_yaml.get_worker_skills(name)
            mcp = agentteams_yaml.get_worker_mcp(name)

            ok = await self.create_worker(
                name=name,
                soul_file=str(soul_path),
                skills=skills,
                mcp_servers=mcp,
            )
            results[name] = ok

        return results

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
        print(f"✓ 平台连通性: {'OK' if ok else 'FAIL'}")
    except Exception as e:
        print(f"  ⚠ 连通性检查异常: {e}")

    # 2. 获取状态
    try:
        status = await client.status()
        print(f"✓ 平台状态: managers={status['managers']}, workers={status['workers']}")
    except Exception as e:
        print(f"  ⚠ 状态检查异常: {e}")

    await client.close()
    print("=== AgentTeamsClient 自检完成 ===")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_self_test())
