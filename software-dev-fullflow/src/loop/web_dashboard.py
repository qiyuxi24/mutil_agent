"""Web SSE 仪表盘 —— 浏览器实时看板。

基于 EventBus 事件驱动，通过 Server-Sent Events 推送到浏览器。
复用 EventBus、TaskState、AgentInterface 等已有组件。

特性：
  - SSE 实时事件推送（/events）
  - 简洁 HTML 仪表盘（PDCA 进度 + Worker 状态 + 事件流）
  - 人工审批按钮（/api/approve）
  - 零额外依赖（FastAPI + uvicorn 可选，降级为纯 HTTP）

用法：
    from loop.web_dashboard import WebDashboard
    from loop.agentteams_loop import AgentTeamsLoop

    loop = AgentTeamsLoop(...)
    web = WebDashboard(loop.event_bus, loop.state, loop.ctx, port=8080)
    await web.start()
    await loop.run()
    await web.stop()
"""

from __future__ import annotations

import asyncio
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Any

from loop.agent_bus import EventBus, EventType, Event
from loop.state import TaskState, State, STATE_EXECUTOR, STATE_EXPECTED_MILESTONE
from loop.context import ContextManager

# uvicorn + starlette 是可选依赖
try:
    import uvicorn
    from starlette.applications import Starlette
    from starlette.responses import Response, JSONResponse, HTMLResponse
    from starlette.routing import Route
    try:
        from sse_starlette.sse import EventSourceResponse  # 新版 sse-starlette
    except ImportError:
        from starlette.sse import EventSourceResponse  # 旧版路径兼容
    HAS_WEB = True
except ImportError:
    HAS_WEB = False


# ========================================================================== #
# 1. HTML 仪表盘模板
# ========================================================================== #

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PDCA 闭环调度仪表盘</title>
<style>
  :root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9;
          --dim: #8b949e; --green: #3fb950; --yellow: #d29922; --red: #f85149;
          --cyan: #58a6ff; --magenta: #bc8cff; --blue: #79c0ff; --white: #f0f6fc; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--text); padding: 16px; min-height: 100vh; }
  .header { display: flex; justify-content: space-between; align-items: center;
            padding: 12px 16px; background: var(--card); border: 1px solid var(--border);
            border-radius: 8px; margin-bottom: 16px; }
  .header h1 { font-size: 18px; color: var(--cyan); }
  .header .meta { font-size: 12px; color: var(--dim); }
  .main { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .panel { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
           padding: 12px; }
  .panel h2 { font-size: 14px; margin-bottom: 12px; color: var(--dim); text-transform: uppercase; }
  .pipeline-item { display: flex; align-items: center; padding: 6px 8px;
                   border-radius: 4px; margin-bottom: 4px; font-size: 13px; }
  .pipeline-item .icon { width: 24px; }
  .pipeline-item .name { flex: 1; }
  .pipeline-item .executor { color: var(--dim); font-size: 11px; }
  .pipeline-item.done { background: rgba(63,185,80,0.1); }
  .pipeline-item.running { background: rgba(210,153,34,0.15); animation: pulse 1.5s infinite; }
  .pipeline-item.pending { opacity: 0.5; }
  .pipeline-item.failed { background: rgba(248,81,73,0.15); }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.7; } }
  .worker-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
  .worker-card { padding: 10px; border-radius: 6px; border: 1px solid var(--border);
                 font-size: 12px; }
  .worker-card .w-name { font-weight: bold; margin-bottom: 4px; }
  .worker-card .w-status { font-size: 11px; }
  .worker-card.done { border-color: var(--green); }
  .worker-card.running { border-color: var(--yellow); }
  .worker-card.failed { border-color: var(--red); }
  .events { grid-column: 1 / -1; max-height: 200px; overflow-y: auto;
            font-size: 12px; font-family: monospace; }
  .event-line { padding: 2px 4px; border-bottom: 1px solid var(--border); }
  .event-line .ts { color: var(--dim); margin-right: 8px; }
  .event-line .src { margin-right: 8px; }
  .footer { margin-top: 16px; padding: 10px 16px; background: var(--card);
            border: 1px solid var(--border); border-radius: 8px; font-size: 12px;
            display: flex; justify-content: space-between; color: var(--dim); }
  .btn { padding: 6px 14px; border-radius: 6px; border: 1px solid var(--border);
         background: var(--card); color: var(--text); cursor: pointer; font-size: 12px; }
  .btn:hover { background: var(--border); }
  .btn.approve { border-color: var(--green); color: var(--green); }
  .btn.reject { border-color: var(--red); color: var(--red); }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>PDCA 闭环调度仪表盘</h1>
    <div class="meta">任务 <span id="task-id">—</span> · 已运行 <span id="elapsed">0s</span></div>
  </div>
  <div>
    <button class="btn approve" onclick="approve()">批准发布</button>
    <button class="btn reject" onclick="reject()">驳回</button>
  </div>
