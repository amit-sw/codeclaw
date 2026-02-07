from __future__ import annotations

import argparse
import subprocess

import uvicorn

from openclaw.approvals import ApprovalsStore
from openclaw.config import load_config
from openclaw.gateway_client import ws_request_sync
from openclaw.doctor import run_doctor


def _ws_url(config):
    return f"ws://{config.gateway.host}:{config.gateway.port}/ws"


def cmd_gateway_run(args):
    config = load_config(args.config)
    uvicorn.run("openclaw.gateway:app", host=config.gateway.host, port=config.gateway.port)


def cmd_agent_send(args):
    config = load_config(args.config)
    result = ws_request_sync(
        _ws_url(config),
        config.gateway.token,
        config.gateway.password,
        "session.send",
        {
            "agent_id": args.agent,
            "session_id": args.session,
            "message": args.message,
            "channel": "cli",
            "peer": args.peer,
        },
    )
    print(result.get("assistant_message", ""))


def cmd_sessions_list(args):
    config = load_config(args.config)
    result = ws_request_sync(
        _ws_url(config),
        config.gateway.token,
        config.gateway.password,
        "session.list",
        {"agent_id": args.agent},
    )
    for session in result.get("sessions", []):
        print(f"{session['id']}\t{session['title']}")


def cmd_sessions_view(args):
    config = load_config(args.config)
    result = ws_request_sync(
        _ws_url(config),
        config.gateway.token,
        config.gateway.password,
        "session.events",
        {"agent_id": args.agent, "session_id": args.session},
    )
    for event in result.get("events", []):
        role = event.get("role")
        content = event.get("content")
        print(f"[{role}] {content}")


def cmd_doctor(args):
    exit(run_doctor(args.config))


def cmd_test(args):
    result = subprocess.run(["pytest", "-q"])
    raise SystemExit(result.returncode)


def cmd_tools_allow(args):
    config = load_config(args.config)
    approvals = ApprovalsStore(config.tools.approvals_path)
    approvals.allow(args.tool)


def build_parser():
    parser = argparse.ArgumentParser(prog="openclaw")
    parser.add_argument("--config", default=None)

    sub = parser.add_subparsers(dest="command")

    gateway = sub.add_parser("gateway")
    gateway_sub = gateway.add_subparsers(dest="subcommand")
    gateway_run = gateway_sub.add_parser("run")
    gateway_run.set_defaults(func=cmd_gateway_run)

    agent = sub.add_parser("agent")
    agent_sub = agent.add_subparsers(dest="subcommand")
    agent_send = agent_sub.add_parser("send")
    agent_send.add_argument("--agent", required=True)
    agent_send.add_argument("--message", required=True)
    agent_send.add_argument("--session", default=None)
    agent_send.add_argument("--peer", default="local")
    agent_send.set_defaults(func=cmd_agent_send)

    sessions = sub.add_parser("sessions")
    sessions_sub = sessions.add_subparsers(dest="subcommand")
    sessions_list = sessions_sub.add_parser("list")
    sessions_list.add_argument("--agent", required=True)
    sessions_list.set_defaults(func=cmd_sessions_list)
    sessions_view = sessions_sub.add_parser("view")
    sessions_view.add_argument("--agent", required=True)
    sessions_view.add_argument("--session", required=True)
    sessions_view.set_defaults(func=cmd_sessions_view)

    doctor = sub.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    test = sub.add_parser("test")
    test.set_defaults(func=cmd_test)

    tools = sub.add_parser("tools")
    tools_sub = tools.add_subparsers(dest="subcommand")
    tools_allow = tools_sub.add_parser("allow")
    tools_allow.add_argument("tool")
    tools_allow.set_defaults(func=cmd_tools_allow)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(1)
    args.func(args)


if __name__ == "__main__":
    main()
