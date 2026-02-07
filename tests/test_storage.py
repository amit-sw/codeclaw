from openclaw.config import StorageConfig
from openclaw.storage import SessionStore


def test_session_store(tmp_path):
    store = SessionStore(StorageConfig(base_path=str(tmp_path)))
    session = store.create_session("agent", "cli", "peer", "hello")
    store.append_event("agent", session["id"], {"role": "user", "content": "hi"})
    events = store.read_events("agent", session["id"])
    assert events[0]["content"] == "hi"
    sessions = store.list_sessions("agent")
    assert sessions[0]["id"] == session["id"]
