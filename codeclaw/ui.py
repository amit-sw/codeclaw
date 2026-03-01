from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import streamlit as st
import toml
import tomllib

from codeclaw.config import default_config_path, load_config


def _gateway_url(config):
    return f"http://{config.gateway.host}:{config.gateway.port}"


def _request_json(method: str, url: str, **kwargs):
    try:
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


def _load_toml_data(config_path: Path) -> tuple[bool, dict[str, Any], str]:
    try:
        raw = config_path.read_text() if config_path.exists() else ""
        data = tomllib.loads(raw) if raw.strip() else {}
    except Exception as exc:  # noqa: BLE001
        return False, {}, f"failed to read config: {exc}"
    if not isinstance(data, dict):
        return False, {}, "failed to parse config: root is not a table"
    return True, data, ""


def _save_toml_data(config_path: Path, data: dict[str, Any]) -> tuple[bool, str]:
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(toml.dumps(data))
    except Exception as exc:  # noqa: BLE001
        return False, f"failed to write config: {exc}"
    return True, ""


def _save_telegram_runtime_settings(
    config_path: Path,
    *,
    bot_token: str,
    poll_interval: int,
    typing_interval_seconds: int,
    stream_partial_replies: bool,
    partial_reply_chunk_chars: int,
    partial_reply_delay_seconds: float,
    send_max_retries: int,
    send_backoff_seconds: float,
    voice_transcription_enabled: bool,
    voice_transcription_model: str,
    voice_max_seconds: int,
    voice_max_bytes: int,
) -> tuple[bool, str]:
    if poll_interval < 1:
        return False, "poll_interval must be at least 1 second."
    if typing_interval_seconds < 1:
        return False, "typing_interval_seconds must be at least 1 second."
    if partial_reply_chunk_chars < 80:
        return False, "partial_reply_chunk_chars must be at least 80."
    if partial_reply_delay_seconds < 0.01:
        return False, "partial_reply_delay_seconds must be at least 0.01."
    if send_max_retries < 0:
        return False, "send_max_retries cannot be negative."
    if send_backoff_seconds <= 0:
        return False, "send_backoff_seconds must be positive."
    if voice_max_seconds < 1:
        return False, "voice_max_seconds must be at least 1."
    if voice_max_bytes < 1_000_000:
        return False, "voice_max_bytes must be at least 1000000."

    ok, data, err = _load_toml_data(config_path)
    if not ok:
        return False, err
    telegram = data.get("telegram")
    if not isinstance(telegram, dict):
        telegram = {}
        data["telegram"] = telegram
    telegram["bot_token"] = bot_token.strip()
    telegram["poll_interval"] = int(poll_interval)
    telegram["typing_interval_seconds"] = int(typing_interval_seconds)
    telegram["stream_partial_replies"] = bool(stream_partial_replies)
    telegram["partial_reply_chunk_chars"] = int(partial_reply_chunk_chars)
    telegram["partial_reply_delay_seconds"] = float(partial_reply_delay_seconds)
    telegram["send_max_retries"] = int(send_max_retries)
    telegram["send_backoff_seconds"] = float(send_backoff_seconds)
    telegram["voice_transcription_enabled"] = bool(voice_transcription_enabled)
    telegram["voice_transcription_model"] = str(voice_transcription_model).strip() or "whisper-1"
    telegram["voice_max_seconds"] = int(voice_max_seconds)
    telegram["voice_max_bytes"] = int(voice_max_bytes)
    return _save_toml_data(config_path, data)


def _save_telegram_settings(config_path: Path, bot_token: str, poll_interval: int) -> tuple[bool, str]:
    # Backward-compatible helper retained for tests and existing callers.
    return _save_telegram_runtime_settings(
        config_path,
        bot_token=bot_token,
        poll_interval=poll_interval,
        typing_interval_seconds=3,
        stream_partial_replies=False,
        partial_reply_chunk_chars=240,
        partial_reply_delay_seconds=0.08,
        send_max_retries=4,
        send_backoff_seconds=1.0,
        voice_transcription_enabled=True,
        voice_transcription_model="whisper-1",
        voice_max_seconds=180,
        voice_max_bytes=25_000_000,
    )


def _save_gateway_settings(config_path: Path, host: str, port: int) -> tuple[bool, str]:
    if port <= 0 or port > 65535:
        return False, "gateway port must be between 1 and 65535."
    ok, data, err = _load_toml_data(config_path)
    if not ok:
        return False, err
    gateway = data.get("gateway")
    if not isinstance(gateway, dict):
        gateway = {}
        data["gateway"] = gateway
    gateway["host"] = host.strip() or "127.0.0.1"
    gateway["port"] = int(port)
    return _save_toml_data(config_path, data)