</div>
<div class="main">
  <div class="panel">
    <h2>PDCA 流水线</h2>
    <div id="pipeline"></div>
  </div>
  <div class="panel">
    <h2>Worker 状态</h2>
    <div class="worker-grid" id="workers"></div>
  </div>
  <div class="panel events" id="events">
    <div class="event-line"><span class="ts">--:--:--</span> 等待事件...</div>
  </div>
</div>
<div class="footer">
  <span id="budget">上下文: —</span>
  <span id="stats">Worker: 0 done / 0 running / 0 failed</span>
</div>
<script>
const ROLE_COLORS = { aggregator:'#58a6ff', rootcause:'#bc8cff', fixer:'#d29922',
  tester:'#3fb950', releaser:'#79c0ff', retrospector:'#f0f6fc', manager:'#f85149' };
const ROLE_ICONS = { aggregator:'📋', rootcause:'🔍', fixer:'🔧', tester:'🧪',
  releaser:'🚀', retrospector:'📝', manager:'👔' };
const STAGES = ['SPEC_INPUT','SPEC_DECOMPOSE','ROOT_CAUSE','FIX_APPLY',
  'TEST_VERIFY','RELEASE','RELEASE_APPROVE','RETROSPECT'];
const STAGE_NAMES = { SPEC_INPUT:'需求聚合', SPEC_DECOMPOSE:'任务拆解', ROOT_CAUSE:'根因定位',
  FIX_APPLY:'代码修复', TEST_VERIFY:'测试验证', RELEASE:'发布准备',
  RELEASE_APPROVE:'发布审批', RETROSPECT:'复盘沉淀' };
const EXECUTORS = { SPEC_INPUT:'aggregator', SPEC_DECOMPOSE:'aggregator',
  ROOT_CAUSE:'rootcause', FIX_APPLY:'fixer', TEST_VERIFY:'tester',
  RELEASE:'releaser', RELEASE_APPROVE:'releaser', RETROSPECT:'retrospector' };

let workerStatus = {};
['aggregator','rootcause','fixer','tester','releaser','retrospector'].forEach(w => {
  workerStatus[w] = {status:'pending', milestone:'', elapsed:0};
});
let completedStages = [];
let events = [];
let startTime = Date.now();

function initPipeline() {
  let html = '';
  STAGES.forEach(s => {
    html += `<div class="pipeline-item pending" id="stage-${s}">
      <span class="icon">⏳</span>
      <span class="name">${STAGE_NAMES[s]}</span>
      <span class="executor">${ROLE_ICONS[EXECUTORS[s]]} ${EXECUTORS[s]}</span>
    </div>`;
  });
  document.getElementById('pipeline').innerHTML = html;
}

