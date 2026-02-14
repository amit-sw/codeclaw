from __future__ import annotations

import asyncio
import json

import websockets


async def _recv_for_id(ws, req_id: int):
    while True:
        raw = await ws.recv()
        frame = json.loads(raw)
        if frame.get("type") == "res" and frame.get("id") == req_id:
            return frame


async def ws_request(url: str, token: str, password: str, method: str, params: dict):
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "req", "id": 1, "method": "connect", "params": {"token": token, "password": password, "client": "cli"}}))
        connect_res = await _recv_for_id(ws, 1)
        if connect_res.get("error"):
            raise RuntimeError(connect_res["error"])
        await ws.send(json.dumps({"type": "req", "id": 2, "method": method, "params": params}))
        res = await _recv_for_id(ws, 2)
        if res.get("error"):
            raise RuntimeError(res["error"])
        return res.get("result")


def ws_request_sync(url: str, token: str, password: str, method: str, params: dict):
    return asyncio.run(ws_request(url, token, password, method, params))
