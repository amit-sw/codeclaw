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


@dataclass
class WorkItem:
    update_id: int
    chat_id: int
    text: str
    voice_file_id: str = ""
    voice_duration_seconds: int = 0
    voice_mime_type: str = "audio/ogg"


class ChatWorker:
    def __init__(self, config: AppConfig, chat_id: int, agent_id: str):
        self.config = config
        self.chat_id = chat_id
        self.agent_id = agent_id
        self.queue: queue.Queue[WorkItem | None] = queue.Queue(maxsize=max(1, int(config.telegram.max_queue_per_chat)))
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"codeclaw-tg-chat-{chat_id}")
        self._session_id: str | None = None
        self._processed = 0
        self._last_update_id = 0
        self._last_duration_ms = 0
        self._last_error = ""
        self._running = True
        self._thread.start()

    def enqueue(self, item: WorkItem) -> bool:
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            return False
        return True

    def stop(self) -> None:
        self._running = False
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=2.0)

    def status(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "queue_depth": self.queue.qsize(),
            "processed": self._processed,
            "last_update_id": self._last_update_id,
            "last_duration_ms": self._last_duration_ms,
            "last_error": self._last_error,
            "active": self._running,
        }

    def _run(self) -> None:
        while self._running:
            item = self.queue.get()
            try:
                if item is None:
                    return
                self._process_item(item)
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"{exc.__class__.__name__}: {exc}"
                log.exception("telegram worker failure chat_id=%s err=%s", self.chat_id, exc)
            finally:
                self.queue.task_done()

    def _process_item(self, item: WorkItem) -> None:
        typing = TypingLoop(self.config, self.chat_id)
        typing.start()
        started = time.perf_counter()
        try:
            user_text = item.text.strip()
            if not user_text and item.voice_file_id:
                transcribed = _transcribe_voice_message(
                    self.config,
                    file_id=item.voice_file_id,
                    duration_seconds=item.voice_duration_seconds,
                    mime_type=item.voice_mime_type,
                )
                if not transcribed.get("ok"):
                    self._processed += 1
                    self._last_update_id = item.update_id
                    self._last_duration_ms = int((time.perf_counter() - started) * 1000)
                    self._last_error = str(transcribed.get("error", "Voice transcription failed."))
                    _send_telegram_message(
                        self.config,
                        self.chat_id,
                        f"Voice transcription failed: {self._last_error}",
                        stream_partial=False,
                    )
                    return
                user_text = str(transcribed.get("text", "")).strip()
                if not user_text:
                    self._processed += 1
                    self._last_update_id = item.update_id
                    self._last_duration_ms = int((time.perf_counter() - started) * 1000)
                    self._last_error = "Transcription was empty."
                    _send_telegram_message(
                        self.config,
                        self.chat_id,
                        "I could not hear any speech in that voice message. Please try again.",
                        stream_partial=False,
                    )
                    return
                log.info(
                    "telegram voice transcribed chat_id=%s update_id=%s chars=%s",
                    self.chat_id,
                    item.update_id,
                    len(user_text),
                )
            result = _send_gateway(
                self.config,
                self.agent_id,
                user_text,
                self._session_id,
                str(self.chat_id),
                queue_depth=self.queue.qsize(),
                stream_partial=self.config.telegram.stream_partial_replies,
            )
        finally:
            typing.stop()

        self._processed += 1
        self._last_update_id = item.update_id
        self._last_duration_ms = int((time.perf_counter() - started) * 1000)

        if result.get("ok"):
            self._last_error = ""
            self._session_id = result.get("session_id") or self._session_id
            reply = str(result.get("assistant_message", "")).strip() or "No response."
        else:
            self._last_error = str(result.get("error", "Request failed."))
            reply = self._last_error.strip() or "Request failed."

        _send_telegram_message(
            self.config,
            self.chat_id,
            reply,
            stream_partial=self.config.telegram.stream_partial_replies,
        )
        log.info(
            "telegram turn chat_id=%s update_id=%s duration_ms=%s queue_depth=%s ok=%s",
            self.chat_id,
            item.update_id,
            self._last_duration_ms,
            self.queue.qsize(),
            bool(result.get("ok")),
        )