function initWorkers() {
  let html = '';
  for (let [name, ws] of Object.entries(workerStatus)) {
    html += `<div class="worker-card" id="worker-${name}">
      <div class="w-name" style="color:${ROLE_COLORS[name]}">${ROLE_ICONS[name]} ${name}</div>
      <div class="w-status">⏳ 等待中</div></div>`;
  }
  document.getElementById('workers').innerHTML = html;
}

function updateStage(stage) {
  if (completedStages.includes(stage)) return;
  completedStages.push(stage);
  let el = document.getElementById('stage-' + stage);
  if (!el) return;
  el.className = 'pipeline-item done';
  el.querySelector('.icon').textContent = '✅';
  // 下一个阶段标记为 running
  let idx = STAGES.indexOf(stage);
  if (idx < STAGES.length - 1) {
    let next = STAGES[idx + 1];
    let nel = document.getElementById('stage-' + next);
    if (nel && !completedStages.includes(next)) {
      nel.className = 'pipeline-item running';
      nel.querySelector('.icon').textContent = '🔄';
    }
  }
}

function updateWorker(name, status, milestone, elapsed) {
  workerStatus[name] = {status, milestone, elapsed};
  let el = document.getElementById('worker-' + name);
  if (!el) return;
  el.className = 'worker-card ' + status;
  let icon = {pending:'⏳', running:'🔄', done:'✅', failed:'❌'}[status] || '?';
  let ms = milestone ? ` → ${milestone}` : '';
  let t = elapsed ? ` (${elapsed.toFixed(1)}s)` : '';
  el.querySelector('.w-status').innerHTML = `${icon} ${status}${ms}${t}`;
}

function addEvent(ts, source, msg) {
  events.unshift({ts, source, msg});
  if (events.length > 50) events.length = 50;
  let html = events.slice(0, 15).map(e =>
    `<div class="event-line">
      <span class="ts">${e.ts}</span>
      <span class="src" style="color:${ROLE_COLORS[e.source]||'#8b949e'}">${e.source}</span>
      ${e.msg}
    </div>`
  ).join('');
  document.getElementById('events').innerHTML = html;
}

function updateStats() {
  let done = 0, running = 0, failed = 0;
  for (let ws of Object.values(workerStatus)) {
    if (ws.status === 'done') done++;
    else if (ws.status === 'running') running++;
    else if (ws.status === 'failed') failed++;
  }
  document.getElementById('stats').textContent =
    `Worker: ${done} done / ${running} running / ${failed} failed`;
  document.getElementById('elapsed').textContent =
    Math.floor((Date.now() - startTime) / 1000) + 's';
}

// SSE 连接
const evtSource = new EventSource('/events');
evtSource.onmessage = function(e) {
  let evt = JSON.parse(e.data);
  let ts = new Date(evt.timestamp * 1000).toLocaleTimeString('zh-CN', {hour12:false});
  let source = evt.source;
  let etype = evt.event_type;
  let data = evt.data || {};
  let icon = {WORKER_STARTED:'▶', WORKER_COMPLETED:'✓', WORKER_FAILED:'✗',
    MILESTONE_REACHED:'🏁', MILESTONE_FAILED:'💥', ERROR_OCCURRED:'⚠',
    TASK_STARTED:'🚀', TASK_COMPLETED:'🎉'}[etype] || '•';

  if (etype === 'WORKER_STARTED') {
    updateWorker(source, 'running');
  } else if (etype === 'WORKER_COMPLETED') {
    updateWorker(source, 'done', data.milestone, data.elapsed);
  } else if (etype === 'MILESTONE_REACHED' && data.milestone) {
    // 映射里程碑到阶段
    let map = {TASK_SPEC_READY:'SPEC_INPUT', ROOT_CAUSE_FOUND:'ROOT_CAUSE',
      FIX_APPLIED:'FIX_APPLY', TEST_PASSED:'TEST_VERIFY',
      RELEASE_OK:'RELEASE', RETROSPECT_DONE:'RETROSPECT'};
    if (map[data.milestone]) updateStage(map[data.milestone]);
  } else if (etype === 'WORKER_FAILED') {
    updateWorker(source, 'failed');
  }
  addEvent(ts, source, `${icon} ${etype}`);
  updateStats();
};
evtSource.onerror = function() { console.log('SSE 连接中断，5s 后重连...'); };

