from __future__ import annotations

import os
from pathlib import Path
import tomllib
from datetime import datetime

import httpx
import streamlit as st
import toml

from codeclaw.config import default_config_path, load_config


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


def _config_path() -> Path:
    configured = os.environ.get("CODECLAW_CONFIG")
    if configured:
        return Path(configured).expanduser()
    return default_config_path()


def _save_telegram_settings(config_path: Path, bot_token: str, poll_interval: int) -> tuple[bool, str]:
    if poll_interval < 1:
        return False, "poll_interval must be at least 1 second."
    try:
        raw = config_path.read_text() if config_path.exists() else ""
        data = tomllib.loads(raw) if raw.strip() else {}
    except Exception as exc:  # noqa: BLE001
        return False, f"failed to read config: {exc}"
    telegram = data.get("telegram")
    if not isinstance(telegram, dict):
        telegram = {}
        data["telegram"] = telegram
    telegram["bot_token"] = bot_token.strip()
    telegram["poll_interval"] = int(poll_interval)
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(toml.dumps(data))
    except Exception as exc:  # noqa: BLE001
        return False, f"failed to write config: {exc}"
    return True, ""


def _latest_plan(events: list[dict]) -> list[dict[str, str]] | None:
    for event in reversed(events):
        if event.get("role") != "plan":
            continue
        content = event.get("content")
        if not isinstance(content, list):
            return []
        plan: list[dict[str, str]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).strip().lower()
            if not text:
                continue
            if status not in {"pending", "in_progress", "completed"}:
                status = "pending"
            plan.append({"content": text, "status": status})
        return plan
    return None


def _event_dt(event: dict) -> datetime | None:
    raw = event.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except Exception:  # noqa: BLE001
        return None


