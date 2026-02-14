# Troubleshooting

## Config Errors
**Symptom**: `codeclaw doctor` fails or gateway crashes on startup.
- Ensure `~/.codeclaw/codeclaw.toml` exists and matches `docs/codeclaw.example.toml`.
- Check for missing sections: `[gateway]`, `[[agents]]`, `[llm.openai]`, `[langchain]`, `[langsmith]`, `[langgraph]`, `[telegram]`, `[storage]`, `[tools]`.

## Unauthorized Responses
**Symptom**: API responses contain `unauthorized`.
- Verify the `token` and `password` in the config.
- Ensure the UI/CLI uses the same values.

## WebSocket Errors
**Symptom**: CLI send fails with connection errors.
- Confirm the gateway is running on `host:port` from config.
- Check firewall rules and port availability.

## Tool Approval Required
**Symptom**: Assistant replies that a tool needs approval.
- Approve via CLI: `codeclaw tools allow <tool>`
- Approve via Telegram: `/allow <tool>`
- Approve in UI using the sidebar buttons.

## Unexpected File Location
**Symptom**: File writes go to an unexpected location.
- If no path is supplied, files are written under `~/.codeclaw/` using usage-aware defaults.
- If the model sends `/root/.codeclaw/...` on a non-root machine, it is remapped to your home directory.
- Check `~/.codeclaw/FILE_INDEX.json` for the actual resolved file path and usage.

## No Messages in UI
**Symptom**: UI shows no sessions or empty chat.
- Ensure you are using the correct `token`/`password`.
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
