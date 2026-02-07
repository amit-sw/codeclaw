# Deployment Guide

## Overview
This app runs as three processes:
- Gateway (FastAPI + WebSocket)
- Streamlit UI
- Telegram polling (optional)

## Prerequisites
- Python 3.11+
- A global config at `~/.openclaw/openclaw.toml`

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Configure
Copy the sample config and edit keys:
```bash
mkdir -p ~/.openclaw
cp docs/openclaw.example.toml ~/.openclaw/openclaw.toml
```

## Run Gateway
```bash
openclaw gateway run
```

## Run Streamlit UI
```bash
streamlit run openclaw/ui.py
```

## Run Telegram Poller (optional)
```bash
python -m openclaw.telegram
```

## Validate Config
```bash
openclaw doctor
```

## Run Tests
```bash
openclaw test
```

## Ports
- Gateway: `18789` by default
- Streamlit: `8501` by default

## Upgrade Notes
- If you change the config schema, update `openclaw/config.py`, `docs/openclaw.example.toml`, and `docs/engineering-design.md`.
