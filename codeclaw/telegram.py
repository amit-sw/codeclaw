from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from codeclaw.config import AppConfig, load_config

log = logging.getLogger(__name__)


def _gateway_url(config: AppConfig):
    return f"http://{config.gateway.host}:{config.gateway.port}"


def _send_gateway(
    config: AppConfig,
    agent_id: str,
    message: str,
    session_id: str | None,
    peer: str,
    queue_depth: int | None = None,
    stream_partial: bool = False,
) -> dict:
    timeout_seconds = int(os.environ.get("CODECLAW_TELEGRAM_GATEWAY_TIMEOUT", "300"))
    timeout = httpx.Timeout(connect=10.0, read=float(timeout_seconds), write=30.0, pool=30.0)
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "message": message,
        "session_id": session_id,
        "channel": "telegram",
        "peer": peer,
        "stream_partial": stream_partial,
    }
    if queue_depth is not None:
        payload["queue_depth"] = int(queue_depth)
    try:
        resp = httpx.post(
            f"{_gateway_url(config)}/api/session/send",
            json=payload,
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


def _offset_path(config: AppConfig) -> Path:
    return Path(config.telegram.offset_path).expanduser()


def _load_offset(config: AppConfig) -> int:
    path = _offset_path(config)
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    value = payload.get("offset", 0)
    if isinstance(value, int):
        return max(0, value)
    return 0


def _save_offset(config: AppConfig, offset: int) -> None:
    path = _offset_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"offset": max(0, int(offset))}))


def _telegram_api_post(
    config: AppConfig,
    method: str,
    payload: dict[str, Any],
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    retries = max(0, int(config.telegram.send_max_retries))
    backoff = max(0.05, float(config.telegram.send_backoff_seconds))
    url = f"https://api.telegram.org/bot{config.telegram.bot_token}/{method}"
    attempt = 0
    while True:
        attempt += 1
        try:
            response = httpx.post(url, json=payload, timeout=timeout_seconds)
        except httpx.RequestError as exc:
            if attempt > retries:
                return {"ok": False, "error": f"telegram request failed: {exc}"}
            time.sleep(backoff * attempt)
            continue

        try:
            data = response.json()
        except ValueError:
            data = {"ok": False, "error": f"telegram returned non-json ({response.status_code})"}

        if response.status_code == 429:
            retry_after = 0
            params = (data.get("parameters") if isinstance(data, dict) else None) or {}
            if isinstance(params, dict):
                retry_after_raw = params.get("retry_after")
                if isinstance(retry_after_raw, int):
                    retry_after = retry_after_raw
            if attempt > retries:
                return {"ok": False, "error": "telegram rate limit exceeded", "response": data}
            time.sleep(max(backoff * attempt, retry_after))
            continue

        if response.status_code >= 500:
            if attempt > retries:
                return {"ok": False, "error": f"telegram server error {response.status_code}", "response": data}
            time.sleep(backoff * attempt)
            continue

        if isinstance(data, dict):
            return data
        return {"ok": False, "error": "telegram returned invalid payload"}


def _send_chat_action(config: AppConfig, chat_id: int, action: str = "typing") -> None:
    _telegram_api_post(config, "sendChatAction", {"chat_id": chat_id, "action": action}, timeout_seconds=10.0)


def _send_telegram_message(
    config: AppConfig,
    chat_id: int,
    text: str,
    stream_partial: bool = False,
) -> None:
    normalized = text.strip() or "No response."
    if not stream_partial:
        _telegram_api_post(config, "sendMessage", {"chat_id": chat_id, "text": normalized})
        return

    chunk_size = max(80, int(config.telegram.partial_reply_chunk_chars))
    if len(normalized) <= chunk_size:
        _telegram_api_post(config, "sendMessage", {"chat_id": chat_id, "text": normalized})
        return

    head = normalized[:chunk_size]
    tail = normalized[chunk_size:]
    sent = _telegram_api_post(config, "sendMessage", {"chat_id": chat_id, "text": head})
    if not sent.get("ok"):
        _telegram_api_post(config, "sendMessage", {"chat_id": chat_id, "text": normalized})
        return
    result = sent.get("result", {})
    if not isinstance(result, dict):
        _telegram_api_post(config, "sendMessage", {"chat_id": chat_id, "text": normalized})
        return
    message_id = result.get("message_id")
    if not isinstance(message_id, int):
        _telegram_api_post(config, "sendMessage", {"chat_id": chat_id, "text": normalized})
        return

    delay = max(0.01, float(config.telegram.partial_reply_delay_seconds))
    current = head
    index = 0
    while index < len(tail):
        next_piece = tail[index : index + chunk_size]
        index += chunk_size
        current += next_piece
        _telegram_api_post(
            config,
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": current},
        )
        time.sleep(delay)


class TypingLoop:
    def __init__(self, config: AppConfig, chat_id: int):
        self.config = config
        self.chat_id = chat_id
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        interval = max(1, int(self.config.telegram.typing_interval_seconds))
        while not self._stop.is_set():
            _send_chat_action(self.config, self.chat_id, action="typing")
            self._stop.wait(interval)


@dataclass
class WorkItem:
    update_id: int
    chat_id: int
    text: str


class ChatWorker:
    def __init__(self, config: AppConfig, chat_id: int, agent_id: str):
        self.config = config
        self.chat_id = chat_id
        self.agent_id = agent_id
        self.queue: queue.Queue[WorkItem] = queue.Queue(maxsize=max(1, int(config.telegram.max_queue_per_chat)))
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"codeclaw-tg-chat-{chat_id}")
        self._session_id: str | None = None
        self._thread.start()

    def enqueue(self, item: WorkItem) -> bool:
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            return False
        return True

    def qsize(self) -> int:
        return self.queue.qsize()

    def _run(self) -> None:
        while True:
            item = self.queue.get()
            try:
                self._process_item(item)
            except Exception as exc:  # noqa: BLE001
                log.exception("telegram worker failure chat_id=%s err=%s", self.chat_id, exc)
            finally:
                self.queue.task_done()

    def _process_item(self, item: WorkItem) -> None:
        typing = TypingLoop(self.config, self.chat_id)
        typing.start()
        started = time.perf_counter()
        try:
            result = _send_gateway(
                self.config,
                self.agent_id,
                item.text,
                self._session_id,
                str(self.chat_id),
                queue_depth=self.queue.qsize(),
                stream_partial=self.config.telegram.stream_partial_replies,
            )
        finally:
            typing.stop()

        if result.get("ok"):
            self._session_id = result.get("session_id") or self._session_id
            reply = str(result.get("assistant_message", "")).strip() or "No response."
        else:
            reply = str(result.get("error", "Request failed.")).strip() or "Request failed."

        _send_telegram_message(
            self.config,
            self.chat_id,
            reply,
            stream_partial=self.config.telegram.stream_partial_replies,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "telegram turn chat_id=%s update_id=%s duration_ms=%s queue_depth=%s ok=%s",
            self.chat_id,
            item.update_id,
            elapsed_ms,
            self.queue.qsize(),
            bool(result.get("ok")),
        )


