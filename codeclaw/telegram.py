from __future__ import annotations

import os
import time

import httpx

from codeclaw.approvals import ApprovalsStore
from codeclaw.config import load_config


def _gateway_url(config):
    return f"http://{config.gateway.host}:{config.gateway.port}"


def _send_gateway(config, agent_id: str, message: str, session_id: str | None, peer: str):
    resp = httpx.post(
        f"{_gateway_url(config)}/api/session/send",
        headers={"x-token": config.gateway.token, "x-password": config.gateway.password},
        json={"agent_id": agent_id, "message": message, "session_id": session_id, "channel": "telegram", "peer": peer},
        timeout=30,
    )
    return resp.json()


def poll_loop():
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    approvals = ApprovalsStore(config.tools.approvals_path)
    offset = 0
    while True:
        resp = httpx.get(
            f"https://api.telegram.org/bot{config.telegram.bot_token}/getUpdates",
            params={"timeout": 30, "offset": offset},
            timeout=35,
        )
        data = resp.json()
        for update in data.get("result", []):
            offset = update.get("update_id", offset) + 1
            message = update.get("message") or {}
            text = message.get("text") or ""
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if not chat_id:
                continue
            if text.startswith("/allow "):
                tool = text.replace("/allow ", "", 1).strip()
                approvals.allow(tool)
                httpx.post(
                    f"https://api.telegram.org/bot{config.telegram.bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": f"Approved tool {tool}"},
                )
                continue
            agent_id = config.agents[0].id
            result = _send_gateway(config, agent_id, text, None, str(chat_id))
            reply = result.get("assistant_message", "") if result.get("ok") else result.get("error", "")
            httpx.post(
                f"https://api.telegram.org/bot{config.telegram.bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": reply},
            )
        time.sleep(config.telegram.poll_interval)


def main():
    poll_loop()


if __name__ == "__main__":
    main()
