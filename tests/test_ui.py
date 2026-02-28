import tomllib

from codeclaw.ui import _completed_plan_durations, _llm_requests, _save_telegram_settings


def test_llm_requests_are_reverse_chronological():
    events = [
        {"role": "user", "content": "first"},
        {
            "role": "llm_request",
            "content": {"provider": "openai", "model": "gpt-5", "message": "first", "channel": "webui"},
        },
        {"role": "assistant", "content": "a1"},
        {
            "role": "llm_request",
            "content": {"provider": "openai", "model": "gpt-5", "message": "second", "channel": "webui"},
        },
    ]
    rows = _llm_requests(events)
    assert [row["message"] for row in rows] == ["second", "first"]
    assert rows[0]["provider"] == "openai"


def test_llm_requests_include_rounded_duration_seconds():
    events = [
        {
            "role": "llm_request",
            "content": {"provider": "openai", "model": "gpt-5", "message": "a", "channel": "webui"},
            "created_at": "2026-02-28T10:00:00+00:00",
        },
        {"role": "assistant", "content": "ok", "created_at": "2026-02-28T10:00:02.6+00:00"},
    ]
    rows = _llm_requests(events)
    assert len(rows) == 1
    assert rows[0]["duration_seconds"] == 3


def test_completed_plan_durations_rounded_seconds():
    events = [
        {
            "role": "plan",
            "content": [{"content": "Step A", "status": "in_progress"}],
            "created_at": "2026-02-28T10:00:00+00:00",
        },
        {
            "role": "plan",
            "content": [{"content": "Step A", "status": "completed"}],
            "created_at": "2026-02-28T10:00:04.4+00:00",
        },
    ]
    durations = _completed_plan_durations(events)
    assert durations["Step A"] == 4


def test_save_telegram_settings_updates_config(tmp_path):
    config_path = tmp_path / "codeclaw.toml"
    config_path.write_text(
        """
[gateway]
host = "127.0.0.1"
port = 18789

[telegram]
bot_token = "old"
poll_interval = 3
"""
    )
    ok, err = _save_telegram_settings(config_path, "new-token", 9)
    assert ok is True
    assert err == ""
    data = tomllib.loads(config_path.read_text())
    assert data["telegram"]["bot_token"] == "new-token"
    assert data["telegram"]["poll_interval"] == 9
    assert data["gateway"]["host"] == "127.0.0.1"


def test_save_telegram_settings_rejects_invalid_interval(tmp_path):
    config_path = tmp_path / "codeclaw.toml"
    config_path.write_text("[gateway]\nhost='127.0.0.1'\nport=18789\n")
    ok, err = _save_telegram_settings(config_path, "token", 0)
    assert ok is False
    assert "at least 1" in err