def _duration_seconds(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    delta = (end - start).total_seconds()
    if delta < 0:
        return None
    return int(delta + 0.5)


def _completed_plan_durations(events: list[dict]) -> dict[str, int]:
    starts: dict[str, datetime] = {}
    done: dict[str, int] = {}
    for event in events:
        if event.get("role") != "plan":
            continue
        content = event.get("content")
        if not isinstance(content, list):
            continue
        at = _event_dt(event)
        for item in content:
            if not isinstance(item, dict):
                continue
            text = str(item.get("content", "")).strip()
            if not text:
                continue
            status = str(item.get("status", "pending")).strip().lower()
            if text not in starts and at is not None:
                starts[text] = at
            if status == "completed" and text not in done:
                seconds = _duration_seconds(starts.get(text), at)
                if seconds is not None:
                    done[text] = seconds
    return done


def _llm_requests(events: list[dict]) -> list[dict[str, str | int]]:
    requests: list[dict[str, str | int]] = []
    for i, event in enumerate(events):
        if event.get("role") != "llm_request":
            continue
        content = event.get("content")
        request: dict[str, str | int] = {"message": "", "provider": "", "model": "", "channel": ""}
        if isinstance(content, dict):
            request["message"] = str(content.get("message", "")).strip()
            request["provider"] = str(content.get("provider", "")).strip()
            request["model"] = str(content.get("model", "")).strip()
            request["channel"] = str(content.get("channel", "")).strip()
        else:
            request["message"] = str(content)
        start = _event_dt(event)
        end = None
        for follow in events[i + 1 :]:
            if follow.get("role") == "assistant":
                end = _event_dt(follow)
                break
        seconds = _duration_seconds(start, end)
        if seconds is not None:
            request["duration_seconds"] = seconds
        requests.append(request)
    requests.reverse()
    return requests


def _render_plan_sidebar(plan: list[dict[str, str]], plan_done_seconds: dict[str, int], pending: bool) -> None:
    st.sidebar.subheader("AI Plan")
    if pending:
        st.sidebar.caption("Updating...")
    if not plan:
        st.sidebar.caption("No active plan.")
        return
    markers = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    for item in plan:
        marker = markers.get(item["status"], "[ ]")
        text = item["content"]
        if item["status"] == "completed" and text in plan_done_seconds:
            st.sidebar.write(f"{marker} {text} ({plan_done_seconds[text]}s)")
        else:
            st.sidebar.write(f"{marker} {text}")


def _render_llm_requests_sidebar(entries: list[dict[str, str | int]], pending_msg: str) -> None:
    st.sidebar.subheader("LLM Requests")
    if pending_msg:
        preview = pending_msg.replace("\n", " ").strip()
        if len(preview) > 120:
            preview = preview[:117] + "..."
        st.sidebar.write(f"[pending] {preview}")
    if not entries:
        st.sidebar.caption("No requests in this session.")
        return
    for entry in entries:
        provider = str(entry["provider"])
        model = str(entry["model"])
        if provider and model:
            prefix = f"{provider}:{model}"
        elif model:
            prefix = model
        else:
            prefix = provider
        message = str(entry["message"]).replace("\n", " ").strip()
        if len(message) > 120:
            message = message[:117] + "..."
        suffix = ""
        duration_seconds = entry.get("duration_seconds")
        if isinstance(duration_seconds, int):
            suffix = f" ({duration_seconds}s)"
        if prefix:
            st.sidebar.write(f"{prefix} {message}{suffix}")
        else:
            st.sidebar.write(f"{message}{suffix}")


def main():
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    config_path = _config_path()

    st.sidebar.title("CodeClaw Lite")
    with st.sidebar.expander("Telegram Bot Setup", expanded=False):
        st.caption(f"Config: {config_path}")
        with st.form("telegram_settings_form"):
            bot_token = st.text_input("Bot Token", value=config.telegram.bot_token, type="password")
            poll_interval = int(
                st.number_input(
                    "Poll Interval (seconds)",
                    min_value=1,
                    max_value=300,
                    value=int(config.telegram.poll_interval),
                    step=1,
                )
            )
            save_telegram = st.form_submit_button("Save Telegram Settings")
        if save_telegram:
            ok, err = _save_telegram_settings(config_path, bot_token, poll_interval)
            if ok:
                st.success("Saved. Restart Telegram poller to apply changes.")
                st.rerun()
            else:
                st.error(err)

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
    plan_key = f"active_plan::{agent_id}"
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
    if plan_key not in st.session_state:
        st.session_state[plan_key] = []

    active_session_id = st.session_state[state_key]
    active_session_choice = "New"
    if active_session_id:
        for key, sid in session_map.items():
            if sid == active_session_id:
                active_session_choice = key
                break
    current_choice = st.session_state.get(session_choice_key, "New")
    if current_choice not in session_choices:
        current_choice = active_session_choice
    if active_session_id and session_map.get(current_choice) != active_session_id:
        current_choice = active_session_choice
    if not active_session_id:
        current_choice = "New"
    st.session_state[session_choice_key] = current_choice
    session_choice = st.sidebar.selectbox("Session", session_choices, key=session_choice_key)
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
        elif role in {"plan", "llm_request"}:
            continue
        else:
            with st.chat_message("assistant"):
                st.write(f"[{role}] {content}")

    latest_plan = _latest_plan(events)
    if latest_plan is not None:
        st.session_state[plan_key] = latest_plan

    pending_msg = st.session_state[pending_msg_key]
    pending_err = st.session_state[pending_err_key]
    request_log = _llm_requests(events)
    plan_done_seconds = _completed_plan_durations(events)
    _render_plan_sidebar(
        st.session_state[plan_key],
        plan_done_seconds=plan_done_seconds,
        pending=bool(pending_msg and not pending_err),
    )
    _render_llm_requests_sidebar(request_log, pending_msg if not pending_err else "")
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
            if isinstance(resp.get("plan"), list):
                st.session_state[plan_key] = resp.get("plan")
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
