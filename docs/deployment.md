# Deployment Guide

## Overview
This app runs as two processes:
- Gateway (FastAPI + WebSocket + integrated Telegram polling)
- Streamlit UI

## Prerequisites
- Python 3.11+
- A global config at `~/.codeclaw/codeclaw.toml`

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configure
Copy the sample config and edit keys:
```bash
mkdir -p ~/.codeclaw
cp docs/codeclaw.example.toml ~/.codeclaw/codeclaw.toml
```

## Filesystem Access
- The runtime uses LangChain `deepagents` with a local shell/filesystem backend.
- File operations run directly on your machine with full access in this trusted setup.

## Run Gateway
```bash
codeclaw gateway run
```

## Run Streamlit UI
```bash
streamlit run streamlit_app.py
```

## Telegram Polling
- Telegram polling runs inside the gateway process by default.
- To disable integrated Telegram polling for a gateway run, set:
  - `CODECLAW_DISABLE_GATEWAY_TELEGRAM=1`
- Voice messages are supported via Telegram `voice` updates and OpenAI transcription (`/audio/transcriptions`).
- Ensure `[llm.openai].api_key` is set and `telegram.voice_transcription_enabled = true`.

## Validate Config
```bash
codeclaw doctor
```

## Run Tests
```bash
codeclaw test
```

## Ports
- Gateway: `18789` by default
- Streamlit: `8501` by default

## Upgrade Notes
- If you change the config schema, update `codeclaw/config.py`, `docs/codeclaw.example.toml`, and `docs/engineering-design.md`.
- If you change Telegram runtime behavior, also update `codeclaw/telegram.py` and this deployment guide.
