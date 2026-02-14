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