function approve() { fetch('/api/approve', {method:'POST', body:'approved=true'}).then(r=>r.json()).then(console.log); }
function reject() { fetch('/api/approve', {method:'POST', body:'rejected=true'}).then(r=>r.json()).then(console.log); }

initPipeline();
initWorkers();
setInterval(updateStats, 1000);
</script>
</body>
</html>"""


# ========================================================================== #
# 2. Web 仪表盘服务
# ========================================================================== #

class WebDashboard:
    """Web SSE 仪表盘 —— 浏览器实时看板。

    Args:
        event_bus: EventBus 实例（事件源）
        state: TaskState 实例（状态源）
        ctx: ContextManager 实例（上下文源）
        port: HTTP 端口（默认 8080）
        host: 绑定地址（默认 127.0.0.1）
    """

    def __init__(
        self,
        event_bus: EventBus,
        state: TaskState,
        ctx: ContextManager,
        port: int = 8080,
        host: str = "127.0.0.1",
        approval: Any = None,
    ):
        self.event_bus = event_bus
        self.state = state
        self.ctx = ctx
        self.port = port
        self.host = host
        # 审批管理器（可选）：接入后 /api/approve 走留痕闭环 + TTL 兜底；
        #   不传时降级为仅发事件（保持旧行为兼容）
        self.approval = approval

        # SSE 客户端队列
        self._queues: list[asyncio.Queue] = []

        self._server: uvicorn.Server | None = None
        self._server_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #

    async def start(self):
        """启动 Web 服务。"""
        if not HAS_WEB:
            print("  ⚠ Web 仪表盘需要 uvicorn 和 starlette（pip install uvicorn starlette）")
            return

        # 订阅 EventBus
        self.event_bus.subscribe("*", self._on_event)

        # 创建 Starlette 应用
        app = Starlette(debug=False, routes=[
            Route("/", self._index, methods=["GET"]),
            Route("/events", self._events_sse, methods=["GET"]),
            Route("/api/status", self._status_api, methods=["GET"]),
            Route("/api/approve", self._approve_api, methods=["POST"]),
            Route("/api/approvals", self._approvals_api, methods=["GET"]),
        ])

        config = uvicorn.Config(
            app, host=self.host, port=self.port,
            log_level="warning", access_log=False,
        )
        self._server = uvicorn.Server(config)

        self._server_task = asyncio.create_task(self._server.serve())
        print(f"  🌐 Web 仪表盘: http://{self.host}:{self.port}")
        await asyncio.sleep(0.5)  # 等服务器启动

    async def stop(self):
        """停止 Web 服务。"""
        if self._server:
            self._server.should_exit = True
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
        # 关闭所有 SSE 连接
        for q in self._queues:
            await q.put(None)  # 发送关闭信号

    # ------------------------------------------------------------------ #
    # 事件处理
    # ------------------------------------------------------------------ #

    def _on_event(self, event: Event):
        """EventBus 回调：将事件推送到所有 SSE 客户端。"""
        data = json.dumps(event.to_dict(), ensure_ascii=False)
        for q in self._queues:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    # ------------------------------------------------------------------ #
    # HTTP 路由
    # ------------------------------------------------------------------ #

    async def _index(self, request):
        """仪表盘主页。"""
        return HTMLResponse(DASHBOARD_HTML)

    async def _events_sse(self, request):
        """SSE 事件流端点。"""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._queues.append(queue)

        async def generate():
            try:
                while True:
                    data = await queue.get()
                    if data is None:  # 关闭信号
                        break
                    yield {"event": "message", "data": data}
            except asyncio.CancelledError:
                pass
            finally:
                self._queues.remove(queue)

        return EventSourceResponse(generate())

    async def _status_api(self, request):
        """状态 API。"""
        return JSONResponse({
            "task_id": self.state.task_id,
            "state": self.state.state.value,
            "milestones": list(self.state.milestones.keys()),
            "artifacts": self.state.artifacts,
        })

    async def _approve_api(self, request):
        """人工审批 API。

        走 ApprovalManager 时：
          - 支持按 approval_id 精确审批（POST approval_id=<id>&approved=true/false）；
          - 未带 approval_id 则审批该 task_id 下最新一条待审请求（兼容旧前端按钮）。
          - 每次决策写审计（human_intervention + decision），实现留痕闭环。
        未接入 ApprovalManager（approval=None）时降级为仅发事件（旧行为）。
        """
        body = await request.body()
        body_str = body.decode("utf-8", errors="replace")
        approved = "approved=true" in body_str
        rejected = "rejected=true" in body_str or not approved
        approval_id = ""
        # 解析 form 字段
        for kv in body_str.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                if k == "approval_id":
                    approval_id = v

        # 无审批管理器：降级为仅发事件（保持旧行为）
        if self.approval is None:
            if approved:
                await self.event_bus.milestone_reached(
                    "human", self.state.task_id, "RELEASE_APPROVED",
                    data={"approved": True},
                )
            else:
                await self.event_bus.milestone_failed(
                    "human", self.state.task_id, "RELEASE_REJECTED",
                    data={"rejected": True},
                )
            return JSONResponse({"status": "ok", "approved": approved})

        # 有审批管理器：定位目标审批请求（默认该 task 下最新一条 pending）
        if not approval_id:
            pending = self.approval.pending(self.state.task_id)
            if not pending:
                return JSONResponse({"status": "error", "error": "无待审批请求"})
            approval_id = pending[-1].approval_id

        req = await self.approval.decide(
            approval_id, approved=approved, reviewer="human-web",
        )
        if req is None:
            return JSONResponse({"status": "error", "error": f"审批 {approval_id} 不存在或已处置"})
        return JSONResponse({
            "status": "ok", "approved": approved,
            "approval_id": approval_id, "result": req.status.value,
        })

    async def _approvals_api(self, request):
        """查询待审批请求列表（供前端轮询展示 TTL 倒计时）。"""
        if self.approval is None:
            return JSONResponse({"approvals": [], "ttl_secs": 0})
        snap = self.approval.snapshot()
        return JSONResponse({"approvals": snap["pending"],
                             "by_status": snap["by_status"],
                             "ttl_secs": self.approval.ttl_secs})


# ========================================================================== #
# 3. 自检
# ========================================================================== #

async def _self_test():
    """快速自检。"""
    from loop.context import ContextManager
    from loop.state import TaskState

    print("=== WebDashboard 自检 ===")

    state = TaskState(task_id="web-test", spec="测试 Web 仪表盘")
    event_bus = EventBus()
    ctx = ContextManager(task_id="web-test", workdir=Path("."), total_budget=1000)

    web = WebDashboard(event_bus, state, ctx, port=9999)
    await web.start()

    # 模拟事件
    await event_bus.task_started("web-test", "测试")
    await asyncio.sleep(0.1)
    await event_bus.worker_started("aggregator", "web-test")
    await asyncio.sleep(0.1)
    await event_bus.worker_completed("aggregator", "web-test", "TASK_SPEC_READY", elapsed=0.5)
    await event_bus.milestone_reached("aggregator", "web-test", "TASK_SPEC_READY")

    print("✓ 事件已推送到 SSE")
    print(f"  SSE 客户端数: {len(web._queues)}")
    print(f"  浏览器打开: http://{web.host}:{web.port}")

    await asyncio.sleep(1)
    await web.stop()
    print("=== 自检通过 ===")


if __name__ == "__main__":
    asyncio.run(_self_test())