class TelegramDispatcher:
    def __init__(self, config: AppConfig):
        self.config = config
        self.agent_id = config.agents[0].id
        self._workers: dict[int, ChatWorker] = {}
        self._lock = threading.Lock()
        self._dropped_updates = 0

    def enqueue(self, item: WorkItem) -> None:
        worker = self._worker_for_chat(item.chat_id)
        accepted = worker.enqueue(item)
        if not accepted:
            self._dropped_updates += 1
            log.warning("telegram queue full for chat_id=%s; dropping update_id=%s", item.chat_id, item.update_id)

    def stop(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.stop()

    def status(self) -> dict[str, Any]:
        with self._lock:
            workers = list(self._workers.values())
        return {
            "worker_count": len(workers),
            "dropped_updates": self._dropped_updates,
            "workers": [worker.status() for worker in workers],
        }

    def _worker_for_chat(self, chat_id: int) -> ChatWorker:
        with self._lock:
            existing = self._workers.get(chat_id)
            if existing is not None:
                return existing
            worker = ChatWorker(self.config, chat_id=chat_id, agent_id=self.agent_id)
            self._workers[chat_id] = worker
            return worker


class TelegramPoller:
    def __init__(self, config: AppConfig):
        self.config = config
        self.dispatcher = TelegramDispatcher(config)
        self.offset = _load_offset(config)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._last_error = ""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._started_at = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True, name="codeclaw-telegram-poller")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        self.dispatcher.stop()

    def status(self) -> dict[str, Any]:
        running = self._thread is not None and self._thread.is_alive() and not self._stop.is_set()
        return {
            "enabled": True,
            "running": running,
            "offset": self.offset,
            "last_error": self._last_error,
            "uptime_seconds": int(time.time() - self._started_at) if self._started_at else 0,
            "dispatcher": self.dispatcher.status(),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            data = _fetch_updates(self.config, self.offset)
            updates = data.get("result", [])
            if not isinstance(updates, list):
                updates = []
            if not data.get("ok", True):
                self._last_error = str(data.get("error", "telegram polling failed"))
            for update in updates:
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id", self.offset)
                if isinstance(update_id, int):
                    self.offset = max(self.offset, update_id + 1)
                    _save_offset(self.config, self.offset)
                item = _work_item_from_update(update, default_update_id=int(update_id) if isinstance(update_id, int) else 0)
                if item is None:
                    continue
                self.dispatcher.enqueue(item)
            self._stop.wait(max(0.05, float(self.config.telegram.poll_interval)))


_ACTIVE_POLLER: TelegramPoller | None = None
_POLLER_LOCK = threading.Lock()


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


def _work_item_from_update(update: dict[str, Any], default_update_id: int = 0) -> WorkItem | None:
    if not isinstance(update, dict):
        return None
    message = update.get("message") or {}
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return None
    raw_update_id = update.get("update_id", default_update_id)
    update_id = int(raw_update_id) if isinstance(raw_update_id, int) else int(default_update_id)

    text = str(message.get("text") or "").strip()
    if text:
        return WorkItem(update_id=update_id, chat_id=chat_id, text=text)

    voice = message.get("voice") or {}
    if not isinstance(voice, dict):
        return None
    file_id = str(voice.get("file_id") or "").strip()
    if not file_id:
        return None
    raw_duration = voice.get("duration", 0)
    duration_seconds = int(raw_duration) if isinstance(raw_duration, int) else 0
    mime_type = str(voice.get("mime_type") or "audio/ogg")
    return WorkItem(
        update_id=update_id,
        chat_id=chat_id,
        text="",
        voice_file_id=file_id,
        voice_duration_seconds=max(0, duration_seconds),
        voice_mime_type=mime_type,
    )


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


def _download_telegram_file(config: AppConfig, file_path: str, max_bytes: int) -> dict[str, Any]:
    url = f"https://api.telegram.org/file/bot{config.telegram.bot_token}/{file_path}"
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=30.0)
    try:
        response = httpx.get(url, timeout=timeout)
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"telegram file download failed: {exc}"}
    if response.status_code >= 400:
        return {"ok": False, "error": f"telegram file download failed (HTTP {response.status_code})"}
    payload = response.content
    if len(payload) > max_bytes:
        return {"ok": False, "error": f"voice message too large ({len(payload)} bytes > {max_bytes} bytes)"}
    content_type = response.headers.get("content-type", "application/octet-stream")
    return {"ok": True, "bytes": payload, "content_type": content_type}


