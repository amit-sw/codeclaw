from __future__ import annotations

from pathlib import Path

from codeclaw.config import load_config


def run_doctor(config_path: str | None = None) -> int:
    config = load_config(config_path)
    if any(a.provider == "local" for a in config.agents) and not config.llm.local:
        raise ValueError("local provider requires llm.local")
    Path(config.storage.base_path).expanduser().mkdir(parents=True, exist_ok=True)
    return 0
