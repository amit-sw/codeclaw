# Deployment Guide

## Overview
This app runs as three processes:
- Gateway (FastAPI + WebSocket)
- Streamlit UI
- Telegram polling (optional)

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

## File Writing Defaults
- If the agent writes a file without an explicit path, it writes under `~/.codeclaw/`.
- Default filename is selected by usage/content:
  - tasks -> `tasks.md`
  - meetings -> `meetings.md`
  - notes/summaries -> `notes.md`
  - ideas -> `ideas.md`
  - fallback -> `inbox.md`
- The system also maintains `~/.codeclaw/FILE_INDEX.json` with file purpose and last update metadata.

## Run Gateway
```bash
codeclaw gateway run
```

## Run Streamlit UI
```bash
streamlit run streamlit_app.py
```

## Run Telegram Poller (optional)
```bash
python -m codeclaw.telegram
```

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
