from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from codeclaw.config import StorageConfig

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


_LOCK_MAP_GUARD = threading.Lock()
_LOCK_MAP: dict[str, threading.RLock] = {}


def _get_process_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCK_MAP_GUARD:
        lock = _LOCK_MAP.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCK_MAP[key] = lock
    return lock


@contextmanager
def _locked_file(path: Path):
    lock = _get_process_lock(path)
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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

    def _audit_path(self, agent_id: str) -> Path:
        return self._session_dir(agent_id) / "audit.jsonl"

    def _events_path(self, agent_id: str, session_id: str) -> Path:
        return self._session_dir(agent_id) / f"{session_id}.jsonl"

    def _lock_path(self, agent_id: str) -> Path:
        return self._session_dir(agent_id) / ".store.lock"

    @contextmanager
    def _agent_lock(self, agent_id: str):
        with _locked_file(self._lock_path(agent_id)):
            yield

    def _load_index_unlocked(self, agent_id: str) -> list[dict]:
        path = self._index_path(agent_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [entry for entry in data if isinstance(entry, dict)]

    def _save_index_unlocked(self, agent_id: str, sessions: list[dict]) -> None:
        path = self._index_path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sessions, indent=2))

    def _read_events_unlocked(self, agent_id: str, session_id: str) -> list[dict]:
        path = self._events_path(agent_id, session_id)
        if not path.exists():
            return []
        events: list[dict] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events

    def _write_events_unlocked(self, agent_id: str, session_id: str, events: list[dict]) -> None:
        path = self._events_path(agent_id, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event) + "\n")

    def list_sessions(self, agent_id: str) -> list[dict]:
        with self._agent_lock(agent_id):
            return self._load_index_unlocked(agent_id)

    def find_latest_session(self, agent_id: str, channel: str, peer: str) -> dict | None:
        with self._agent_lock(agent_id):
            sessions = self._load_index_unlocked(agent_id)
            for session in sorted(sessions, key=lambda s: s["updated_at"], reverse=True):
                if session.get("channel") == channel and session.get("peer") == peer:
                    return session
        return None

    def get_session(self, agent_id: str, session_id: str) -> dict | None:
        with self._agent_lock(agent_id):
            sessions = self._load_index_unlocked(agent_id)
            for session in sessions:
                if session.get("id") == session_id:
                    return session
        return None

    def create_session(self, agent_id: str, channel: str, peer: str, title: str) -> dict:
        with self._agent_lock(agent_id):
            session_id = f"{agent_id}-{uuid.uuid4().hex}"
            session = SessionRecord(
                id=session_id,
                agent_id=agent_id,
                channel=channel,
                peer=peer,
                title=title,
                created_at=_now(),
                updated_at=_now(),
            )
            sessions = self._load_index_unlocked(agent_id)
            sessions.append(session.__dict__)
            self._save_index_unlocked(agent_id, sessions)
            return session.__dict__

    def ensure_session(self, agent_id: str, session_id: str, channel: str, peer: str, title: str) -> dict:
        with self._agent_lock(agent_id):
            sessions = self._load_index_unlocked(agent_id)
            for session in sessions:
                if session.get("id") == session_id:
                    return session
            session = SessionRecord(
                id=session_id,
                agent_id=agent_id,
                channel=channel,
                peer=peer,
                title=title,
                created_at=_now(),
                updated_at=_now(),
            )
            sessions.append(session.__dict__)
            self._save_index_unlocked(agent_id, sessions)
            return session.__dict__

    def _touch_session_unlocked(self, agent_id: str, session_id: str) -> None:
        sessions = self._load_index_unlocked(agent_id)
        for session in sessions:
            if session.get("id") == session_id:
                session["updated_at"] = _now()
        self._save_index_unlocked(agent_id, sessions)

    def touch_session(self, agent_id: str, session_id: str) -> None:
        with self._agent_lock(agent_id):
            self._touch_session_unlocked(agent_id, session_id)

    def append_event(self, agent_id: str, session_id: str, event: dict) -> None:
        with self._agent_lock(agent_id):
            path = self._events_path(agent_id, session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            event_to_write = dict(event)
            event_to_write.setdefault("created_at", _now())
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event_to_write) + "\n")
            self._touch_session_unlocked(agent_id, session_id)
            self._compact_if_needed_unlocked(agent_id)

    def append_audit(self, agent_id: str, entry: dict[str, Any]) -> None:
        with self._agent_lock(agent_id):
            path = self._audit_path(agent_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = dict(entry)
            payload.setdefault("created_at", _now())
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\n")

    def read_events(self, agent_id: str, session_id: str) -> list[dict]:
        with self._agent_lock(agent_id):
            return self._read_events_unlocked(agent_id, session_id)

    def compact_if_needed(self, agent_id: str) -> None:
        with self._agent_lock(agent_id):
            self._compact_if_needed_unlocked(agent_id)

    def _compact_if_needed_unlocked(self, agent_id: str) -> None:
        compaction_path = self._compaction_path(agent_id)
        last_run = None
        if compaction_path.exists():
            try:
                payload = json.loads(compaction_path.read_text())
                if isinstance(payload, dict):
                    last_run = payload.get("last_run")
            except json.JSONDecodeError:
                last_run = None
        if last_run:
            last_dt = _parse_ts(str(last_run))
            if datetime.now(timezone.utc) - last_dt < timedelta(hours=self.compact_interval_hours):
                return
        self._compact_unlocked(agent_id)
        compaction_path.parent.mkdir(parents=True, exist_ok=True)
        compaction_path.write_text(json.dumps({"last_run": _now()}))

    def _compact_unlocked(self, agent_id: str) -> None:
        sessions = self._load_index_unlocked(agent_id)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        kept: list[dict] = []
        for session in sessions:
            updated_raw = session.get("updated_at")
            if not isinstance(updated_raw, str):
                continue
            updated = _parse_ts(updated_raw)
            if updated >= cutoff:
                kept.append(session)
            else:
                session_id = session.get("id")
                if not isinstance(session_id, str):
                    continue
                path = self._events_path(agent_id, session_id)
                if path.exists():
                    path.unlink()
        self._save_index_unlocked(agent_id, kept)

    def compact_session_context(
        self,
        agent_id: str,
        session_id: str,
        keep_recent_events: int,
        summary_line_limit: int,
    ) -> dict[str, Any]:
        with self._agent_lock(agent_id):
            events = self._read_events_unlocked(agent_id, session_id)
            if len(events) <= keep_recent_events + 1:
                return {"compacted": False, "reason": "not_enough_events"}
            keep_recent_events = max(4, keep_recent_events)
            head = events[:-keep_recent_events]
            tail = events[-keep_recent_events:]
            summary_text = self._summarize_events(head, summary_line_limit)
            if not summary_text:
                return {"compacted": False, "reason": "empty_summary"}
            summary_event = {
                "role": "summary",
                "content": summary_text,
                "meta": {"source_event_count": len(head)},
                "created_at": _now(),
            }
            new_events = [summary_event, *tail]
            self._write_events_unlocked(agent_id, session_id, new_events)
            self._touch_session_unlocked(agent_id, session_id)
            return {"compacted": True, "source_events": len(head), "kept_events": len(tail)}

    def _summarize_events(self, events: list[dict], summary_line_limit: int) -> str:
        lines: list[str] = []
        for event in events:
            role = str(event.get("role", "")).strip().lower()
            if role not in {"user", "assistant", "summary"}:
                continue
            content = str(event.get("content", "")).replace("\n", " ").strip()
            if not content:
                continue
            prefix = "User" if role == "user" else "Assistant" if role == "assistant" else "Summary"
            lines.append(f"- {prefix}: {content[:280]}")
            if len(lines) >= summary_line_limit:
                break
        if not lines:
            return ""
        return "Compacted session summary:\n" + "\n".join(lines)
