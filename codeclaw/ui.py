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
    session_choices = ["New"] + list(session_map.keys())
    state_key = f"active_session_id::{agent_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = None

    default_idx = 0
    if st.session_state[state_key]:
        for i, key in enumerate(session_choices):
            if session_map.get(key) == st.session_state[state_key]:
                default_idx = i
                break
    session_choice = st.sidebar.selectbox("Session", session_choices, index=default_idx)
    session_id = session_map.get(session_choice) or st.session_state[state_key]
    if session_choice == "New":
        session_id = st.session_state[state_key]

    st.sidebar.subheader("Tool Approvals")
    allowed = approvals.load()
    for tool in ["exec", "file.read", "file.write", "web.fetch"]:
        if tool in allowed:
            st.sidebar.write(f"{tool}: allowed")
        else:
            if st.sidebar.button(f"Allow {tool}"):
                approvals.allow(tool)

    st.title("Chat")
    events = []
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
        events = events_resp.get("events", [])

    for event in events:
        role = event.get("role")
        content = event.get("content")
        if role == "user":
            with st.chat_message("user"):
                st.write(content)
        elif role == "assistant":
            with st.chat_message("assistant"):
                st.write(content)
        else:
            with st.chat_message("assistant"):
                st.write(f"[{role}] {content}")

    user_msg = st.chat_input("Message")
    if user_msg:
        resp = _request_json(
            "POST",
            f"{_gateway_url(config)}/api/session/send",
            headers=_auth_headers(token, password),
            json={"agent_id": agent_id, "message": user_msg, "session_id": session_id, "channel": "webui", "peer": "ui"},
            timeout=30,
        )
        if resp.get("ok"):
            returned_session_id = resp.get("session_id")
            if returned_session_id:
                st.session_state[state_key] = returned_session_id
            st.rerun()
        else:
            st.error(resp.get("error"))


if __name__ == "__main__":
    main()
