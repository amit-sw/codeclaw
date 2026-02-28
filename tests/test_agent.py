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
    pass


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
