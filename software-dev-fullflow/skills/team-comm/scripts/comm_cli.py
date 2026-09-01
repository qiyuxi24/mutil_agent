#!/usr/bin/env python3
"""comm_cli.py — 员工间通信命令行入口。

为 `skills/team-comm` Skill 提供可执行能力：
  定向请求/应答、发送消息/反馈/告警。

用法（在项目根目录，或把 src/ 加入 PYTHONPATH）：
  python skills/team-comm/scripts/comm_cli.py \
      request --from tester --to backend --task T-0001 \
      --content "请提供 POST /api/submit 接口的开发日志" --kind log
  python skills/team-comm/scripts/comm_cli.py \
      reply --from backend --to tester --task T-0001 \
      --reply-to req-1 --content "接口日志已写入 /tmp/server.log"
  python skills/team-comm/scripts/comm_cli.py send \
      --from leader --to tester --task T-0001 --content "请开始验证"

退出码：0=成功；1=执行错误；2=参数错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接运行：把项目 src/ 加入 sys.path
_PROJECT = Path(__file__).resolve().parent.parent.parent.parent
_SRC = _PROJECT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from loop.agent_bus import AgentBus, AgentMessage, MessageType  # noqa: E402


def _add_common(parser: argparse.ArgumentParser) -> None:
    """给子命令添加通用参数（sender/receiver/task）。"""
    parser.add_argument("--from", dest="sender", required=True, help="发送者 Worker")
    parser.add_argument("--to", dest="receiver", required=True, help="接收者 Worker")
    parser.add_argument("--task", default="", help="任务 ID")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="员工间通信命令行")
    sub = parser.add_subparsers(dest="op", required=True)

    p_send = sub.add_parser("send", help="发送普通消息")
    _add_common(p_send)
    p_send.add_argument("--content", required=True)

    p_request = sub.add_parser("request", help="定向请求信息")
    _add_common(p_request)
    p_request.add_argument("--content", required=True)
    p_request.add_argument("--kind", default="", help="请求类型（log/api_contract/repro）")

    p_reply = sub.add_parser("reply", help="应答某条请求")
    _add_common(p_reply)
    p_reply.add_argument("--reply-to", dest="request_id", required=True)
    p_reply.add_argument("--content", required=True)

    p_feedback = sub.add_parser("feedback", help="反馈/打回")
    _add_common(p_feedback)
    p_feedback.add_argument("--content", required=True)

    p_alert = sub.add_parser("alert", help="告警")
    _add_common(p_alert)
    p_alert.add_argument("--content", required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    bus = AgentBus()

    # 授权当前发送者 → 接收者（演示环境默认全授权；真实环境由 Leader/channelPolicy 决定）
    bus.authorize(args.sender, args.receiver)

    if args.op == "request":
        request_id = bus.request(args.sender, args.receiver, args.task,
                                 args.content, kind=args.kind)
        if not request_id:
            print(json.dumps({"status": "UNAUTHORIZED", "sender": args.sender,
                              "receiver": args.receiver}, ensure_ascii=False))
            return 1
        print(json.dumps({"status": "OK", "milestone": "TEAM_REQUEST_SENT",
                          "request_id": request_id}, ensure_ascii=False))
        return 0

    if args.op == "reply":
        ok = bus.reply(args.sender, args.receiver, args.task,
                       args.request_id, args.content)
        if not ok:
            print(json.dumps({"status": "UNAUTHORIZED"}, ensure_ascii=False))
            return 1
        print(json.dumps({"status": "OK", "milestone": "TEAM_REPLY_SENT",
                          "request_id": args.request_id}, ensure_ascii=False))
        return 0

    if args.op == "send":
        ok = bus.publish(AgentMessage(
            msg_id="send-1", msg_type=MessageType.QUERY,
            sender=args.sender, receiver=args.receiver,
            content=args.content, task_id=args.task,
        ))
    elif args.op == "feedback":
        ok = bus.feedback(args.sender, args.receiver, args.task, args.content)
    elif args.op == "alert":
        ok = bus.alert(args.sender, args.receiver, args.task, args.content)
    else:
        print(json.dumps({"status": "ERROR", "reason": f"未知操作: {args.op}"}))
        return 1

    if not ok:
        print(json.dumps({"status": "UNAUTHORIZED"}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "OK", "milestone": f"TEAM_{args.op.upper()}_SENT"},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
