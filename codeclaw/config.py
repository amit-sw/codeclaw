from __future__ import annotations

from pathlib import Path
import tomllib
from pydantic import BaseModel, Field


class GatewayConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 18789
    token: str = ""
    password: str = ""


class AgentConfig(BaseModel):
    id: str
    name: str
    model: str
    fallback_models: list[str] = Field(default_factory=list)
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
    request_timeout_seconds: int = 120
    max_retries: int = 2


class LangChainConfig(BaseModel):
    api_key: str


class LangSmithConfig(BaseModel):
    api_key: str
    project: str


class LangGraphConfig(BaseModel):
    project: str


class TelegramConfig(BaseModel):
    bot_token: str
    poll_interval: int = 1
    typing_interval_seconds: int = 3
    send_max_retries: int = 4
    send_backoff_seconds: float = 1.0
    offset_path: str = str(Path.home() / ".codeclaw" / "telegram_offset.json")
    stream_partial_replies: bool = False
    partial_reply_chunk_chars: int = 240
    partial_reply_delay_seconds: float = 0.08
    max_queue_per_chat: int = 100


class StorageConfig(BaseModel):
    base_path: str = str(Path.home() / ".codeclaw" / "agents")
    retention_days: int = 30
    compact_interval_hours: int = 24


class ToolsConfig(BaseModel):
    approvals_path: str = str(Path.home() / ".codeclaw" / "approvals.json")
    exec_allowlist: list[str] = Field(default_factory=list)


class DoctorConfig(BaseModel):
    strict_mode: bool = True


class ContextConfig(BaseModel):
    context_window_tokens: int = 128_000
    reserve_tokens: int = 20_000
    compact_trigger_tokens: int = 8_000
    keep_recent_events: int = 24
    summary_line_limit: int = 120


class MemoryConfig(BaseModel):
    enabled: bool = True
    max_search_results: int = 8
    max_snippet_chars: int = 320


class SelfUpdateConfig(BaseModel):
    enabled: bool = True
    audit_log_path: str = str(Path.home() / ".codeclaw" / "audit.jsonl")


class ObservabilityConfig(BaseModel):
    log_turn_metrics: bool = True


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
    context: ContextConfig = ContextConfig()
    memory: MemoryConfig = MemoryConfig()
    self_update: SelfUpdateConfig = SelfUpdateConfig()
    observability: ObservabilityConfig = ObservabilityConfig()


def default_config_path() -> Path:
    return Path.home() / ".codeclaw" / "codeclaw.toml"


def load_config(path: str | None = None) -> AppConfig:
    config_path = Path(path).expanduser() if path else default_config_path()
    data = tomllib.loads(config_path.read_text())
    return AppConfig.model_validate(data)
