from __future__ import annotations

from pathlib import Path
import tomllib
from pydantic import BaseModel, Field


class GatewayConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 18789
    token: str
    password: str


class AgentConfig(BaseModel):
    id: str
    name: str
    model: str
    provider: str = "openai"
    system_prompt: str = ""


class OpenAIConfig(BaseModel):
    api_key: str
    base_url: str = "https://api.openai.com/v1"


class LocalConfig(BaseModel):
    base_url: str
    api_key: str = ""


class LLMConfig(BaseModel):
    openai: OpenAIConfig
    local: LocalConfig | None = None


class LangChainConfig(BaseModel):
    api_key: str


class LangSmithConfig(BaseModel):
    api_key: str
    project: str


class LangGraphConfig(BaseModel):
    project: str


class TelegramConfig(BaseModel):
    bot_token: str
    poll_interval: int = 3


class StorageConfig(BaseModel):
    base_path: str = str(Path.home() / ".codeclaw" / "agents")
    retention_days: int = 30
    compact_interval_hours: int = 24


class ToolsConfig(BaseModel):
    approvals_path: str = str(Path.home() / ".codeclaw" / "approvals.json")
    exec_allowlist: list[str] = Field(default_factory=list)


class DoctorConfig(BaseModel):
    strict_mode: bool = True


class AppConfig(BaseModel):
    gateway: GatewayConfig
    agents: list[AgentConfig]
    llm: LLMConfig
    langchain: LangChainConfig
    langsmith: LangSmithConfig
    langgraph: LangGraphConfig
    telegram: TelegramConfig
    storage: StorageConfig
    tools: ToolsConfig
    doctor: DoctorConfig = DoctorConfig()


def default_config_path() -> Path:
    return Path.home() / ".codeclaw" / "codeclaw.toml"


def load_config(path: str | None = None) -> AppConfig:
    config_path = Path(path).expanduser() if path else default_config_path()
    data = tomllib.loads(config_path.read_text())
    return AppConfig.model_validate(data)