def _save_agent_model_settings(
    config_path: Path,
    *,
    agent_id: str,
    model: str,
    fallback_models_csv: str,
    request_timeout_seconds: int,
    max_retries: int,
) -> tuple[bool, str]:
    if request_timeout_seconds < 1:
        return False, "request_timeout_seconds must be at least 1."
    if max_retries < 0:
        return False, "max_retries cannot be negative."
    fallback_models = [item.strip() for item in fallback_models_csv.split(",") if item.strip()]

    ok, data, err = _load_toml_data(config_path)
    if not ok:
        return False, err

    agents = data.get("agents")
    if not isinstance(agents, list):
        return False, "invalid config: [[agents]] section missing"

    updated = False
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        if str(agent.get("id", "")) != agent_id:
            continue
        agent["model"] = model.strip() or str(agent.get("model", ""))
        agent["fallback_models"] = fallback_models
        updated = True
        break
    if not updated:
        return False, f"agent '{agent_id}' not found"

    llm = data.get("llm")
    if not isinstance(llm, dict):
        llm = {}
        data["llm"] = llm
    llm["request_timeout_seconds"] = int(request_timeout_seconds)
    llm["max_retries"] = int(max_retries)

    return _save_toml_data(config_path, data)


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


def _metrics_rows(events: list[dict]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if event.get("role") != "metrics":
            continue
        content = event.get("content")
        if not isinstance(content, dict):
            continue
        rows.append(
            {
                "created_at": str(event.get("created_at", "")),
                "duration_ms": int(content.get("duration_ms", 0) or 0),
                "gateway_duration_ms": int(content.get("gateway_duration_ms", 0) or 0),
                "input_tokens": int(content.get("input_tokens", 0) or 0),
                "output_tokens": int(content.get("output_tokens", 0) or 0),
                "context_tokens_estimate": int(content.get("context_tokens_estimate", 0) or 0),
                "context_compacted": bool(content.get("context_compacted", False)),
                "context_overflow_retried": bool(content.get("context_overflow_retried", False)),
                "failover_count": int(content.get("failover_count", 0) or 0),
                "model_used": str(content.get("model_used", "")),
                "tool_calls": int(len(content.get("tool_calls") or [])),
            }
        )
    rows.reverse()
    return rows


def _tail_file_lines(path: Path, max_lines: int = 200) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= max_lines:
        return lines
    return lines[-max_lines:]


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


def _session_state_key(agent_id: str, name: str) -> str:
    return f"{name}::{agent_id}"


def render_welcome_page() -> None:
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    st.title("CodeClaw Control Center")
    st.caption("Unified gateway + Telegram runtime with operational visibility.")

    col1, col2, col3 = st.columns(3)
    col1.metric("Gateway", f"{config.gateway.host}:{config.gateway.port}")
    col2.metric("Agents", str(len(config.agents)))
    col3.metric("Telegram Poll", f"{config.telegram.poll_interval}s")

    health = _request_json("GET", f"{_gateway_url(config)}/health", timeout=5)
    runtime = _request_json("GET", f"{_gateway_url(config)}/api/runtime/status", timeout=5)

    st.subheader("Runtime Status")
    if health.get("ok"):
        st.success("Gateway is healthy")
    else:
        st.error(f"Gateway health check failed: {health.get('error', 'unknown error')}")

    if runtime.get("ok"):
        telegram = runtime.get("telegram", {})
        gateway_info = runtime.get("gateway", {})
        st.json(
            {
                "gateway": gateway_info,
                "telegram": {
                    "running": telegram.get("running", False),
                    "worker_count": (telegram.get("dispatcher") or {}).get("worker_count", 0),
                    "dropped_updates": (telegram.get("dispatcher") or {}).get("dropped_updates", 0),
                    "offset": telegram.get("offset", 0),
                    "last_error": telegram.get("last_error", ""),
                },
            }
        )
    else:
        st.warning(f"Unable to read runtime status: {runtime.get('error', 'unknown error')}")

    st.subheader("Available Agents")
    st.table(
        [
            {
                "id": agent.id,
                "name": agent.name,
                "provider": agent.provider,
                "model": agent.model,
                "fallback_models": ", ".join(agent.fallback_models) if getattr(agent, "fallback_models", None) else "",
            }
            for agent in config.agents
        ]
    )

    st.subheader("Pages")
    st.markdown("- `Chat`: interact with sessions and view plans in real time.")
    st.markdown("- `Configuration`: change Telegram, gateway, and model/runtime settings.")
    st.markdown("- `Logs and Processing`: inspect queue state, metrics, audit entries, and event logs.")


def render_chat_page() -> None:
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    st.title("Chat")

    agent_ids = [a.id for a in config.agents]
    agent_id = st.sidebar.selectbox("Agent", agent_ids, key="chat_agent_select")

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
    session_map = {s["title"] + " | " + s["id"]: s["id"] for s in sessions if isinstance(s, dict) and s.get("id")}
    session_choices = ["New"] + list(session_map.keys())

    state_key = _session_state_key(agent_id, "active_session_id")
    session_choice_key = _session_state_key(agent_id, "session_choice")
    prev_session_choice_key = _session_state_key(agent_id, "prev_session_choice")
    pending_msg_key = _session_state_key(agent_id, "pending_user_msg")
    pending_err_key = _session_state_key(agent_id, "pending_user_err")
    plan_key = _session_state_key(agent_id, "active_plan")

    st.session_state.setdefault(state_key, None)
    st.session_state.setdefault(session_choice_key, "New")
    st.session_state.setdefault(prev_session_choice_key, st.session_state[session_choice_key])
    st.session_state.setdefault(pending_msg_key, "")
    st.session_state.setdefault(pending_err_key, "")
    st.session_state.setdefault(plan_key, [])

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

    events: list[dict] = []
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
        elif role in {"plan", "llm_request", "metrics"}:
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
                    timeout=240,
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


def render_configuration_page() -> None:
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    config_path = _config_path()

    st.title("Configuration")
    st.caption(f"Config file: `{config_path}`")

    st.subheader("Gateway")
    with st.form("gateway_settings_form"):
        gateway_host = st.text_input("Gateway Host", value=config.gateway.host)
        gateway_port = int(
            st.number_input("Gateway Port", min_value=1, max_value=65535, value=int(config.gateway.port), step=1)
        )
        save_gateway = st.form_submit_button("Save Gateway Settings")
    if save_gateway:
        ok, err = _save_gateway_settings(config_path, gateway_host, gateway_port)
        if ok:
            st.success("Gateway settings saved.")
            st.rerun()
        else:
            st.error(err)

    st.subheader("Telegram Runtime")
    with st.form("telegram_runtime_settings_form"):
        bot_token = st.text_input("Bot Token", value=config.telegram.bot_token, type="password")
        poll_interval = int(
            st.number_input("Poll Interval (seconds)", min_value=1, max_value=300, value=int(config.telegram.poll_interval), step=1)
        )
        typing_interval_seconds = int(
            st.number_input(
                "Typing Keepalive Interval (seconds)",
                min_value=1,
                max_value=30,
                value=int(config.telegram.typing_interval_seconds),
                step=1,
            )
        )
        stream_partial_replies = st.checkbox(
            "Enable Partial Reply Streaming",
            value=bool(getattr(config.telegram, "stream_partial_replies", False)),
        )
        partial_reply_chunk_chars = int(
            st.number_input(
                "Partial Reply Chunk Chars",
                min_value=80,
                max_value=2000,
                value=int(getattr(config.telegram, "partial_reply_chunk_chars", 240)),
                step=20,
            )
        )
        partial_reply_delay_seconds = float(
            st.number_input(
                "Partial Reply Delay (seconds)",
                min_value=0.01,
                max_value=1.0,
                value=float(getattr(config.telegram, "partial_reply_delay_seconds", 0.08)),
                step=0.01,
                format="%.2f",
            )
        )
        send_max_retries = int(
            st.number_input(
                "Send Max Retries",
                min_value=0,
                max_value=20,
                value=int(getattr(config.telegram, "send_max_retries", 4)),
                step=1,
            )
        )
        send_backoff_seconds = float(
            st.number_input(
                "Send Backoff Seconds",
                min_value=0.05,
                max_value=30.0,
                value=float(getattr(config.telegram, "send_backoff_seconds", 1.0)),
                step=0.05,
                format="%.2f",
            )
        )
        voice_transcription_enabled = st.checkbox(
            "Enable Voice Transcription",
            value=bool(getattr(config.telegram, "voice_transcription_enabled", True)),
        )
        voice_transcription_model = st.text_input(
            "Voice Transcription Model",
            value=str(getattr(config.telegram, "voice_transcription_model", "whisper-1")),
        )
        voice_max_seconds = int(
            st.number_input(
                "Voice Max Duration (seconds)",
                min_value=1,
                max_value=900,
                value=int(getattr(config.telegram, "voice_max_seconds", 180)),
                step=1,
            )
        )
        voice_max_bytes = int(
            st.number_input(
                "Voice Max Size (bytes)",
                min_value=1_000_000,
                max_value=100_000_000,
                value=int(getattr(config.telegram, "voice_max_bytes", 25_000_000)),
                step=100_000,
            )
        )
        save_telegram = st.form_submit_button("Save Telegram Settings")
    if save_telegram:
        ok, err = _save_telegram_runtime_settings(
            config_path,
            bot_token=bot_token,
            poll_interval=poll_interval,
            typing_interval_seconds=typing_interval_seconds,
            stream_partial_replies=stream_partial_replies,
            partial_reply_chunk_chars=partial_reply_chunk_chars,
            partial_reply_delay_seconds=partial_reply_delay_seconds,
            send_max_retries=send_max_retries,
            send_backoff_seconds=send_backoff_seconds,
            voice_transcription_enabled=voice_transcription_enabled,
            voice_transcription_model=voice_transcription_model,
            voice_max_seconds=voice_max_seconds,
            voice_max_bytes=voice_max_bytes,
        )
        if ok:
            st.success("Telegram settings saved.")
            st.rerun()
        else:
            st.error(err)

    st.subheader("Model Runtime")
    agent_ids = [a.id for a in config.agents]
    selected_agent_id = st.selectbox("Agent", agent_ids, key="config_agent_select")
    selected_agent = next((a for a in config.agents if a.id == selected_agent_id), config.agents[0])

    with st.form("model_runtime_settings_form"):
        model = st.text_input("Primary Model", value=selected_agent.model)
        fallback_models_csv = st.text_input(
            "Fallback Models (comma-separated)",
            value=", ".join(getattr(selected_agent, "fallback_models", [])),
        )
        request_timeout_seconds = int(
            st.number_input(
                "LLM Request Timeout (seconds)",
                min_value=1,
                max_value=1800,
                value=int(config.llm.request_timeout_seconds),
                step=1,
            )
        )
        max_retries = int(
            st.number_input(
                "LLM Max Retries",
                min_value=0,
                max_value=20,
                value=int(config.llm.max_retries),
                step=1,
            )
        )
        save_model_runtime = st.form_submit_button("Save Model Runtime Settings")
    if save_model_runtime:
        ok, err = _save_agent_model_settings(
            config_path,
            agent_id=selected_agent_id,
            model=model,
            fallback_models_csv=fallback_models_csv,
            request_timeout_seconds=request_timeout_seconds,
            max_retries=max_retries,
        )
        if ok:
            st.success("Model runtime settings saved.")
            st.rerun()
        else:
            st.error(err)


def render_logs_page() -> None:
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    st.title("Logs and Processing")

    runtime = _request_json("GET", f"{_gateway_url(config)}/api/runtime/status", timeout=10)
    st.subheader("Integrated Runtime")
    if runtime.get("ok"):
        st.json(runtime)
    else:
        st.error(runtime.get("error", "failed to load runtime status"))

    agent_ids = [a.id for a in config.agents]
    agent_id = st.selectbox("Agent", agent_ids, key="logs_agent_select")

    sessions_resp = _request_json(
        "GET",
        f"{_gateway_url(config)}/api/session/list",
        params={"agent_id": agent_id},
        timeout=10,
    )
    sessions = sessions_resp.get("sessions", []) if sessions_resp.get("ok", True) else []
    session_map = {s["title"] + " | " + s["id"]: s["id"] for s in sessions if isinstance(s, dict) and s.get("id")}
    session_choice = st.selectbox("Session", ["None"] + list(session_map.keys()), key="logs_session_select")
    session_id = session_map.get(session_choice)

    events: list[dict] = []
    if session_id:
        events_resp = _request_json(
            "GET",
            f"{_gateway_url(config)}/api/session/events",
            params={"agent_id": agent_id, "session_id": session_id},
            timeout=10,
        )
        if events_resp.get("ok", True):
            events = events_resp.get("events", [])

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("LLM Requests")
        req_rows = _llm_requests(events)
        if req_rows:
            st.dataframe(req_rows, use_container_width=True)
        else:
            st.caption("No request rows yet.")

    with col2:
        st.subheader("Metrics")
        metric_rows = _metrics_rows(events)
        if metric_rows:
            st.dataframe(metric_rows, use_container_width=True)
        else:
            st.caption("No metrics rows yet.")

    st.subheader("Recent Event Log")
    if events:
        tail_events = events[-100:]
        st.json(tail_events)
    else:
        st.caption("No events for selected session.")

    st.subheader("Self-Update Audit")
    audit_path = Path(config.self_update.audit_log_path).expanduser()
    lines = _tail_file_lines(audit_path, max_lines=200)
    if lines:
        st.code("\n".join(lines), language="json")
    else:
        st.caption(f"No audit entries found at {audit_path}")

    agent_audit_path = Path(config.storage.base_path).expanduser() / agent_id / "sessions" / "audit.jsonl"
    st.subheader("Per-Agent Audit")
    agent_audit_lines = _tail_file_lines(agent_audit_path, max_lines=200)
    if agent_audit_lines:
        st.code("\n".join(agent_audit_lines), language="json")
    else:
        st.caption(f"No per-agent audit entries found at {agent_audit_path}")


def main() -> None:
    # Backward-compatible default entrypoint.
    render_welcome_page()


if __name__ == "__main__":
    main()
