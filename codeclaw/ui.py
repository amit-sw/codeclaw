from __future__ import annotations

import os

import httpx
import streamlit as st

from codeclaw.approvals import ApprovalsStore
from codeclaw.config import load_config


def _gateway_url(config):
    return f"http://{config.gateway.host}:{config.gateway.port}"


def _auth_headers(token: str, password: str):
    return {"x-token": token, "x-password": password}


def _request_json(method: str, url: str, **kwargs):
    try:
        # Gateway calls are local HTTP endpoints; disable TLS verification to avoid
        # broken global SSL cert path configurations affecting local requests.
        kwargs.setdefault("verify", False)
        response = httpx.request(method, url, **kwargs)
    except httpx.RequestError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        return response.json()
    except ValueError:
        if response.text:
            return {"ok": False, "error": response.text[:500]}
        return {"ok": False, "error": f"HTTP {response.status_code} returned non-JSON response"}


def main():
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    approvals = ApprovalsStore(config.tools.approvals_path)

    st.sidebar.title("CodeClaw Lite")
    token = st.sidebar.text_input("Token", type="password")
    password = st.sidebar.text_input("Password", type="password")
    authed = bool(token and password)

    if not authed:
        st.stop()

    agent_ids = [a.id for a in config.agents]
    agent_id = st.sidebar.selectbox("Agent", agent_ids)

    sessions_resp = _request_json(
        "GET",
        f"{_gateway_url(config)}/api/session/list",
        headers=_auth_headers(token, password),
        params={"agent_id": agent_id},
        timeout=10,
    )
    if not sessions_resp.get("ok", True):
        st.error(sessions_resp.get("error", "failed to load sessions"))
        st.stop()
    sessions = sessions_resp.get("sessions", [])
    session_map = {s["title"] + " | " + s["id"]: s["id"] for s in sessions}
    session_choice = st.sidebar.selectbox("Session", ["New"] + list(session_map.keys()))
    session_id = session_map.get(session_choice)

    st.sidebar.subheader("Tool Approvals")
    allowed = approvals.load()
    for tool in ["exec", "file.read", "file.write", "web.fetch"]:
        if tool in allowed:
            st.sidebar.write(f"{tool}: allowed")
        else:
            if st.sidebar.button(f"Allow {tool}"):
                approvals.allow(tool)

    st.title("Chat")
    if session_id:
        events_resp = _request_json(
            "GET",
            f"{_gateway_url(config)}/api/session/events",
            headers=_auth_headers(token, password),
            params={"agent_id": agent_id, "session_id": session_id},
            timeout=10,
        )
        if not events_resp.get("ok", True):
            st.error(events_resp.get("error", "failed to load session events"))
            st.stop()
        for event in events_resp.get("events", []):
            role = event.get("role")
            content = event.get("content")
            st.write(f"**{role}**: {content}")

    user_msg = st.text_input("Message")
    if st.button("Send") and user_msg:
        resp = _request_json(
            "POST",
            f"{_gateway_url(config)}/api/session/send",
            headers=_auth_headers(token, password),
            json={"agent_id": agent_id, "message": user_msg, "session_id": session_id, "channel": "webui", "peer": "ui"},
            timeout=30,
        )
        if resp.get("ok"):
            st.write(resp.get("assistant_message"))
        else:
            st.error(resp.get("error"))


if __name__ == "__main__":
    main()
