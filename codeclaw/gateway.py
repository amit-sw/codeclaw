from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header
from pydantic import BaseModel

from codeclaw.approvals import ApprovalsStore
from codeclaw.agent import AgentRuntime
from codeclaw.config import AppConfig, load_config
from codeclaw.storage import SessionStore
from codeclaw.tools import ToolRegistry


class SendRequest(BaseModel):
    agent_id: str
    message: str
    session_id: str | None = None
    channel: str = "cli"
    peer: str = "local"


def _load_app_config() -> AppConfig:
    return load_config(os.environ.get("CODECLAW_CONFIG"))


def _auth_ok(token: str | None, password: str | None, config: AppConfig) -> bool:
    if token is None or password is None:
        return False
    return token == config.gateway.token and password == config.gateway.password


def _error_payload(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}


def create_app() -> FastAPI:
    config = _load_app_config()
    store = SessionStore(config.storage)
    approvals = ApprovalsStore(config.tools.approvals_path)
    tools = ToolRegistry(config.tools, approvals)
    runtime = AgentRuntime(config, store, tools)

    app = FastAPI()

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/api/agents")
    def agents(x_token: str | None = Header(default=None), x_password: str | None = Header(default=None)):
        if not _auth_ok(x_token, x_password, config):
            return {"ok": False, "error": "unauthorized"}
        return {"ok": True, "agents": [a.model_dump() for a in config.agents]}

    @app.post("/api/session/send")
    def session_send(req: SendRequest, x_token: str | None = Header(default=None), x_password: str | None = Header(default=None)):
        if not _auth_ok(x_token, x_password, config):
            return {"ok": False, "error": "unauthorized"}
        try:
            session = _get_or_create_session(store, req.agent_id, req.channel, req.peer, req.session_id, req.message)
            store.append_event(req.agent_id, session["id"], {"role": "user", "content": req.message})
            assistant = runtime.run_turn(req.agent_id, session["id"], req.message, req.channel, interactive=False)
            store.append_event(req.agent_id, session["id"], {"role": "assistant", "content": assistant})
            return {"ok": True, "session_id": session["id"], "assistant_message": assistant}
        except Exception as exc:
            return _error_payload(exc)

    @app.get("/api/session/list")
    def session_list(agent_id: str, x_token: str | None = Header(default=None), x_password: str | None = Header(default=None)):
        if not _auth_ok(x_token, x_password, config):
            return {"ok": False, "error": "unauthorized"}
        try:
            return {"ok": True, "sessions": store.list_sessions(agent_id)}
        except Exception as exc:
            return _error_payload(exc)

    @app.get("/api/session/events")
    def session_events(agent_id: str, session_id: str, x_token: str | None = Header(default=None), x_password: str | None = Header(default=None)):
        if not _auth_ok(x_token, x_password, config):
            return {"ok": False, "error": "unauthorized"}
        try:
            return {"ok": True, "events": store.read_events(agent_id, session_id)}
        except Exception as exc:
            return _error_payload(exc)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        authed = False
        try:
            while True:
                raw = await ws.receive_text()
                frame = json.loads(raw)
                if frame.get("type") != "req":
                    await ws.send_text(json.dumps({"type": "res", "id": frame.get("id"), "error": {"message": "invalid frame"}}))
                    continue
                method = frame.get("method")
                params = frame.get("params", {})
                req_id = frame.get("id")
                if method == "connect":
                    token = params.get("token")
                    password = params.get("password")
                    if _auth_ok(token, password, config):
                        authed = True
                        await ws.send_text(json.dumps({"type": "res", "id": req_id, "result": {"ok": True, "server_info": {"name": "codeclaw-lite"}}}))
                    else:
                        await ws.send_text(json.dumps({"type": "res", "id": req_id, "error": {"message": "unauthorized"}}))
                    continue
                if not authed:
                    await ws.send_text(json.dumps({"type": "res", "id": req_id, "error": {"message": "not connected"}}))
                    continue
                try:
                    result = _handle_ws_request(method, params, store, runtime, config)
                except Exception as exc:
                    await ws.send_text(json.dumps({"type": "res", "id": req_id, "error": {"message": f"{exc.__class__.__name__}: {exc}"}}))
                    continue
                await ws.send_text(json.dumps({"type": "res", "id": req_id, "result": result}))
                if method == "session.send" and result.get("session_id"):
                    await ws.send_text(json.dumps({"type": "event", "method": "session.update", "params": {"session_id": result.get("session_id")}}))
        except WebSocketDisconnect:
            return

    return app


def _get_or_create_session(store: SessionStore, agent_id: str, channel: str, peer: str, session_id: str | None, first_message: str) -> dict:
    if session_id:
        return store.ensure_session(agent_id, session_id, channel, peer, first_message[:80])
    existing = store.find_latest_session(agent_id, channel, peer)
    if existing:
        return existing
    return store.create_session(agent_id, channel, peer, first_message[:80])


def _handle_ws_request(method: str, params: dict, store: SessionStore, runtime: AgentRuntime, config: AppConfig) -> dict:
    if method == "agent.list":
        return {"agents": [a.model_dump() for a in config.agents]}
    if method == "session.list":
        agent_id = params.get("agent_id")
        return {"sessions": store.list_sessions(agent_id)}
    if method == "session.events":
        agent_id = params.get("agent_id")
        session_id = params.get("session_id")
        return {"events": store.read_events(agent_id, session_id)}
    if method == "session.send":
        agent_id = params.get("agent_id")
        channel = params.get("channel", "cli")
        peer = params.get("peer", "local")
        message = params.get("message", "")
        session_id = params.get("session_id")
        session = _get_or_create_session(store, agent_id, channel, peer, session_id, message)
        store.append_event(agent_id, session["id"], {"role": "user", "content": message})
        assistant = runtime.run_turn(agent_id, session["id"], message, channel, interactive=False)
        store.append_event(agent_id, session["id"], {"role": "assistant", "content": assistant})
        return {"session_id": session["id"], "assistant_message": assistant}
    return {"error": f"unknown method {method}"}


app = create_app()
