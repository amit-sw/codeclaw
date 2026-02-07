# Engineering Design: Minimal OpenClaw (Pure Python)

## Planning Session Notes
- Goals: pure Python Gateway with Telegram + CLI channels, multi-agent routing, on-disk sessions, Streamlit UI, LangChain/LangSmith, OpenAI + local model via OpenAI-compatible HTTP.
- Constraints: minimal code, minimal exception handling, no skills, no sandbox, global TOML config, simplified WS protocol.
- Success metrics: CLI/Telegram chat works, sessions persisted and viewable in UI, auth enforced, tools functional end-to-end.
- Risks: no sandbox for tools; simplified protocol diverges from OpenClaw ecosystem; minimal error handling reduces resilience.
- Assumptions: session storage uses OpenClaw path layout; Telegram uses polling; Web tool uses HTTP fetch + text extraction.

## Architecture Overview
**Core flow**: Channel -> Gateway -> Session Store -> Agent Runtime -> Tool Registry -> Session Store -> Channel/UI.

**Major components**:
- Gateway API (HTTP + WebSocket)
- Session Store (OpenClaw-compatible JSON + JSONL)
- Agent Runtime (LangChain + LangSmith)
- Tool Registry (exec, file, web)
- Channel Adapters (Telegram, CLI)
- Streamlit UI (chat + sessions)
- Auth Manager (token + password handshake)
- Config Loader (global TOML)
- Configuration Doctor (config validation CLI)
- Test Runner (CLI command to run full test suite)

## Component Definitions

## Gateway API
- **Purpose**: Accept connections, enforce auth, route requests to agents/sessions.
- **Responsibilities**:
  1. Authenticate via token + password handshake.
  2. Implement simplified WS protocol.
  3. Route `session.send` to Agent Runtime and persist events.
- **Inputs**: WS frames, HTTP requests (health/config/status).
- **Outputs**: WS `res`/`event` frames.
- **Interfaces**:
  - `handle_connect(auth: AuthDTO) -> ConnectResult`
  - `handle_send(req: SendDTO) -> SendResult`
  - `handle_session_list(req: SessionListDTO) -> SessionListResult`
- **Dependencies**: Auth Manager, Session Store, Agent Runtime.
- **Test Strategy**:
  - Unit: handshake success/fail, routing paths.
  - Contract: WS frame schema.
  - Observability: required log fields present.
- **Open Questions**: none.

## Session Store
- **Purpose**: Persist and retrieve sessions and transcripts.
- **Responsibilities**:
  1. Maintain `sessions.json` index.
  2. Append to `<sessionId>.jsonl` transcripts.
  3. Provide session list and transcript reads.
- **Inputs**: session events, read requests.
- **Outputs**: session summaries, transcript lines.
- **Interfaces**:
  - `list_sessions(agent_id: str) -> list[SessionSummary]`
  - `load_session(session_id: str) -> Session`
  - `append_event(session_id: str, event: EventDTO) -> None`
- **Dependencies**: filesystem.
- **Test Strategy**:
  - Unit: index update, JSONL append, read integrity.
  - Contract: event DTO schema.
- **Open Questions**: compaction schedule details.

## Agent Runtime
- **Purpose**: Execute LLM calls and tool invocations for a turn.
- **Responsibilities**:
  1. Build LangChain request.
  2. Call OpenAI or local OpenAI-compatible endpoint.
  3. Invoke tools via Tool Registry.
- **Inputs**: session history, user message, agent config.
- **Outputs**: assistant message + tool results.
- **Interfaces**:
  - `run_turn(session: Session, user_msg: str) -> AssistantResult`
- **Dependencies**: LangChain, LangSmith, Tool Registry.
- **Test Strategy**:
  - Unit: tool routing, prompt assembly.
  - Integration: mocked LLM responses.
- **Open Questions**: none.

## Tool Registry
- **Purpose**: Register and execute tools.
- **Responsibilities**:
  1. Provide `exec`, `file`, `web` tools.
  2. Enforce first-use confirmation and persist allow.
- **Inputs**: tool call requests.
- **Outputs**: tool results.
- **Interfaces**:
  - `execute(tool: str, args: dict) -> ToolResult`
- **Dependencies**: OS, HTTP client, persistent approvals store.
- **Test Strategy**:
  - Unit: exec, file read/write, web fetch.
  - Contract: tool response schema.
- **Open Questions**: maximum output size.

## Channel Adapter: Telegram
- **Purpose**: Poll Telegram and bridge messages.
- **Responsibilities**:
  1. Poll updates.
  2. Map chats to sessions and agents.
  3. Send replies.
- **Inputs**: Telegram updates.
- **Outputs**: Gateway send, Telegram response.
- **Interfaces**:
  - `poll_loop() -> None`
- **Dependencies**: Telegram Bot API.
- **Test Strategy**:
  - Integration: mocked Telegram API.

## Channel Adapter: CLI
- **Purpose**: Provide local CLI interface.
- **Responsibilities**:
  1. Send messages to Gateway.
  2. Render responses.
  3. Run config doctor checks.
  4. Run full test suite.