class TelegramDispatcher:
    def __init__(self, config: AppConfig):
        self.config = config
        self.agent_id = config.agents[0].id
        self._workers: dict[int, ChatWorker] = {}
        self._lock = threading.Lock()

    def enqueue(self, item: WorkItem) -> None:
        worker = self._worker_for_chat(item.chat_id)
        accepted = worker.enqueue(item)
        if not accepted:
            log.warning("telegram queue full for chat_id=%s; dropping update_id=%s", item.chat_id, item.update_id)

    def _worker_for_chat(self, chat_id: int) -> ChatWorker:
        with self._lock:
            existing = self._workers.get(chat_id)
            if existing is not None:
                return existing
            worker = ChatWorker(self.config, chat_id=chat_id, agent_id=self.agent_id)
            self._workers[chat_id] = worker
            return worker


def _fetch_updates(config: AppConfig, offset: int) -> dict[str, Any]:
    try:
        response = httpx.get(
            f"https://api.telegram.org/bot{config.telegram.bot_token}/getUpdates",
            params={"timeout": 30, "offset": offset},
            timeout=35,
        )
        return response.json()
    except (httpx.RequestError, ValueError) as exc:
        return {"ok": False, "error": str(exc), "result": []}


def poll_loop():
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    dispatcher = TelegramDispatcher(config)
    offset = _load_offset(config)
    while True:
        data = _fetch_updates(config, offset)
        updates = data.get("result", [])
        if not isinstance(updates, list):
            updates = []
        for update in updates:
            if not isinstance(update, dict):
                continue
            update_id = update.get("update_id", offset)
            if isinstance(update_id, int):
                offset = max(offset, update_id + 1)
                _save_offset(config, offset)
            message = update.get("message") or {}
            text = str(message.get("text") or "")
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            if not isinstance(chat_id, int) or not text.strip():
                continue
            dispatcher.enqueue(WorkItem(update_id=int(update_id) if isinstance(update_id, int) else 0, chat_id=chat_id, text=text))
        time.sleep(max(0.05, float(config.telegram.poll_interval)))


def main():
    poll_loop()


if __name__ == "__main__":
    main()
