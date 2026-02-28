from codeclaw.gateway import _get_or_create_session


class _DummyStore:
    def __init__(self):
        self.calls = []

    def ensure_session(self, agent_id, session_id, channel, peer, title):
        self.calls.append(("ensure", session_id))
        return {"id": session_id}

    def find_latest_session(self, agent_id, channel, peer):
        self.calls.append(("find_latest", None))
        return {"id": "latest-1"}

    def create_session(self, agent_id, channel, peer, title):
        self.calls.append(("create", None))
        return {"id": "new-1"}


def test_get_or_create_session_force_new_bypasses_latest():
    store = _DummyStore()
    result = _get_or_create_session(
        store,
        agent_id="default",
        channel="webui",
        peer="ui",
        session_id=None,
        first_message="hello",
        force_new=True,
    )
    assert result["id"] == "new-1"
    assert ("find_latest", None) not in store.calls


def test_get_or_create_session_uses_latest_when_not_forced():
    store = _DummyStore()
    result = _get_or_create_session(
        store,
        agent_id="default",
        channel="webui",
        peer="ui",
        session_id=None,
        first_message="hello",
        force_new=False,
    )
    assert result["id"] == "latest-1"
    assert ("find_latest", None) in store.calls

