from __future__ import annotations

from pathlib import Path

from openclaw.config import load_config


def run_doctor(config_path: str | None = None) -> int:
    config = load_config(config_path)
    if not config.gateway.token or not config.gateway.password:
        raise ValueError("gateway token/password required")
    if any(a.provider == "local" for a in config.agents) and not config.llm.local:
        raise ValueError("local provider requires llm.local")
    Path(config.storage.base_path).expanduser().mkdir(parents=True, exist_ok=True)
    Path(config.tools.approvals_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    return 0
