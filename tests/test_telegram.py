from types import SimpleNamespace

import httpx

from codeclaw.telegram import _send_gateway


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
