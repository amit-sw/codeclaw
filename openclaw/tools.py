from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx

from openclaw.approvals import ApprovalsStore
from openclaw.config import ToolsConfig


class ToolApprovalRequired(Exception):
    def __init__(self, tool: str, message: str):
        super().__init__(message)
        self.tool = tool


def _matches_allowlist(cmd: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    return any(cmd.startswith(prefix) for prefix in allowlist)


def _exec_tool(args: dict[str, Any], allowlist: list[str]) -> dict[str, Any]:
    cmd = args.get("cmd")
    if isinstance(cmd, list):
        cmd_str = " ".join(cmd)
    else:
        cmd_str = str(cmd)
    if not _matches_allowlist(cmd_str, allowlist):
        return {"ok": False, "error": "command not allowed"}
    result = subprocess.run(cmd, capture_output=True, text=True)
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "code": result.returncode}


def _file_read(args: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(args.get("path"))).expanduser()
    return {"ok": True, "content": path.read_text()}


def _file_write(args: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(args.get("path"))).expanduser()
    content = str(args.get("content", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return {"ok": True}


def _web_fetch(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url"))
    resp = httpx.get(url, timeout=20)
    return {"ok": True, "status": resp.status_code, "text": resp.text}


class ToolRegistry:
    def __init__(self, config: ToolsConfig, approvals: ApprovalsStore):
        self.config = config
        self.approvals = approvals

    def ensure_approved(self, tool: str, channel: str, interactive: bool) -> None:
        if self.approvals.is_allowed(tool):
            return
        if interactive:
            resp = input(f"Allow tool '{tool}'? [y/N]: ").strip().lower()
            if resp in {"y", "yes"}:
                self.approvals.allow(tool)
                return
        raise ToolApprovalRequired(tool, f"Tool '{tool}' requires approval")

    def execute(self, tool: str, args: dict[str, Any], channel: str, interactive: bool) -> dict[str, Any]:
        self.ensure_approved(tool, channel, interactive)
        if tool == "exec":
            return _exec_tool(args, self.config.exec_allowlist)
        if tool == "file.read":
            return _file_read(args)
        if tool == "file.write":
            return _file_write(args)
        if tool == "web.fetch":
            return _web_fetch(args)
        return {"ok": False, "error": f"unknown tool {tool}"}
