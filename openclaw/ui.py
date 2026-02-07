from __future__ import annotations

import os

import httpx
import streamlit as st

from openclaw.approvals import ApprovalsStore
from openclaw.config import load_config


def _gateway_url(config):
    return f"http://{config.gateway.host}:{config.gateway.port}"


def _auth_headers(token: str, password: str):
    return {"x-token": token, "x-password": password}


def main():
    config = load_config(os.environ.get("OPENCLAW_CONFIG"))
    approvals = ApprovalsStore(config.tools.approvals_path)

    st.sidebar.title("OpenClaw Lite")
    token = st.sidebar.text_input("Token", type="password")
    password = st.sidebar.text_input("Password", type="password")
    authed = bool(token and password)

    if not authed:
        st.stop()

    agent_ids = [a.id for a in config.agents]
    agent_id = st.sidebar.selectbox("Agent", agent_ids)

    sessions_resp = httpx.get(
        f"{_gateway_url(config)}/api/session/list",
        headers=_auth_headers(token, password),
        params={"agent_id": agent_id},
        timeout=10,
    ).json()
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
        events_resp = httpx.get(
            f"{_gateway_url(config)}/api/session/events",
            headers=_auth_headers(token, password),
            params={"agent_id": agent_id, "session_id": session_id},
            timeout=10,
        ).json()
        for event in events_resp.get("events", []):
            role = event.get("role")
            content = event.get("content")
            st.write(f"**{role}**: {content}")

    user_msg = st.text_input("Message")
    if st.button("Send") and user_msg:
        resp = httpx.post(
            f"{_gateway_url(config)}/api/session/send",
            headers=_auth_headers(token, password),
            json={"agent_id": agent_id, "message": user_msg, "session_id": session_id, "channel": "webui", "peer": "ui"},
            timeout=30,
        ).json()
        if resp.get("ok"):
            st.write(resp.get("assistant_message"))
        else:
            st.error(resp.get("error"))


if __name__ == "__main__":
    main()
