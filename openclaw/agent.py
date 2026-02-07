from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from openclaw.config import AppConfig
from openclaw.storage import SessionStore
from openclaw.tools import ToolRegistry, ToolApprovalRequired


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = {}


class ModelResponse(BaseModel):
    message: str
    tool: ToolCall | None = None


class AgentRuntime:
    def __init__(self, config: AppConfig, store: SessionStore, tools: ToolRegistry):
        self.config = config
        self.store = store
        self.tools = tools
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

    def _build_messages(self, agent_id: str, events: list[dict], user_msg: str) -> list:
        agent = self._agent_config(agent_id)
        messages: list = [SystemMessage(content=agent.system_prompt or "")]
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

    def run_turn(self, agent_id: str, session_id: str, user_msg: str, channel: str, interactive: bool) -> str:
        events = self.store.read_events(agent_id, session_id)
        llm = self._llm(agent_id).with_structured_output(ModelResponse)
        messages = self._build_messages(agent_id, events, user_msg)
        response = llm.invoke(messages)
        if response.tool:
            try:
                result = self.tools.execute(response.tool.name, response.tool.args, channel=channel, interactive=interactive)
                tool_event = {
                    "role": "tool",
                    "tool": response.tool.name,
                    "content": result,
                }
                self.store.append_event(agent_id, session_id, tool_event)
                messages.append(SystemMessage(content=f"Tool {response.tool.name}: {result}"))
                response = llm.invoke(messages)
            except ToolApprovalRequired as exc:
                return f"Tool '{exc.tool}' requires approval. Approve via CLI 'openclaw tools allow {exc.tool}', Telegram '/allow {exc.tool}', or Streamlit UI."
        return response.message
