from __future__ import annotations

import os

import httpx
import streamlit as st

from codeclaw.config import load_config


def _gateway_url(config):
    return f"http://{config.gateway.host}:{config.gateway.port}"


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

    st.sidebar.title("CodeClaw Lite")
    agent_ids = [a.id for a in config.agents]
    agent_id = st.sidebar.selectbox("Agent", agent_ids)

    sessions_resp = _request_json(
        "GET",
        f"{_gateway_url(config)}/api/session/list",
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
    session_choice_key = f"session_choice::{agent_id}"
    prev_session_choice_key = f"prev_session_choice::{agent_id}"
    pending_msg_key = f"pending_user_msg::{agent_id}"
    pending_err_key = f"pending_user_err::{agent_id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = None
    if session_choice_key not in st.session_state:
        st.session_state[session_choice_key] = "New"
    if prev_session_choice_key not in st.session_state:
        st.session_state[prev_session_choice_key] = st.session_state[session_choice_key]
    if pending_msg_key not in st.session_state:
        st.session_state[pending_msg_key] = ""
    if pending_err_key not in st.session_state:
        st.session_state[pending_err_key] = ""

    default_idx = 0
    if st.session_state[state_key]:
        for i, key in enumerate(session_choices):
            if session_map.get(key) == st.session_state[state_key]:
                default_idx = i
                break
    session_choice = st.sidebar.selectbox("Session", session_choices, index=default_idx, key=session_choice_key)
    prev_choice = st.session_state[prev_session_choice_key]
    if session_choice == "New" and prev_choice != "New":
        st.session_state[state_key] = None
    st.session_state[prev_session_choice_key] = session_choice

    session_id = session_map.get(session_choice)
    if session_choice == "New":
        session_id = st.session_state[state_key]
    force_new_session = session_choice == "New" and not session_id

    st.title("Chat")
    events = []
    if session_id:
        events_resp = _request_json(
            "GET",
            f"{_gateway_url(config)}/api/session/events",
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

    pending_msg = st.session_state[pending_msg_key]
    pending_err = st.session_state[pending_err_key]
    if pending_msg:
        with st.chat_message("user"):
            st.write(pending_msg)

    user_msg = st.chat_input("Message", disabled=bool(pending_msg))
    if user_msg and not pending_msg:
        st.session_state[pending_msg_key] = user_msg
        st.session_state[pending_err_key] = ""
        st.rerun()

    pending_msg = st.session_state[pending_msg_key]
    pending_err = st.session_state[pending_err_key]
    if pending_msg and not pending_err:
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                resp = _request_json(
                    "POST",
                    f"{_gateway_url(config)}/api/session/send",
                    json={
                        "agent_id": agent_id,
                        "message": pending_msg,
                        "session_id": session_id,
                        "force_new": force_new_session,
                        "channel": "webui",
                        "peer": "ui",
                    },
                    timeout=180,
                )
        if resp.get("ok"):
            returned_session_id = resp.get("session_id")
            if returned_session_id:
                st.session_state[state_key] = returned_session_id
            st.session_state[pending_msg_key] = ""
            st.session_state[pending_err_key] = ""
            st.rerun()
        else:
            st.session_state[pending_err_key] = resp.get("error", "request failed")
            st.rerun()

    pending_msg = st.session_state[pending_msg_key]
    pending_err = st.session_state[pending_err_key]
    if pending_msg and pending_err:
        st.error(f"Send failed: {pending_err}")
        c1, c2 = st.columns(2)
        if c1.button("Retry send"):
            st.session_state[pending_err_key] = ""
            st.rerun()
        if c2.button("Discard message"):
            st.session_state[pending_msg_key] = ""
            st.session_state[pending_err_key] = ""
            st.rerun()


if __name__ == "__main__":
    main()
