from types import SimpleNamespace

import httpx

from codeclaw.telegram import _send_gateway, _transcribe_voice_message, _work_item_from_update


def _config():
    return SimpleNamespace(gateway=SimpleNamespace(host="127.0.0.1", port=18789))


def test_send_gateway_handles_timeout(monkeypatch):
    def _fake_post(*args, **kwargs):  # noqa: ARG001
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr("codeclaw.telegram.httpx.post", _fake_post)

    result = _send_gateway(_config(), "default", "hello", None, "peer-1")

    assert result["ok"] is False
    assert "Gateway request failed" in result["error"]


def test_send_gateway_returns_json_payload(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return {"ok": True, "assistant_message": "ok"}

    monkeypatch.setattr("codeclaw.telegram.httpx.post", lambda *args, **kwargs: _Resp())  # noqa: ARG005

    result = _send_gateway(_config(), "default", "hello", None, "peer-1")

    assert result["ok"] is True
    assert result["assistant_message"] == "ok"


def _voice_config(
    *,
    enabled: bool = True,
    max_seconds: int = 180,
    max_bytes: int = 25_000_000,
    model: str = "whisper-1",
):
    return SimpleNamespace(
        telegram=SimpleNamespace(
            bot_token="bot",
            voice_transcription_enabled=enabled,
            voice_max_seconds=max_seconds,
            voice_max_bytes=max_bytes,
            voice_transcription_model=model,
        ),
        llm=SimpleNamespace(openai=SimpleNamespace(api_key="k", base_url="https://api.openai.com/v1")),
    )


def test_work_item_from_update_parses_text_message():
    update = {
        "update_id": 10,
        "message": {
            "chat": {"id": 55},
            "text": "hello world",
        },
    }

    item = _work_item_from_update(update, default_update_id=0)

    assert item is not None
    assert item.update_id == 10
    assert item.chat_id == 55
    assert item.text == "hello world"
    assert item.voice_file_id == ""


def test_work_item_from_update_parses_voice_message():
    update = {
        "update_id": 11,
        "message": {
            "chat": {"id": 77},
            "voice": {"file_id": "abc123", "duration": 9, "mime_type": "audio/ogg"},
        },
    }

    item = _work_item_from_update(update, default_update_id=0)

    assert item is not None
    assert item.update_id == 11
    assert item.chat_id == 77
    assert item.text == ""
    assert item.voice_file_id == "abc123"
    assert item.voice_duration_seconds == 9
    assert item.voice_mime_type == "audio/ogg"


def test_transcribe_voice_message_short_circuit_when_disabled():
    result = _transcribe_voice_message(_voice_config(enabled=False), file_id="abc123", duration_seconds=2, mime_type="audio/ogg")

    assert result["ok"] is False
    assert "disabled" in result["error"]


def test_transcribe_voice_message_enforces_duration_limit():
    result = _transcribe_voice_message(_voice_config(max_seconds=5), file_id="abc123", duration_seconds=7, mime_type="audio/ogg")

    assert result["ok"] is False
    assert "too long" in result["error"]


def test_transcribe_voice_message_happy_path(monkeypatch):
    monkeypatch.setattr(
        "codeclaw.telegram._telegram_api_post",
        lambda *args, **kwargs: {"ok": True, "result": {"file_path": "voice/file.ogg"}},
    )
    monkeypatch.setattr(
        "codeclaw.telegram._download_telegram_file",
        lambda *args, **kwargs: {"ok": True, "bytes": b"OGG", "content_type": "audio/ogg"},
    )
    monkeypatch.setattr(
        "codeclaw.telegram._transcribe_openai_audio",
        lambda *args, **kwargs: {"ok": True, "text": "turn on the lights"},
    )

    result = _transcribe_voice_message(_voice_config(), file_id="abc123", duration_seconds=4, mime_type="audio/ogg")

    assert result["ok"] is True
    assert result["text"] == "turn on the lights"
    assert result["duration_seconds"] == 4
