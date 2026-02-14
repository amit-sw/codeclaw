from __future__ import annotations

import json
import os
import pwd
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from codeclaw.approvals import ApprovalsStore
from codeclaw.config import ToolsConfig


FILE_INDEX_NAME = "FILE_INDEX.json"


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
    path = _resolve_file_path(args.get("path"), args.get("usage"), args.get("content"))
    return {"ok": True, "path": str(path), "content": path.read_text()}


def _file_write(args: dict[str, Any], channel: str) -> dict[str, Any]:
    usage = str(args.get("usage", "")).strip()
    path = _resolve_file_path(args.get("path"), usage, args.get("content"))
    content = str(args.get("content", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _update_file_index(path, usage or _infer_usage(content), channel)
    return {"ok": True, "path": str(path)}


def _resolve_file_path(path_value: Any, usage_value: Any = None, content_value: Any = None) -> Path:
    raw = str(path_value or "").strip()
    if not raw or raw.lower() in {"none", "null"}:
        usage = str(usage_value or "").strip() or _infer_usage(str(content_value or ""))
        return (_codeclaw_dir() / _usage_to_filename(usage)).expanduser()
    expanded = Path(raw).expanduser()
    # Some models hardcode /root paths. Remap to the active user home when not root.
    if os.getuid() != 0 and str(expanded).startswith("/root/.codeclaw/"):
        suffix = expanded.relative_to(Path("/root"))
        return _user_home() / suffix
    return expanded


def _infer_usage(content: str) -> str:
    text = content.lower()
    if any(word in text for word in ["todo", "task", "checklist", "action item", "next step"]):
        return "tasks"
    if any(word in text for word in ["meeting", "agenda", "minutes"]):
        return "meetings"
    if any(word in text for word in ["journal", "diary", "daily log"]):
        return "journal"
    if any(word in text for word in ["idea", "brainstorm"]):
        return "ideas"
    if any(word in text for word in ["note", "summary"]):
        return "notes"
    return "inbox"


def _usage_to_filename(usage: str) -> str:
    normalized = usage.strip().lower()
    mapping = {
        "task": "tasks.md",
        "tasks": "tasks.md",
        "todo": "tasks.md",
        "checklist": "tasks.md",
        "meeting": "meetings.md",
        "meetings": "meetings.md",
        "minutes": "meetings.md",
        "journal": "journal.md",
        "diary": "journal.md",
        "idea": "ideas.md",
        "ideas": "ideas.md",
        "note": "notes.md",
        "notes": "notes.md",
        "summary": "notes.md",
        "inbox": "inbox.md",
    }
    return mapping.get(normalized, "inbox.md")


def _update_file_index(path: Path, usage: str, channel: str) -> None:
    codeclaw_dir = _codeclaw_dir()
    index_path = codeclaw_dir / FILE_INDEX_NAME
    codeclaw_dir.mkdir(parents=True, exist_ok=True)
    entries = _load_file_index(index_path)
    key = str(path)
    entries[key] = {
        "path": str(path),
        "usage": usage or "inbox",
        "channel": channel,
        "last_updated_at": datetime.now(timezone.utc).isoformat(),
    }
    index_path.write_text(json.dumps({"files": entries}, indent=2))


def _load_file_index(index_path: Path) -> dict[str, dict[str, str]]:
    if not index_path.exists():
        return {}
    data = json.loads(index_path.read_text())
    files = data.get("files", {})
    if isinstance(files, dict):
        return files
    return {}


def _codeclaw_dir() -> Path:
    return _user_home() / ".codeclaw"


def _user_home() -> Path:
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except KeyError:
        return Path.home()


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
            return _file_write(args, channel)
        if tool == "web.fetch":
            return _web_fetch(args)
        return {"ok": False, "error": f"unknown tool {tool}"}
