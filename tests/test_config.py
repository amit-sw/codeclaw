from codeclaw.config import load_config


def test_load_config(tmp_path):
    cfg = tmp_path / "codeclaw.toml"
    cfg.write_text(
        """
[gateway]
host = "127.0.0.1"
port = 18789
token = "t"
password = "p"

[[agents]]
id = "default"
name = "Default"
model = "gpt-5"
provider = "openai"
system_prompt = ""

[llm.openai]
api_key = "k"
base_url = "https://api.openai.com/v1"

[langchain]
api_key = "k"

[langsmith]
api_key = "k"
project = "proj"

[langgraph]
project = "lg"

[telegram]
bot_token = "bot"
poll_interval = 3

[storage]
base_path = "./sessions"
retention_days = 30
compact_interval_hours = 24

[tools]
approvals_path = "./approvals.json"
exec_allowlist = []
"""
    )
    config = load_config(str(cfg))
    assert config.gateway.token == "t"
    assert config.agents[0].id == "default"
