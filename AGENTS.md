# Repository Guidelines

## Project Structure & Module Organization
Key paths:
- `codeclaw/`: core runtime (gateway, agent runtime, tools, storage, CLI, UI, Telegram).
- `tests/`: pytest suite for config, storage, and tools.
- `docs/`: architecture and engineering notes.
  - `docs/deployment.md`: deployment steps.
  - `docs/troubleshooting.md`: troubleshooting guide.
  - `docs/codeclaw.example.toml`: sample config.

## Build, Test, and Development Commands
- `codeclaw gateway run`: start the FastAPI gateway (reads `~/.codeclaw/codeclaw.toml`).
- `codeclaw agent send --agent <id> --message "<text>"`: send a CLI message over WebSocket.
- `codeclaw sessions list --agent <id>`: list sessions for an agent.
- `codeclaw sessions view --agent <id> --session <id>`: view transcript events.
- `codeclaw doctor`: validate config TOML and required paths.
- `codeclaw test`: run the full pytest suite.
- `codeclaw tools allow <tool>`: approve a tool permanently.
- `streamlit run streamlit_app.py`: launch the Streamlit UI.
- `python -m codeclaw.telegram`: run Telegram polling.

## Coding Style & Naming Conventions
- Indentation: 4 spaces (Python).
- File naming: `snake_case.py` for modules.
- No formatter or linter is enforced yet; keep functions small and explicit.

## Testing Guidelines
- Framework: `pytest`.
- Run: `pytest -q` (or `codeclaw test`).
- Tests live under `tests/` and follow `test_*.py` naming.

## Commit & Pull Request Guidelines
No Git history was found to infer conventions. Until established, use:
- Commit messages: short, imperative, and scoped. Example: `feat: add user signup`
- Pull requests: include a clear description, linked issue (if any), and screenshots for UI changes

## Configuration & Secrets
Do not commit secrets. The gateway reads `~/.codeclaw/codeclaw.toml` for API keys, auth token/password, and channel settings. Use `codeclaw doctor` to validate the file before running.
