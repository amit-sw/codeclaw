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
4. Telegram polling starts automatically inside the gateway process.

## Use the Web UI
The app is split across pages:
1. `Welcome`: runtime health and deployment summary.
2. `Chat`: active conversation UI and session switching.
3. `Configuration`: gateway/Telegram/model runtime settings.
4. `Logs and Processing`: queue/metrics/audit visibility.

In `Chat`:
1. Select an `Agent` in the sidebar.
2. Select `Session`:
   - `New` starts a fresh conversation.
   - Existing session entries reopen previous chats.
3. Type a message in the chat box.
4. If a request fails, use:
   - `Retry send`
   - `Discard message`

## AI Plan Sidebar
- The sidebar includes an `AI Plan` panel.
- It shows current todo steps from the agent with status markers:
  - `[ ]` pending
  - `[~]` in progress
  - `[x]` completed
- During processing, the panel shows `Updating...` and refreshes with the latest plan state after each turn.
- Completed plan steps display elapsed time in seconds, rounded to the nearest second (example: `(12s)`).

## LLM Request Log Sidebar
- The sidebar includes an `LLM Requests` panel for the current session.
- It shows requests in reverse chronological order (most recent first).
- While a request is running, a `[pending]` entry appears at the top.
- Completed requests display elapsed time in seconds, rounded to the nearest second.

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

## Telegram Setup (Optional)
Use these steps exactly to connect Telegram.

1. Download and install Telegram:
   - Mobile: install Telegram from your app store.
   - Desktop: install Telegram Desktop from the official Telegram site.
2. Sign in to Telegram with your phone number.
3. In Telegram search, open `@BotFather`.
4. Send `/newbot` to BotFather.
5. Follow prompts:
   - Set a bot display name.
   - Set a bot username that ends with `bot` (example: `my_codeclaw_bot`).
6. BotFather returns an HTTP API token (often what people call the bot id), for example:
   - `123456789:AA...`
7. Start the gateway:
   ```bash
   codeclaw gateway run
   ```
8. Start the web app in another terminal:
   ```bash
   streamlit run streamlit_app.py
   ```
9. In the `Configuration` page, open the `Telegram Runtime` section and enter:
   - `Bot Token` from BotFather
   - `Poll Interval (seconds)` (for example, `3`)
10. Click `Save Telegram Settings`.
11. Restart the gateway so integrated Telegram polling picks up new settings.
12. Open your bot in Telegram and send `/start`, then send a normal message.

Notes:
- The poller only receives updates for chats that already sent at least one message to the bot.
- Keep your bot token secret.
- Voice messages are transcribed with OpenAI Whisper (`telegram.voice_transcription_model`, default `whisper-1`) and processed like typed messages.

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
- Voice message not processed:
  - Verify `telegram.voice_transcription_enabled = true`.
  - Verify `[llm.openai].api_key` is valid.
  - Check `telegram.voice_max_seconds` and `telegram.voice_max_bytes` limits.

## Safety Note
This system is configured for trusted local environments. It can access local files and run local commands through deepagents. Do not expose it to untrusted users or networks.

## Web Search
The assistant includes a web search capability powered by OpenAI's `web_search` tool.

Behavior:
- It should be used only when you explicitly ask for web/internet lookup.
- It should not be used for normal local coding or filesystem tasks.

Good prompts:
- `Search the web for the latest FastAPI release notes and summarize key changes.`
- `Find current guidance for OpenAI Responses API tool usage and cite sources.`
