# User Manual

## Purpose
CodeClaw Lite is a local chat system that can:
- chat with configured LLM agents
- run local filesystem and shell tasks through deepagents
- keep per-agent chat sessions with history

This build is configured for trusted local use and does not require login credentials.

## Prerequisites
- Python 3.11+
- Config file at `~/.codeclaw/codeclaw.toml`
- A valid model/API setup in config (for example, `[llm.openai]`)

## Start the System
1. Start the gateway:
   ```bash
   codeclaw gateway run
   ```
2. Start the web app (new terminal):
   ```bash
   streamlit run streamlit_app.py
   ```
3. Open Streamlit in your browser (usually `http://localhost:8501`).

## Use the Web UI
1. Select an `Agent` in the sidebar.
2. Select `Session`:
   - `New` starts a fresh conversation.
   - Existing session entries reopen previous chats.
3. Type a message in the chat box.
4. If a request fails, use:
   - `Retry send`
   - `Discard message`

## Use the CLI
- Send a message:
  ```bash
  codeclaw agent send --agent default --message "Summarize docs/deployment.md"
  ```
- List sessions:
  ```bash
  codeclaw sessions list --agent default
  ```
- View a session transcript:
  ```bash
  codeclaw sessions view --agent default --session <session_id>
  ```

## Telegram (Optional)
Run the Telegram poller:
```bash
python -m codeclaw.telegram
```

## Working With Local Files
The assistant can directly access local files in this trusted setup.

Recommended prompt style:
- Use absolute paths for important operations.
- Be explicit about create/overwrite behavior.
- Ask for a preview before destructive changes.

Examples:
- `List files in /Users/you/projects/myapp`
- `Read /Users/you/projects/myapp/README.md`
- `Create /Users/you/projects/myapp/docs/notes.md with a release checklist`

## Session Behavior
- Sessions are stored per agent.
- New sessions are created automatically when needed.
- Session history is available in UI and CLI.

## Quick Troubleshooting
- Gateway not reachable:
  - Confirm `codeclaw gateway run` is running.
- No response from model:
  - Verify model name and API key in `~/.codeclaw/codeclaw.toml`.
- Wrong file path behavior:
  - Retry with an absolute path.

## Safety Note
This system is configured for trusted local environments. It can access local files and run local commands through deepagents. Do not expose it to untrusted users or networks.

