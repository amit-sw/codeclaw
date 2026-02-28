# Administrator Manual

## Scope
This manual is for operators maintaining a local CodeClaw Lite deployment.

## Current Operating Model
- Core agent runtime: LangChain `deepagents`
- Backend mode: full local shell/filesystem backend
- Auth model: no token/password enforcement on gateway endpoints
- Intended environment: trusted local network or localhost only

## Architecture
- Gateway (`FastAPI` + WebSocket): `codeclaw gateway run`
- Agent runtime: `codeclaw/agent.py`
- Session storage: filesystem-backed session store
- Web UI: Streamlit (`streamlit_app.py`)
- Telegram poller (optional): `python -m codeclaw.telegram`

## Key Paths
- Config: `~/.codeclaw/codeclaw.toml`
- Session storage base path: from `[storage].base_path` (default `~/.codeclaw/agents`)
- Project docs: `docs/`

## Install and Validate
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
codeclaw doctor
codeclaw test
```

## Configuration
Use `docs/codeclaw.example.toml` as baseline.

Critical sections:
- `[gateway]`: host/port
- `[[agents]]`: logical agent definitions
- `[llm.openai]`: API key and base URL
- `[llm.local]`: optional local OpenAI-compatible endpoint
- `[storage]`: session retention paths and intervals
- `[telegram]`: bot polling config (if used)

## Operations

### Start Services
```bash
codeclaw gateway run
streamlit run streamlit_app.py
python -m codeclaw.telegram
```

### Health Checks
- HTTP health:
  ```bash
  curl -s http://127.0.0.1:18789/health
  ```
- CLI round trip:
  ```bash
  codeclaw agent send --agent default --message "health check"
  ```

### Session Inspection
```bash
codeclaw sessions list --agent default
codeclaw sessions view --agent default --session <session_id>
```

## Security and Risk Posture
This runtime has high privilege by design:
- local file read/write access
- local shell command execution
- no gateway auth barrier

Minimum operational controls:
1. Bind gateway to localhost (`127.0.0.1`) unless network access is intentional.
2. Restrict host firewall ingress to trusted sources only.
3. Do not run under highly privileged OS users.
4. Keep secrets outside broadly readable locations.
5. Use separate environments for experimentation vs. sensitive workloads.

## Backup and Recovery
- Backup:
  - `~/.codeclaw/codeclaw.toml`
  - `[storage].base_path` directory (session data)
- Restore:
  1. Restore config and storage paths.
  2. Reinstall environment (`pip install -e ".[dev]"`).
  3. Restart gateway/UI.

## Upgrade Procedure
1. Pull/merge code updates.
2. Reinstall package:
   ```bash
   pip install -e ".[dev]"
   ```
3. Run validation:
   ```bash
   codeclaw doctor
   codeclaw test
   ```
4. Restart gateway/UI/poller.

## Troubleshooting Checklist
- Gateway up but UI empty:
  - check gateway logs, then `codeclaw sessions list --agent <id>`
- Model errors:
  - verify model identifier and API key
- File operation confusion:
  - enforce absolute paths in prompts
- Telegram silent:
  - verify bot token and poller process health

## Change Control Suggestions
- Treat `codeclaw/agent.py` and `codeclaw/gateway.py` as high-risk files.
- Run full tests after any change in runtime, gateway protocol, or config models.
- Keep docs in sync when operational behavior changes.