- **Inputs**: CLI args.
- **Outputs**: stdout.
- **Interfaces**:
  - `send(agent_id: str, message: str) -> None`
  - `doctor() -> None`
  - `test() -> None`
- **Dependencies**: Gateway WS client.
- **Test Strategy**:
  - Unit: argument parsing.
  - Integration: local Gateway.

## Streamlit UI
- **Purpose**: Full chat UI with session list and transcripts.
- **Responsibilities**:
  1. Authenticate via token + password.
  2. List sessions and display transcripts.
  3. Send chat messages to agents.
- **Inputs**: user interaction.
- **Outputs**: UI state.
- **Interfaces**:
  - `render_sessions()`
  - `render_chat()`
- **Dependencies**: Gateway API.
- **Test Strategy**:
  - Manual verification.

## Auth Manager
- **Purpose**: Validate token + password on connect.
- **Responsibilities**:
  1. Validate handshake credentials.
- **Inputs**: auth DTO.
- **Outputs**: accept/deny.
- **Interfaces**:
  - `verify(auth: AuthDTO) -> bool`
- **Dependencies**: Config Loader.
- **Test Strategy**:
  - Unit: valid/invalid cases.

## Config Loader
- **Purpose**: Load and validate global TOML config.
- **Responsibilities**:
  1. Parse TOML into config DTOs.
  2. Enforce required keys.
- **Inputs**: file path.
- **Outputs**: Config object.
- **Interfaces**:
  - `load_config(path: str) -> Config`
- **Dependencies**: TOML parser.
- **Test Strategy**:
  - Unit: missing/invalid keys.

## Configuration Doctor
- **Purpose**: Validate config TOML for completeness and consistency.
- **Responsibilities**:
  1. Run schema checks for required sections/keys.
  2. Validate URLs/paths and auth fields.
  3. Report actionable failures and exit non-zero.
- **Inputs**: config path.
- **Outputs**: stdout/stderr report, exit code.
- **Interfaces**:
  - `run(path: str) -> int`
- **Dependencies**: Config Loader.
- **Test Strategy**:
  - Unit: missing keys, invalid URLs, invalid paths.

## Test Runner (CLI)
- **Purpose**: Run the full test suite from CLI.
- **Responsibilities**:
  1. Execute the project test command.
  2. Return test status as exit code.
- **Inputs**: CLI args.
- **Outputs**: stdout/stderr, exit code.
- **Interfaces**:
  - `run() -> int`
- **Dependencies**: test framework/runner.
- **Test Strategy**:
  - Integration: command executes and returns pass/fail.

## Protocol (Simplified)
**Transport**: WebSocket

**Frame shape**:
- `type`: `req` | `res` | `event`
- `id`: request id (for req/res)
- `method`: string
- `params`: object
- `result`: object
- `error`: object

**Required Methods**
1. `connect`
   - Params: `token`, `password`, `client`
   - Result: `ok`, `server_info`
2. `agent.list`
   - Result: list of agents
3. `session.send`
   - Params: `agent_id`, `session_id?`, `message`
   - Result: `session_id`, `assistant_message`
4. `session.list`
   - Params: `agent_id`
   - Result: session summaries
5. `session.events`
   - Params: `session_id`
   - Result: transcript lines (or stream)

**Events**
- `session.update` on new messages.

## Storage (OpenClaw-Compatible)
- Base path: `~/.openclaw/agents/<agentId>/sessions/`
- `sessions.json`: index of sessions
- `<sessionId>.jsonl`: transcript events
- Automated retention/compaction (schedule defined in config)

## Config Schema (TOML, Global)
- Location: `~/.openclaw/openclaw.toml`
- Sections:
  - `[gateway]` host, port, auth token/password
  - `[agents]` definitions (name, model, system prompt)
  - `[llm.openai]` api_key, base_url
  - `[llm.local]` base_url, api_key (if required)
  - `[langchain]` api_key
  - `[langsmith]` api_key, project
  - `[langgraph]` project
  - `[telegram]` bot_token, poll_interval
  - `[storage]` base_path, retention_days, compact_interval
  - `[tools]` approvals_path, exec_allowlist
  - `[doctor]` strict_mode (optional)

## Testing Plan
- Target: >=85% coverage for core modules.
- Unit: Gateway routing/auth, session IO, tool execution, config parsing.
- Integration: Gateway WS handshake, CLI->Gateway->Agent, Telegram polling.
- CLI: config doctor validation and test runner exit codes.
- Fixtures: sample `sessions.json`, transcript JSONL, mock LLM/Telegram payloads.

## Pattern Mapping
- Observability Control Plane: LangSmith instrumentation in Agent Runtime.
- Config-Driven Pipeline Orchestrator: Config Loader + Gateway wiring.

## Approval Plan
1. Confirm protocol + config schema.
2. Implement Gateway + Session Store + Agent Runtime.
3. Add CLI + Telegram + Streamlit UI.
4. End-to-end demo with persisted sessions.
