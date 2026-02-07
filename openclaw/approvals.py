from __future__ import annotations

import json
from pathlib import Path


class ApprovalsStore:
    def __init__(self, path: str):
        self.path = Path(path).expanduser()

    def load(self) -> set[str]:
        if not self.path.exists():
            return set()
        data = json.loads(self.path.read_text())
        return set(data.get("allowed", []))

    def save(self, allowed: set[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"allowed": sorted(allowed)}
        self.path.write_text(json.dumps(payload, indent=2))

    def is_allowed(self, tool: str) -> bool:
        return tool in self.load()

    def allow(self, tool: str) -> None:
        allowed = self.load()
        allowed.add(tool)
        self.save(allowed)
