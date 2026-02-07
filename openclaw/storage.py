from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openclaw.config import StorageConfig


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class SessionRecord:
    id: str
    agent_id: str
    channel: str
    peer: str
    title: str
    created_at: str
    updated_at: str


class SessionStore:
    def __init__(self, config: StorageConfig):
        self.base_path = Path(config.base_path).expanduser()
        self.retention_days = config.retention_days
        self.compact_interval_hours = config.compact_interval_hours

    def _session_dir(self, agent_id: str) -> Path:
        return self.base_path / agent_id / "sessions"

    def _index_path(self, agent_id: str) -> Path:
        return self._session_dir(agent_id) / "sessions.json"

    def _compaction_path(self, agent_id: str) -> Path:
        return self._session_dir(agent_id) / "compaction.json"

    def _events_path(self, agent_id: str, session_id: str) -> Path:
        return self._session_dir(agent_id) / f"{session_id}.jsonl"

    def _load_index(self, agent_id: str) -> list[dict]:
        path = self._index_path(agent_id)
        if not path.exists():
            return []
        return json.loads(path.read_text())

    def _save_index(self, agent_id: str, sessions: list[dict]) -> None:
        path = self._index_path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sessions, indent=2))

    def list_sessions(self, agent_id: str) -> list[dict]:
        return self._load_index(agent_id)

    def find_latest_session(self, agent_id: str, channel: str, peer: str) -> dict | None:
        sessions = self._load_index(agent_id)
        for session in sorted(sessions, key=lambda s: s["updated_at"], reverse=True):
            if session["channel"] == channel and session["peer"] == peer:
                return session
        return None

    def get_session(self, agent_id: str, session_id: str) -> dict | None:
        sessions = self._load_index(agent_id)
        for session in sessions:
            if session["id"] == session_id:
                return session
        return None

    def create_session(self, agent_id: str, channel: str, peer: str, title: str) -> dict:
        session_id = f"{agent_id}-{int(datetime.now(timezone.utc).timestamp())}"
        session = SessionRecord(
            id=session_id,
            agent_id=agent_id,
            channel=channel,
            peer=peer,
            title=title,
            created_at=_now(),
            updated_at=_now(),
        )
        sessions = self._load_index(agent_id)
        sessions.append(session.__dict__)
        self._save_index(agent_id, sessions)
        return session.__dict__

    def ensure_session(self, agent_id: str, session_id: str, channel: str, peer: str, title: str) -> dict:
        existing = self.get_session(agent_id, session_id)
        if existing:
            return existing
        session = SessionRecord(
            id=session_id,
            agent_id=agent_id,
            channel=channel,
            peer=peer,
            title=title,
            created_at=_now(),
            updated_at=_now(),
        )
        sessions = self._load_index(agent_id)
        sessions.append(session.__dict__)
        self._save_index(agent_id, sessions)
        return session.__dict__

    def touch_session(self, agent_id: str, session_id: str) -> None:
        sessions = self._load_index(agent_id)
        for session in sessions:
            if session["id"] == session_id:
                session["updated_at"] = _now()
        self._save_index(agent_id, sessions)

    def append_event(self, agent_id: str, session_id: str, event: dict) -> None:
        path = self._events_path(agent_id, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        self.touch_session(agent_id, session_id)
        self.compact_if_needed(agent_id)

    def read_events(self, agent_id: str, session_id: str) -> list[dict]:
        path = self._events_path(agent_id, session_id)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def compact_if_needed(self, agent_id: str) -> None:
        compaction_path = self._compaction_path(agent_id)
        last_run = None
        if compaction_path.exists():
            last_run = json.loads(compaction_path.read_text()).get("last_run")
        if last_run:
            last_dt = _parse_ts(last_run)
            if datetime.now(timezone.utc) - last_dt < timedelta(hours=self.compact_interval_hours):
                return
        self._compact(agent_id)
        compaction_path.parent.mkdir(parents=True, exist_ok=True)
        compaction_path.write_text(json.dumps({"last_run": _now()}))

    def _compact(self, agent_id: str) -> None:
        sessions = self._load_index(agent_id)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        kept = []
        for session in sessions:
            updated = _parse_ts(session["updated_at"])
            if updated >= cutoff:
                kept.append(session)
            else:
                path = self._events_path(agent_id, session["id"])
                if path.exists():
                    path.unlink()
        self._save_index(agent_id, kept)
