from codeclaw.approvals import ApprovalsStore
from codeclaw.config import ToolsConfig
from codeclaw.tools import ToolRegistry, ToolApprovalRequired


def test_tool_approval_required(tmp_path):
    approvals = ApprovalsStore(str(tmp_path / "approvals.json"))
    registry = ToolRegistry(ToolsConfig(approvals_path=str(tmp_path / "approvals.json")), approvals)
    try:
        registry.execute("web.fetch", {"url": "https://example.com"}, channel="cli", interactive=False)
    except ToolApprovalRequired:
        return
    assert False


def test_tool_allowed(tmp_path):
    approvals = ApprovalsStore(str(tmp_path / "approvals.json"))
    approvals.allow("exec")
    registry = ToolRegistry(ToolsConfig(approvals_path=str(tmp_path / "approvals.json")), approvals)
    result = registry.execute("exec", {"cmd": ["echo", "hi"]}, channel="cli", interactive=False)
    assert result["ok"] is True


def test_file_write_defaults_to_todo(tmp_path, monkeypatch):
    monkeypatch.setattr("codeclaw.tools._user_home", lambda: tmp_path)
    approvals = ApprovalsStore(str(tmp_path / "approvals.json"))
    approvals.allow("file.write")
    registry = ToolRegistry(ToolsConfig(approvals_path=str(tmp_path / "approvals.json")), approvals)
    result = registry.execute("file.write", {"content": "task1 todo list"}, channel="cli", interactive=False)
    assert result["ok"] is True
    assert result["path"] == str(tmp_path / ".codeclaw" / "tasks.md")
    assert (tmp_path / ".codeclaw" / "tasks.md").read_text() == "task1 todo list"


def test_file_write_remaps_root_path(tmp_path, monkeypatch):
    monkeypatch.setattr("codeclaw.tools._user_home", lambda: tmp_path)
    approvals = ApprovalsStore(str(tmp_path / "approvals.json"))
    approvals.allow("file.write")
    registry = ToolRegistry(ToolsConfig(approvals_path=str(tmp_path / "approvals.json")), approvals)
    result = registry.execute("file.write", {"path": "/root/.codeclaw/TODO.md", "content": "task2"}, channel="cli", interactive=False)
    assert result["ok"] is True
    assert result["path"] == str(tmp_path / ".codeclaw" / "TODO.md")
    assert (tmp_path / ".codeclaw" / "TODO.md").read_text() == "task2"


def test_file_write_updates_file_index(tmp_path, monkeypatch):
    monkeypatch.setattr("codeclaw.tools._user_home", lambda: tmp_path)
    approvals = ApprovalsStore(str(tmp_path / "approvals.json"))
    approvals.allow("file.write")
    registry = ToolRegistry(ToolsConfig(approvals_path=str(tmp_path / "approvals.json")), approvals)
    result = registry.execute("file.write", {"usage": "notes", "content": "note body"}, channel="webui", interactive=False)
    assert result["ok"] is True
    index_path = tmp_path / ".codeclaw" / "FILE_INDEX.json"
    data = index_path.read_text()
    assert "notes.md" in data
    assert "\"usage\": \"notes\"" in data
    assert "\"channel\": \"webui\"" in data
