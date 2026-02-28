from __future__ import annotations

import os
import time

import httpx

from codeclaw.config import load_config


def _gateway_url(config):
    return f"http://{config.gateway.host}:{config.gateway.port}"


def _send_gateway(config, agent_id: str, message: str, session_id: str | None, peer: str) -> dict:
    timeout_seconds = int(os.environ.get("CODECLAW_TELEGRAM_GATEWAY_TIMEOUT", "300"))
    timeout = httpx.Timeout(connect=10.0, read=float(timeout_seconds), write=30.0, pool=30.0)
    try:
        resp = httpx.post(
            f"{_gateway_url(config)}/api/session/send",
            json={"agent_id": agent_id, "message": message, "session_id": session_id, "channel": "telegram", "peer": peer},
            timeout=timeout,
        )
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"Gateway request failed: {exc}"}
    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "error": f"Gateway returned non-JSON response (HTTP {resp.status_code})."}
    if isinstance(data, dict):
        return data
    return {"ok": False, "error": "Gateway returned invalid JSON payload."}


def _send_telegram_message(bot_token: str, chat_id: int, text: str) -> None:
    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=20,
        )
    except httpx.RequestError:
        return


def poll_loop():
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    offset = 0
    while True:
        try:
            resp = httpx.get(
                f"https://api.telegram.org/bot{config.telegram.bot_token}/getUpdates",
                params={"timeout": 30, "offset": offset},
                timeout=35,
            )
            data = resp.json()
        except (httpx.RequestError, ValueError):
            time.sleep(config.telegram.poll_interval)
            continue
        for update in data.get("result", []):
            offset = update.get("update_id", offset) + 1
            message = update.get("message") or {}
            text = message.get("text") or ""
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if not chat_id or not text.strip():
                continue
            agent_id = config.agents[0].id
            result = _send_gateway(config, agent_id, text, None, str(chat_id))
            if result.get("ok"):
                reply = str(result.get("assistant_message", "")).strip() or "No response."
            else:
                reply = str(result.get("error", "Request failed.")).strip() or "Request failed."
            _send_telegram_message(config.telegram.bot_token, chat_id, reply)
        time.sleep(config.telegram.poll_interval)


def main():
    poll_loop()


if __name__ == "__main__":
    main()
