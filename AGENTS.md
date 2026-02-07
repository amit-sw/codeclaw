# Repository Guidelines

## Project Structure & Module Organization
Key paths:
- `openclaw/`: core runtime (gateway, agent runtime, tools, storage, CLI, UI, Telegram).
- `tests/`: pytest suite for config, storage, and tools.
- `docs/`: architecture and engineering notes.
  - `docs/deployment.md`: deployment steps.
  - `docs/troubleshooting.md`: troubleshooting guide.
  - `docs/openclaw.example.toml`: sample config.

## Build, Test, and Development Commands
- `openclaw gateway run`: start the FastAPI gateway (reads `~/.openclaw/openclaw.toml`).
- `openclaw agent send --agent <id> --message "<text>"`: send a CLI message over WebSocket.
- `openclaw sessions list --agent <id>`: list sessions for an agent.
- `openclaw sessions view --agent <id> --session <id>`: view transcript events.
- `openclaw doctor`: validate config TOML and required paths.
- `openclaw test`: run the full pytest suite.
- `openclaw tools allow <tool>`: approve a tool permanently.
- `streamlit run openclaw/ui.py`: launch the Streamlit UI.
- `python -m openclaw.telegram`: run Telegram polling.

## Coding Style & Naming Conventions
- Indentation: 4 spaces (Python).
- File naming: `snake_case.py` for modules.
- No formatter or linter is enforced yet; keep functions small and explicit.

## Testing Guidelines
- Framework: `pytest`.
- Run: `pytest -q` (or `openclaw test`).
- Tests live under `tests/` and follow `test_*.py` naming.

## Commit & Pull Request Guidelines
No Git history was found to infer conventions. Until established, use:
- Commit messages: short, imperative, and scoped. Example: `feat: add user signup`
- Pull requests: include a clear description, linked issue (if any), and screenshots for UI changes

## Configuration & Secrets
Do not commit secrets. The gateway reads `~/.openclaw/openclaw.toml` for API keys, auth token/password, and channel settings. Use `openclaw doctor` to validate the file before running.
