# Troubleshooting

## Config Errors
**Symptom**: `codeclaw doctor` fails or gateway crashes on startup.
- Ensure `~/.codeclaw/codeclaw.toml` exists and matches `docs/codeclaw.example.toml`.
- Check for missing sections: `[gateway]`, `[[agents]]`, `[llm.openai]`, `[langchain]`, `[langsmith]`, `[langgraph]`, `[telegram]`, `[storage]`, `[tools]`.

## Connectivity Errors
**Symptom**: API requests fail before reaching the model.
- Confirm the gateway is running on the configured `host:port`.
- Check firewall rules and local proxy settings.

## WebSocket Errors
**Symptom**: CLI send fails with connection errors.
- Confirm the gateway is running on `host:port` from config.
- Check firewall rules and port availability.

## Filesystem Access
**Symptom**: Assistant says it cannot access local files.
- This runtime uses deepagents with a full-access local shell/filesystem backend.
- Ensure the gateway process was restarted after upgrades.
- Prefer absolute paths when asking for file operations to avoid ambiguity.

## Unexpected File Location
**Symptom**: File writes go to an unexpected location.
- With deepagents full filesystem mode, relative paths resolve from the gateway process working directory.
- Use absolute paths in prompts for deterministic file locations.

## No Messages in UI
**Symptom**: UI shows no sessions or empty chat.
- Confirm that sessions exist via `codeclaw sessions list --agent <id>`.

## Telegram Not Responding
**Symptom**: Bot does not reply.
- Confirm `telegram.bot_token` is correct.
- Ensure the poller is running (`python -m codeclaw.telegram`).
- Check connectivity to `api.telegram.org`.

## Tests Failing
**Symptom**: `codeclaw test` fails.
- Recreate the venv and reinstall: `pip install -e .[dev]`
- Ensure Python 3.11+.
