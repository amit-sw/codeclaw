from __future__ import annotations

import inspect
import os
import pwd
from pathlib import Path
from typing import Any

import httpx
from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from codeclaw.config import AppConfig
from codeclaw.storage import SessionStore


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

    def _llm(self, agent_id: str) -> ChatOpenAI:
        agent = self._agent_config(agent_id)
        if agent.provider == "local" and self.config.llm.local:
            return ChatOpenAI(
                api_key=self.config.llm.local.api_key,
                base_url=self.config.llm.local.base_url,
                model=agent.model,
            )
        return ChatOpenAI(
            api_key=self.config.llm.openai.api_key,
            base_url=self.config.llm.openai.base_url,
            model=agent.model,
        )

    def _build_messages(self, agent_id: str, events: list[dict], user_msg: str) -> list[BaseMessage]:
        agent = self._agent_config(agent_id)
        messages: list[BaseMessage] = [SystemMessage(content=agent.system_prompt or "")]
        for event in events:
            role = event.get("role")
            content = event.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            elif role == "tool":
                messages.append(SystemMessage(content=f"Tool {event.get('tool')}: {content}"))
        messages.append(HumanMessage(content=user_msg))
        return messages

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

    def _normalize_path_mentions(self, text: str) -> str:
        if "/root/.codeclaw/" not in text:
            return text
        home = Path.home()
        try:
            home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        except KeyError:
            home = Path.home()
        return text.replace("/root/.codeclaw/", f"{home}/.codeclaw/")

    def _deep_agent(self, agent_id: str, channel: str, interactive: bool):
        llm = self._llm(agent_id)

        def web_fetch(url: str) -> dict[str, Any]:
            """Fetch a URL over HTTP and return response text and status code."""
            try:
                resp = httpx.get(url, timeout=20)
            except httpx.RequestError as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "status": resp.status_code, "text": resp.text}

        agent = self._agent_config(agent_id)
        planning_controls = (
            "For every user request, create and maintain a todo plan before execution. "
            "Use deepagents built-in filesystem and shell tools for all local work. "
            "Treat this runtime as trusted with full local filesystem access."
        )
        instructions = "\n\n".join(part for part in [agent.system_prompt, planning_controls] if part)
        tool_list = [web_fetch]
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

    def run_turn(self, agent_id: str, session_id: str, user_msg: str, channel: str, interactive: bool) -> str:
        events = self.store.read_events(agent_id, session_id)
        messages = self._build_messages(agent_id, events, user_msg)
        deep_agent = self._deep_agent(agent_id, channel, interactive)
        result = deep_agent.invoke({"messages": messages})
        return self._extract_assistant_message(result)
