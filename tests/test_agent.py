from pathlib import Path

from deepagents.backends import LocalShellBackend

from codeclaw.agent import AgentRuntime
from codeclaw.config import (
    AgentConfig,
    AppConfig,
    DoctorConfig,
    GatewayConfig,
    LangChainConfig,
    LangGraphConfig,
    LangSmithConfig,
    LLMConfig,
    OpenAIConfig,
    StorageConfig,
    TelegramConfig,
    ToolsConfig,
)


class _DummyStore:
    def read_events(self, agent_id, session_id):
        return []


def _config() -> AppConfig:
    return AppConfig(
        gateway=GatewayConfig(token="t", password="p"),
        agents=[AgentConfig(id="default", name="Default", model="gpt-5", system_prompt="Be precise.")],
        llm=LLMConfig(openai=OpenAIConfig(api_key="k")),
        langchain=LangChainConfig(api_key="k"),
        langsmith=LangSmithConfig(api_key="k", project="proj"),
        langgraph=LangGraphConfig(project="graph"),
        telegram=TelegramConfig(bot_token="bot"),
        storage=StorageConfig(),
        tools=ToolsConfig(),
        doctor=DoctorConfig(),
    )


def test_deep_agent_uses_filesystem_backend(monkeypatch):
    runtime = AgentRuntime(_config(), _DummyStore())
    monkeypatch.setattr(runtime, "_llm", lambda _: object())
    captured = {}

    def _fake_create_deep_agent(model=None, tools=None, system_prompt=None, backend=None, **kwargs):
        captured.update(
            {
                "model": model,
                "tools": tools,
                "system_prompt": system_prompt,
                "backend": backend,
                **kwargs,
            }
        )
        return object()

    monkeypatch.setattr("codeclaw.agent.create_deep_agent", _fake_create_deep_agent)
    runtime._deep_agent("default", channel="cli", interactive=False)

    assert isinstance(captured["backend"], LocalShellBackend)
    assert captured["backend"].cwd == Path.cwd().resolve()
    assert "Use deepagents built-in filesystem and shell tools for all local work." in captured["system_prompt"]
    tool_names = {getattr(tool, "__name__", "") for tool in captured["tools"]}
    assert "web_search_openai" in tool_names


def test_web_search_tool_calls_openai_web_search(monkeypatch):
    runtime = AgentRuntime(_config(), _DummyStore())
    monkeypatch.setattr(runtime, "_llm", lambda _: object())
    captured_agent = {}
    captured_call = {}
    captured_client = {}

    def _fake_create_deep_agent(model=None, tools=None, system_prompt=None, backend=None, **kwargs):
        captured_agent.update({"tools": tools})
        return object()

    class _DummyResponse:
        output_text = "web answer"

    class _DummyResponses:
        def create(self, **kwargs):
            captured_call.update(kwargs)
            return _DummyResponse()

    class _DummyClient:
        def __init__(self, **kwargs):
            captured_client.update(kwargs)
            self.responses = _DummyResponses()

    monkeypatch.setattr("codeclaw.agent.create_deep_agent", _fake_create_deep_agent)
    monkeypatch.setattr("codeclaw.agent.OpenAI", _DummyClient)
    runtime._deep_agent("default", channel="cli", interactive=False)

    web_tool = next(tool for tool in captured_agent["tools"] if getattr(tool, "__name__", "") == "web_search_openai")
    result = web_tool("latest updates")

    assert result["ok"] is True
    assert result["answer"] == "web answer"
    assert captured_call["input"] == "latest updates"
    assert captured_call["model"] == "gpt-5"
    assert captured_call["tools"][0]["type"] == "web_search"
    assert captured_client["api_key"] == "k"


def test_run_turn_returns_assistant_message_and_plan(monkeypatch):
    runtime = AgentRuntime(_config(), _DummyStore())

    class _DummyDeepAgent:
        def invoke(self, payload):
            return {
                "messages": [{"type": "assistant", "content": "done"}],
                "todos": [{"content": "Step A", "status": "in_progress"}],
            }

    monkeypatch.setattr(runtime, "_deep_agent", lambda agent_id, channel, interactive: _DummyDeepAgent())
    result = runtime.run_turn("default", "s1", "hello", "webui", interactive=False)
    assert result["assistant_message"] == "done"
    assert result["plan"] == [{"content": "Step A", "status": "in_progress"}]
