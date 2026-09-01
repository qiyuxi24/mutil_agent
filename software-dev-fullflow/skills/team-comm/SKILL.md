---
name: team-comm
description: 员工间通信：在团队内定向请求/应答（如 Tester 向 Backend 要开发日志）、发送消息/反馈/告警。触发词：通信、请求、要日志、@后端、@前端、send、request、reply、ask、问。
assign_when: 任何 Worker 需要与其他员工协作、请求信息、获取上下文时分配。
---

# Skill: team-comm

员工之间直接通信的统一入口（底层走 `AgentBus` / Matrix @mention）。让"测试问后端要开发日志"这类员工间协作成为显式能力。

## 支持的操作

| 操作 | 用途 | 对应底层 |
|------|------|---------|
| `send` | 发一条普通消息给某员工 | `AgentBus.publish` / Matrix @mention |
| `request` | 定向请求信息（返回 request_id） | `AgentBus.request` |
| `reply` | 应答某条请求（带 request_id） | `AgentBus.reply` |
| `feedback` | 反馈/打回（下游对上游产物） | `AgentBus.feedback` |
| `alert` | 告警（异常/超时/质量不达标） | `AgentBus.alert` |

## 输入

- 操作：`send` / `request` / `reply` / `feedback` / `alert`
- 发送者：`--from <sender>`（当前 Worker）
- 接收者：`--to <receiver>`（目标员工，如 backend / frontend / fixer）
- 内容：`--content <文本>`（request 时为请求内容）
- 任务：`--task <task_id>`
- 应答：`--reply-to <request_id>`（reply 时必填）
- 请求类型：`--kind <kind>`（可选，如 log / api_contract / repro）

## 执行步骤

1. **请求信息**（如 Tester 要 Backend 的开发日志）：
   ```bash
   python skills/team-comm/scripts/comm_cli.py request \
     --from tester --to backend --task T-0001 \
     --content "请提供 POST /api/submit 接口的开发日志" --kind log
   # → 返回 request_id: req-1
   ```
2. **应答请求**（Backend 收到后回复）：
   ```bash
   python skills/team-comm/scripts/comm_cli.py reply \
     --from backend --to tester --task T-0001 \
     --reply-to req-1 --content "接口日志已写入 /tmp/server.log"
   ```
3. **发送消息 / 反馈 / 告警**：类似参数，操作换成对应动词。

## 输出

- `request`：返回 `request_id`（供 reply 关联）
- `send` / `reply` / `feedback` / `alert`：返回发送结果（OK / 未授权）

## 依赖工具

- L1 基座：`AgentBus`（`src/loop/agent_bus.py`，request-reply 定向通信）
- 外部依赖：无（纯标准库）

## 失败处理

- 发送者→接收者未授权 → 返回 `UNAUTHORIZED`（需 Leader 授权）
- 接收者不在团队 → 返回 `RECEIVER_NOT_FOUND`
- reply 的 request_id 不存在 → 返回 `REQUEST_NOT_FOUND`

## 安全边界

- 通信受 `channelPolicy` 约束（只有授权 peer 可通信）
- 请求/应答内容会留痕（历史可审计）
- 不传递敏感凭据

## 复用价值

- 所有 Worker 统一挂载 `team-comm`，实现员工间协作
- 解决"测试问后端要开发日志"等跨角色信息获取需求
- 与 Matrix @mention 兼容，天然留痕

## 协同关系

- **并行**：`agent-memory`（记忆）与本 Skill（通信）都是通用能力，所有 Worker 挂载
- **上游**：Leader 编排时协调员工间通信
- **底层**：AgentBus request-reply / Matrix @mention

## 里程碑

- 请求成功：输出 `TEAM_REQUEST_SENT`（含 request_id）
- 应答成功：输出 `TEAM_REPLY_SENT`
