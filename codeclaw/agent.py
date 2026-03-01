from __future__ import annotations

import inspect
import json
import logging
import os
import pwd
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAI

from codeclaw.config import AppConfig, default_config_path
from codeclaw.storage import SessionStore

log = logging.getLogger(__name__)


def _estimate_tokens_from_text(text: str) -> int:
    # Rough approximation for chat-token budgeting.
    return max(1, (len(text) + 3) // 4)


def _is_context_overflow_error(exc: Exception) -> bool:
    message = str(exc).lower()
    markers = [
        "context length",
        "maximum context",
        "too many tokens",
        "token limit",
        "context window",
        "request too large",
    ]
    return any(marker in message for marker in markers)


def _is_failover_error(exc: Exception) -> bool:
    message = str(exc).lower()
    markers = [
        "timed out",
        "timeout",
        "rate limit",
        "429",
        "temporarily unavailable",
        "overloaded",
    ]
    return any(marker in message for marker in markers)


class AgentRuntime:
    def __init__(self, config: AppConfig, store: SessionStore):
        self.config = config
        self.store = store
        os.environ["LANGCHAIN_API_KEY"] = config.langchain.api_key
        os.environ["LANGSMITH_API_KEY"] = config.langsmith.api_key
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = config.langsmith.project
        os.environ["LANGGRAPH_PROJECT"] = config.langgraph.project
        os.environ["LANGCHAIN_ENDPOINT"] = "https://api.smith.langchain.com"

    def _agent_config(self, agent_id: str):
        for agent in self.config.agents:
            if agent.id == agent_id:
                return agent
        raise ValueError(f"unknown agent {agent_id}")

    def _model_candidates(self, agent_id: str) -> list[str]:
        agent = self._agent_config(agent_id)
        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in [agent.model, *agent.fallback_models]:
            model = str(candidate).strip()
            if not model or model in seen:
                continue
            seen.add(model)
            ordered.append(model)
        return ordered or [agent.model]

    def _llm(self, agent_id: str, model: str) -> ChatOpenAI:
        agent = self._agent_config(agent_id)
        timeout_seconds = max(1, int(self.config.llm.request_timeout_seconds))
        retries = max(0, int(self.config.llm.max_retries))
        if agent.provider == "local" and self.config.llm.local:
            return ChatOpenAI(
                api_key=self.config.llm.local.api_key,
                base_url=self.config.llm.local.base_url,
                model=model,
                timeout=timeout_seconds,
                max_retries=retries,
            )
        return ChatOpenAI(
            api_key=self.config.llm.openai.api_key,
            base_url=self.config.llm.openai.base_url,
            model=model,
            timeout=timeout_seconds,
            max_retries=retries,
        )

    def _build_messages(self, agent_id: str, events: list[dict], user_msg: str) -> list[BaseMessage]:
        agent = self._agent_config(agent_id)
        messages: list[BaseMessage] = [SystemMessage(content=agent.system_prompt or "")]
        for event in events:
            role = event.get("role")
            content = event.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=str(content)))
            elif role == "assistant":
                messages.append(AIMessage(content=str(content)))
            elif role == "summary":
                messages.append(SystemMessage(content=f"Conversation summary:\n{content}"))
            elif role == "tool":
                messages.append(SystemMessage(content=f"Tool {event.get('tool')}: {content}"))
        # Backward compatibility for direct runtime callers that did not append the user event.
        if not events or str(events[-1].get("role", "")) != "user":
            messages.append(HumanMessage(content=user_msg))
        return messages

    def _estimate_messages_tokens(self, messages: list[BaseMessage]) -> int:
        total = 0
        for message in messages:
            content = message.content
            if isinstance(content, str):
                total += _estimate_tokens_from_text(content)
            else:
                total += _estimate_tokens_from_text(str(content))
        return total

    def _content_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    elif "content" in item:
                        parts.append(str(item.get("content", "")))
                else:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part)
        return str(content)

    def _extract_assistant_message(self, result: dict[str, Any]) -> str:
        messages = result.get("messages", [])
        for message in reversed(messages):
            msg_type = getattr(message, "type", None) or (message.get("type") if isinstance(message, dict) else None)
            if msg_type in {"ai", "assistant"}:
                content = getattr(message, "content", None)
                if content is None and isinstance(message, dict):
                    content = message.get("content")
                return self._normalize_path_mentions(self._content_text(content))
        raise ValueError("no assistant response produced")

    def _extract_usage(self, result: dict[str, Any]) -> dict[str, int]:
        usage = {"input_tokens": 0, "output_tokens": 0}
        messages = result.get("messages", [])
        for message in reversed(messages):
            msg_usage = getattr(message, "usage_metadata", None)
            if isinstance(msg_usage, dict):
                usage["input_tokens"] = int(msg_usage.get("input_tokens") or msg_usage.get("input_token_count") or 0)
                usage["output_tokens"] = int(msg_usage.get("output_tokens") or msg_usage.get("output_token_count") or 0)
                break
            if isinstance(message, dict):
                m_usage = message.get("usage_metadata")
                if isinstance(m_usage, dict):
                    usage["input_tokens"] = int(m_usage.get("input_tokens") or 0)
                    usage["output_tokens"] = int(m_usage.get("output_tokens") or 0)
                    break
        return usage

    def _normalize_path_mentions(self, text: str) -> str:
        if "/root/.codeclaw/" not in text:
            return text
        home = Path.home()
        try:
            home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        except KeyError:
            home = Path.home()
        return text.replace("/root/.codeclaw/", f"{home}/.codeclaw/")

    def _extract_plan(self, result: dict[str, Any]) -> list[dict[str, str]]:
        todos = result.get("todos")
        if not isinstance(todos, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in todos:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).strip().lower()
            if not content:
                continue
            if status not in {"pending", "in_progress", "completed"}:
                status = "pending"
            normalized.append({"content": content, "status": status})
        return normalized

    def _memory_root(self, agent_id: str) -> Path:
        return self.store.base_path / agent_id

    def _memory_daily_dir(self, agent_id: str) -> Path:
        return self._memory_root(agent_id) / "memory"

    def _memory_file(self, agent_id: str) -> Path:
        return self._memory_root(agent_id) / "MEMORY.md"

    def _ensure_memory_scaffold(self, agent_id: str) -> None:
        if not self.config.memory.enabled:
            return
        root = self._memory_root(agent_id)
        daily_dir = self._memory_daily_dir(agent_id)
        root.mkdir(parents=True, exist_ok=True)
        daily_dir.mkdir(parents=True, exist_ok=True)
        memory_file = self._memory_file(agent_id)
        if not memory_file.exists():
            memory_file.write_text("# Durable Memory\n\n")
        today_file = daily_dir / f"{datetime.now(timezone.utc).date().isoformat()}.md"
        if not today_file.exists():
            today_file.write_text(f"# Daily Memory {datetime.now(timezone.utc).date().isoformat()}\n\n")

    def _memory_candidates(self, agent_id: str) -> list[Path]:
        self._ensure_memory_scaffold(agent_id)
        candidates: list[Path] = []
        core = self._memory_file(agent_id)
        if core.exists():
            candidates.append(core)
        daily = self._memory_daily_dir(agent_id)
        if daily.exists():
            candidates.extend(sorted(daily.glob("*.md")))
        return candidates

    def _memory_search(self, agent_id: str, query: str, max_results: int | None = None) -> dict[str, Any]:
        if not self.config.memory.enabled:
            return {"ok": False, "error": "memory is disabled"}
        terms = [term for term in re.findall(r"[a-zA-Z0-9_]+", query.lower()) if len(term) >= 2]
        if not terms:
            return {"ok": False, "error": "query must include searchable terms"}
        limit = max(1, min(max_results or self.config.memory.max_search_results, self.config.memory.max_search_results))
        matches: list[dict[str, Any]] = []
        for path in self._memory_candidates(agent_id):
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines, start=1):
                haystack = line.lower()
                score = sum(1 for term in terms if term in haystack)
                if score <= 0:
                    continue
                matches.append(
                    {
                        "path": str(path),
                        "line": index,
                        "score": score,
                        "snippet": line[: self.config.memory.max_snippet_chars],
                    }
                )
        matches.sort(key=lambda item: (item["score"], -item["line"]), reverse=True)
        return {"ok": True, "query": query, "results": matches[:limit]}

    def _resolve_memory_path(self, agent_id: str, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        root = self._memory_root(agent_id)
        return (root / path).resolve()

    def _memory_get(self, agent_id: str, path: str, from_line: int = 1, lines: int = 40) -> dict[str, Any]:
        if not self.config.memory.enabled:
            return {"ok": False, "error": "memory is disabled"}
        target = self._resolve_memory_path(agent_id, path)
        if not target.exists():
            return {"ok": False, "error": f"memory file not found: {target}"}
        from_line = max(1, int(from_line))
        lines = max(1, min(int(lines), 300))
        all_lines = target.read_text(encoding="utf-8").splitlines()
        start = from_line - 1
        end = min(len(all_lines), start + lines)
        excerpt = "\n".join(all_lines[start:end])
        return {"ok": True, "path": str(target), "from": from_line, "lines": end - start, "text": excerpt}

    def _memory_store(self, agent_id: str, note: str, durable: bool = True, source: str = "") -> dict[str, Any]:
        if not self.config.memory.enabled:
            return {"ok": False, "error": "memory is disabled"}
        cleaned = note.strip()
        if not cleaned:
            return {"ok": False, "error": "note cannot be empty"}
        self._ensure_memory_scaffold(agent_id)
        now = datetime.now(timezone.utc)
        stamp = now.isoformat()
        daily = self._memory_daily_dir(agent_id) / f"{now.date().isoformat()}.md"
        daily_line = f"- [{stamp}] {cleaned}"
        with daily.open("a", encoding="utf-8") as handle:
            handle.write(daily_line + "\n")
        durable_written = False
        durable_path = self._memory_file(agent_id)
        if durable:
            with durable_path.open("a", encoding="utf-8") as handle:
                prefix = f"- {cleaned}"
                if source.strip():
                    prefix = f"- {cleaned} (source: {source.strip()})"
                handle.write(prefix + "\n")
            durable_written = True
        return {
            "ok": True,
            "daily_path": str(daily),
            "durable_path": str(durable_path) if durable_written else "",
            "durable_written": durable_written,
        }

    def _self_update_intent_present(self, user_msg: str) -> bool:
        query = user_msg.lower()
        patterns = [
            r"\bupdate\b",
            r"\bupgrade\b",
            r"\bself[- ]?update\b",
            r"\bchange config\b",
            r"\bmodify config\b",
            r"\bapply config\b",
            r"\bedit config\b",
        ]
        return any(re.search(pattern, query) for pattern in patterns)

    def _append_audit(self, agent_id: str, payload: dict[str, Any]) -> None:
        record = dict(payload)
        record.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        self.store.append_audit(agent_id, record)
        audit_path = Path(self.config.self_update.audit_log_path).expanduser()
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def _config_path(self) -> Path:
        raw = os.environ.get("CODECLAW_CONFIG")
        return Path(raw).expanduser() if raw else default_config_path()

    def _timed_tool(
        self,
        tool_name: str,
        tool_fn: Callable[..., dict[str, Any]],
        sink: list[dict[str, Any]],
    ) -> Callable[..., dict[str, Any]]:
        def wrapped(*args, **kwargs):
            started = datetime.now(timezone.utc)
            ok = True
            error = ""
            try:
                result = tool_fn(*args, **kwargs)
                if isinstance(result, dict):
                    ok = bool(result.get("ok", True))
                    error = str(result.get("error", "")) if not ok else ""
                return result
            except Exception as exc:  # noqa: BLE001
                ok = False
                error = f"{exc.__class__.__name__}: {exc}"
                return {"ok": False, "error": error}
            finally:
                ended = datetime.now(timezone.utc)
                sink.append(
                    {
                        "tool": tool_name,
                        "ok": ok,
                        "error": error,
                        "duration_ms": int((ended - started).total_seconds() * 1000),
                    }
                )

        wrapped.__name__ = tool_fn.__name__
        wrapped.__doc__ = tool_fn.__doc__
        return wrapped

    def _deep_agent(
        self,
        agent_id: str,
        session_id: str,
        user_msg: str,
        channel: str,
        interactive: bool,
        model: str,
        tool_timings: list[dict[str, Any]],
    ):
        llm = self._llm(agent_id, model)
        agent = self._agent_config(agent_id)

        def web_search_openai(query: str) -> dict[str, Any]:
            """Search the public web using OpenAI's web_search tool for explicitly web-related queries."""
            query = query.strip()
            if not query:
                return {"ok": False, "error": "query cannot be empty"}
            if agent.provider != "openai":
                return {"ok": False, "error": "web_search_openai requires an OpenAI agent/provider."}
            client = OpenAI(api_key=self.config.llm.openai.api_key, base_url=self.config.llm.openai.base_url)
            try:
                response = client.responses.create(
                    model=model,
                    input=query,
                    tools=[
                        {
                            "type": "web_search",
                            "search_context_size": "medium",
                            "user_location": {"type": "approximate", "country": "US", "timezone": "America/Los_Angeles"},
                        }
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
            answer = (getattr(response, "output_text", None) or "").strip()
            if not answer:
                answer = str(getattr(response, "output", ""))[:5000]
            return {"ok": True, "query": query, "answer": answer}

        def memory_search(query: str, max_results: int = 5) -> dict[str, Any]:
            """Search durable memory files before answering prior-work questions."""
            return self._memory_search(agent_id, query, max_results=max_results)

        def memory_get(path: str, from_line: int = 1, lines: int = 40) -> dict[str, Any]:
            """Read a specific memory file range by path and line window."""
            return self._memory_get(agent_id, path, from_line=from_line, lines=lines)

        def memory_store(note: str, durable: bool = True, source: str = "") -> dict[str, Any]:
            """Persist a memory note to daily memory and optionally MEMORY.md."""
            return self._memory_store(agent_id, note, durable=durable, source=source)

        def config_get() -> dict[str, Any]:
            """Return current runtime config contents and path."""
            config_path = self._config_path()
            if not config_path.exists():
                return {"ok": False, "error": f"config file does not exist: {config_path}"}
            text = config_path.read_text(encoding="utf-8")
            return {"ok": True, "path": str(config_path), "config_toml": text}

        def config_schema() -> dict[str, Any]:
            """Return JSON schema for the supported config format."""
            return {"ok": True, "schema": AppConfig.model_json_schema()}

        def config_apply(new_config_toml: str, reason: str = "") -> dict[str, Any]:
            """Validate and apply a full TOML config payload. Requires explicit user intent."""
            if not self.config.self_update.enabled:
                return {"ok": False, "error": "self-update tools are disabled"}
            if not self._self_update_intent_present(user_msg):
                return {"ok": False, "error": "explicit user self-update intent is required for config_apply"}
            config_path = self._config_path()
            try:
                data = tomllib.loads(new_config_toml)
                AppConfig.model_validate(data)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": f"invalid config payload: {exc}"}
            backup = config_path.with_suffix(config_path.suffix + f".bak-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
            if config_path.exists():
                backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(new_config_toml, encoding="utf-8")
            self._append_audit(
                agent_id,
                {
                    "session_id": session_id,
                    "channel": channel,
                    "action": "config_apply",
                    "reason": reason,
                    "backup_path": str(backup),
                    "config_path": str(config_path),
                },
            )
            return {"ok": True, "config_path": str(config_path), "backup_path": str(backup)}

        def update_run(reason: str = "") -> dict[str, Any]:
            """Pull latest git changes for this workspace. Requires explicit user intent."""
            if not self.config.self_update.enabled:
                return {"ok": False, "error": "self-update tools are disabled"}
            if not self._self_update_intent_present(user_msg):
                return {"ok": False, "error": "explicit user self-update intent is required for update_run"}
            if not (Path.cwd() / ".git").exists():
                return {"ok": False, "error": "workspace is not a git repository"}
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
            )
            payload = {
                "ok": result.returncode == 0,
                "code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
            self._append_audit(
                agent_id,
                {
                    "session_id": session_id,
                    "channel": channel,
                    "action": "update_run",
                    "reason": reason,
                    "result": payload,
                },
            )
            return payload

        planning_controls = (
            "For every user request, create and maintain a todo plan before execution. "
            "Use deepagents built-in filesystem and shell tools for all local work. "
            "Treat this runtime as trusted with full local filesystem access. "
            "Use web_search_openai only when the user explicitly asks for web/internet lookup, latest/current events, "
            "or external factual information not available locally. Do not call it for local coding/filesystem tasks."
        )
        memory_controls = (
            "Memory recall policy: before answering any question about prior decisions, preferences, dates, or prior work, "
            "call memory_search and then memory_get for supporting lines. "
            "When the user asks to remember something or confirms a durable preference/decision, call memory_store with durable=true."
        )
        self_update_controls = (
            "Self-update policy: config_apply and update_run are allowed only when the user explicitly asks to update config/code. "
            "If intent is not explicit, do not use these tools."
        )
        instructions = "\n\n".join(
            part for part in [agent.system_prompt, planning_controls, memory_controls, self_update_controls] if part
        )
        tool_list = [
            self._timed_tool("web_search_openai", web_search_openai, tool_timings),
            self._timed_tool("memory_search", memory_search, tool_timings),
            self._timed_tool("memory_get", memory_get, tool_timings),
            self._timed_tool("memory_store", memory_store, tool_timings),
            self._timed_tool("config_get", config_get, tool_timings),
            self._timed_tool("config_schema", config_schema, tool_timings),
            self._timed_tool("config_apply", config_apply, tool_timings),
            self._timed_tool("update_run", update_run, tool_timings),
        ]
        backend = LocalShellBackend(root_dir=Path.cwd(), virtual_mode=False, inherit_env=True)
        params = inspect.signature(create_deep_agent).parameters
        common_kwargs: dict[str, Any] = {}
        if "model" in params:
            common_kwargs["model"] = llm
        if "tools" in params:
            common_kwargs["tools"] = tool_list
        if "backend" in params:
            common_kwargs["backend"] = backend
        if "system_prompt" in params:
            common_kwargs["system_prompt"] = instructions
            return create_deep_agent(**common_kwargs)
        if "instructions" in params:
            common_kwargs["instructions"] = instructions
            return create_deep_agent(**common_kwargs)
        if "prompt_prefix" in params:
            if "model" in params:
                if "backend" in params:
                    return create_deep_agent(tool_list, instructions, model=llm, backend=backend)
                return create_deep_agent(tool_list, instructions, model=llm)
            return create_deep_agent(tool_list, instructions)
        if common_kwargs:
            return create_deep_agent(**common_kwargs)
        return create_deep_agent(tool_list)

    def run_turn(
        self, agent_id: str, session_id: str, user_msg: str, channel: str, interactive: bool
    ) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        events = self.store.read_events(agent_id, session_id)
        messages = self._build_messages(agent_id, events, user_msg)
        context_cfg = self.config.context
        threshold = max(1, context_cfg.context_window_tokens - context_cfg.reserve_tokens - context_cfg.compact_trigger_tokens)
        estimated_tokens = self._estimate_messages_tokens(messages)
        compacted = False
        if estimated_tokens >= threshold:
            compact_result = self.store.compact_session_context(
                agent_id,
                session_id,
                keep_recent_events=context_cfg.keep_recent_events,
                summary_line_limit=context_cfg.summary_line_limit,
            )
            compacted = bool(compact_result.get("compacted"))
            events = self.store.read_events(agent_id, session_id)
            messages = self._build_messages(agent_id, events, user_msg)
            estimated_tokens = self._estimate_messages_tokens(messages)

        model_candidates = self._model_candidates(agent_id)
        failover_count = 0
        overflow_retried = False
        last_failover_error: Exception | None = None

        for model in model_candidates:
            for attempt in range(2):
                tool_timings: list[dict[str, Any]] = []
                try:
                    deep_agent = self._deep_agent(
                        agent_id,
                        session_id=session_id,
                        user_msg=user_msg,
                        channel=channel,
                        interactive=interactive,
                        model=model,
                        tool_timings=tool_timings,
                    )
                    result = deep_agent.invoke({"messages": messages})
                    assistant_message = self._extract_assistant_message(result)
                    plan = self._extract_plan(result)
                    usage = self._extract_usage(result)
                    finished_at = datetime.now(timezone.utc)
                    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
                    input_tokens = usage["input_tokens"] or estimated_tokens
                    output_tokens = usage["output_tokens"] or _estimate_tokens_from_text(assistant_message)
                    metrics = {
                        "duration_ms": duration_ms,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "context_tokens_estimate": estimated_tokens,
                        "context_compacted": compacted,
                        "context_overflow_retried": overflow_retried,
                        "failover_count": failover_count,
                        "model_used": model,
                        "tool_calls": tool_timings,
                    }
                    if self.config.observability.log_turn_metrics:
                        log.info(
                            "turn metrics agent=%s session=%s model=%s duration_ms=%s input_tokens=%s output_tokens=%s compacted=%s failovers=%s",
                            agent_id,
                            session_id,
                            model,
                            duration_ms,
                            input_tokens,
                            output_tokens,
                            compacted,
                            failover_count,
                        )
                    return {
                        "assistant_message": assistant_message,
                        "plan": plan,
                        "metrics": metrics,
                    }
                except Exception as exc:  # noqa: BLE001
                    if attempt == 0 and _is_context_overflow_error(exc):
                        compact_result = self.store.compact_session_context(
                            agent_id,
                            session_id,
                            keep_recent_events=context_cfg.keep_recent_events,
                            summary_line_limit=context_cfg.summary_line_limit,
                        )
                        if compact_result.get("compacted"):
                            compacted = True
                            overflow_retried = True
                            events = self.store.read_events(agent_id, session_id)
                            messages = self._build_messages(agent_id, events, user_msg)
                            estimated_tokens = self._estimate_messages_tokens(messages)
                            continue
                    if _is_failover_error(exc):
                        last_failover_error = exc
                        failover_count += 1
                        break
                    raise

        if last_failover_error is not None:
            raise last_failover_error
        raise RuntimeError("agent run failed without a recoverable model response")