def _transcribe_openai_audio(
    config: AppConfig,
    *,
    model: str,
    filename: str,
    content_type: str,
    audio_bytes: bytes,
) -> dict[str, Any]:
    api_key = str(config.llm.openai.api_key or "").strip()
    if not api_key:
        return {"ok": False, "error": "openai api key is missing for voice transcription"}
    base_url = str(config.llm.openai.base_url or "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/audio/transcriptions"
    timeout = httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=30.0)
    headers = {"Authorization": f"Bearer {api_key}"}
    files = {"file": (filename, audio_bytes, content_type)}
    data = {"model": model}
    try:
        response = httpx.post(url, headers=headers, data=data, files=files, timeout=timeout)
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"openai transcription request failed: {exc}"}
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": {"message": response.text[:500] if response.text else "non-json response"}}
    if response.status_code >= 400:
        error_message = ""
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                error_message = str(err.get("message", "")).strip()
            elif err:
                error_message = str(err).strip()
        if not error_message:
            error_message = f"HTTP {response.status_code}"
        return {"ok": False, "error": f"openai transcription failed: {error_message}"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "openai transcription returned invalid payload"}
    text = str(payload.get("text") or "").strip()
    return {"ok": True, "text": text}


def _transcribe_voice_message(
    config: AppConfig,
    *,
    file_id: str,
    duration_seconds: int = 0,
    mime_type: str = "audio/ogg",
) -> dict[str, Any]:
    if not bool(config.telegram.voice_transcription_enabled):
        return {"ok": False, "error": "voice transcription is disabled"}
    if duration_seconds > int(config.telegram.voice_max_seconds):
        return {
            "ok": False,
            "error": (
                f"voice message too long ({duration_seconds}s > "
                f"{int(config.telegram.voice_max_seconds)}s limit)"
            ),
        }
    file_meta = _telegram_api_post(config, "getFile", {"file_id": file_id}, timeout_seconds=20.0)
    if not file_meta.get("ok"):
        return {"ok": False, "error": str(file_meta.get("error", "telegram getFile failed"))}
    result = file_meta.get("result")
    if not isinstance(result, dict):
        return {"ok": False, "error": "telegram getFile returned invalid result"}
    file_path = str(result.get("file_path") or "").strip()
    if not file_path:
        return {"ok": False, "error": "telegram getFile did not return file_path"}

    max_bytes = max(1_000_000, int(config.telegram.voice_max_bytes))
    downloaded = _download_telegram_file(config, file_path, max_bytes=max_bytes)
    if not downloaded.get("ok"):
        return downloaded

    payload = downloaded.get("bytes")
    if not isinstance(payload, bytes) or not payload:
        return {"ok": False, "error": "downloaded voice payload was empty"}
    content_type = str(downloaded.get("content_type") or mime_type or "audio/ogg")
    model = str(config.telegram.voice_transcription_model or "whisper-1").strip() or "whisper-1"
    filename = Path(file_path).name or "voice.ogg"
    transcribed = _transcribe_openai_audio(
        config,
        model=model,
        filename=filename,
        content_type=content_type,
        audio_bytes=payload,
    )
    if not transcribed.get("ok"):
        return transcribed
    return {
        "ok": True,
        "text": str(transcribed.get("text") or "").strip(),
        "model": model,
        "duration_seconds": duration_seconds,
        "bytes": len(payload),
    }


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


def start_poller_in_background(config: AppConfig) -> TelegramPoller:
    global _ACTIVE_POLLER
    with _POLLER_LOCK:
        if _ACTIVE_POLLER is not None:
            return _ACTIVE_POLLER
        poller = TelegramPoller(config)
        poller.start()
        _ACTIVE_POLLER = poller
        return poller


def stop_active_poller() -> None:
    global _ACTIVE_POLLER
    with _POLLER_LOCK:
        poller = _ACTIVE_POLLER
        _ACTIVE_POLLER = None
    if poller is not None:
        poller.stop()


def get_active_poller_status() -> dict[str, Any]:
    with _POLLER_LOCK:
        poller = _ACTIVE_POLLER
    if poller is None:
        return {"enabled": False, "running": False}
    return poller.status()


def poll_loop():
    config = load_config(os.environ.get("CODECLAW_CONFIG"))
    poller = TelegramPoller(config)
    try:
        poller.start()
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()


def main():
    poll_loop()


if __name__ == "__main__":
    main()
