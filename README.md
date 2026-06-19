# NEXUS-01

A minimal agentic AI framework powered by local LLMs.

See [`../PHASE_MAP.md`](../PHASE_MAP.md) for the development roadmap and current phase status.

## What is NEXUS-01?

NEXUS-01 is a lightweight agentic framework that orchestrates multiple AI agents using:
- **Ollama** for local LLM inference (no API costs)
- **SQLite + ChromaDB** for structured and semantic memory
- **Async message bus** for agent communication
- **Cold Mode** safety checks before critical actions

## NEXUS-01 Agentic OS

Three ways to interact:

| Interface | Command | URL |
|-----------|---------|-----|
| **Web Dashboard** | `python main.py` | http://127.0.0.1:8765 |
| **Terminal (embedded)** | `python main.py` | CLI in same process |
| **Terminal (remote)** | `python nexus_cli.py` | Connects to API |
| **Telegram** | Set `TELEGRAM_TOKEN` | Primary mobile channel |

```bash
pip install -r requirements.txt
ollama pull llama3.2
cp config.example.yaml config.yaml
# Add telegram_token to config.yaml
python main.py
```

Headless server (API + Telegram, no terminal):
```bash
python main.py --no-cli
```

## Web OS Dashboard

Interactive control surface at `/`:

- **Overview** — stats, agent activity chart, LLM provider status
- **Terminal / Chat** — WebSocket chat with session history
- **Projects** — organize work into projects
- **Sessions** — conversation threads across all channels
- **Memory** — knowledge store + semantic vector search
- **Agents** — OSINT, Analyst, Executor, Orchestrator
- **Channels** — Telegram, WhatsApp, Discord, Slack, Signal, Teams

## Quick Start (minimal)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install Ollama and pull a model
# Visit https://ollama.ai for installation
ollama pull llama3.1

# 3. Run the framework
python main.py
```

## Architecture

```
Telegram / WhatsApp / Discord / Slack / CLI
                    │
             ┌──────▼──────┐
             │   Gateway   │  ← HITL approval for exec
             └──────┬──────┘
                    │
             ┌──────▼──────┐
             │ Orchestrator │
             └──────┬──────┘
       ┌────────────┼────────────┐
       │            │            │
  ┌────▼────┐ ┌────▼────┐ ┌────▼────┐
  │  OSINT  │ │ Analyst │ │Executor │
  └────┬────┘ └────┬────┘ └────┬────┘
       └───────────┼───────────┘
                   │
            ┌──────▼──────┐
            │ Message Bus │
            └──────┬──────┘
                   │
     ┌─────────────┼─────────────┐
     │             │             │
┌────▼────┐  ┌─────▼─────┐  ┌────▼────┐
│ Memory  │  │   LLM     │  │  Cold   │
│ SQLite  │  │  Ollama   │  │  Mode   │
└─────────┘  └───────────┘  └─────────┘
```

## Agents

| Agent | Purpose | Capabilities |
|-------|---------|--------------|
| **OSINT** | Intelligence gathering | Web search, URL scraping, breach checking |
| **Executor** | System actions | Command execution, file operations |
| **Analyst** | Data analysis | Pattern detection, anomaly detection |

## CLI Commands

```
nexus> osint cybersecurity trends 2024    # Run OSINT search
nexus> exec ls -la                        # Execute command
nexus> analyst [1,2,3,4,100]             # Analyze data
nexus> help                               # Show commands
nexus> exit                               # Quit
```

## Configuration

Copy `config.example.yaml` to `config.yaml` or use environment variables.

### Core

```yaml
ollama_url: http://localhost:11434
ollama_model: llama3.1
cold_mode_enabled: true
require_approval_for_exec: true
```

### Messaging channels

Enable any combination in `enabled_channels`:

| Channel | Config | Notes |
|---------|--------|-------|
| **Telegram** | `telegram_token` | Create bot via [@BotFather](https://t.me/BotFather). Inline approve/cancel buttons. |
| **WhatsApp** | `whatsapp_token`, `whatsapp_phone_number_id`, `whatsapp_verify_token` | [Meta Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api). Webhook: `GET/POST /webhooks/whatsapp` |
| **Discord** | `discord_token` | Enable Message Content Intent in Discord Developer Portal. Prefix `!` optional. |
| **Slack** | `slack_bot_token`, `slack_signing_secret` | Events API webhook: `POST /webhooks/slack` |

```yaml
enabled_channels:
  - telegram
  - whatsapp
  - discord
  - slack

telegram_token: "your-token"
gateway_host: "0.0.0.0"
gateway_port: 8080
```

**Security:** Set `telegram_allowed_users`, `whatsapp_allowed_numbers`, etc. to restrict who can control agents.

### Telegram quick setup

```bash
export TELEGRAM_TOKEN="your-bot-token"
export ENABLED_CHANNELS=telegram
python main.py
```

### WhatsApp quick setup

1. Create a Meta app with WhatsApp Business API
2. Set webhook URL: `https://your-domain.com/webhooks/whatsapp`
3. Verify token must match `whatsapp_verify_token`
4. Expose port 8080 (or use ngrok for local dev)

```bash
export WHATSAPP_TOKEN="..."
export WHATSAPP_PHONE_NUMBER_ID="..."
export WHATSAPP_VERIFY_TOKEN="nexus-verify"
export ENABLED_CHANNELS=whatsapp
python main.py
```

### Discord quick setup

```bash
export DISCORD_TOKEN="..."
export ENABLED_CHANNELS=discord
python main.py
```

### Slack quick setup

1. Create Slack app → enable Event Subscriptions → `message.channels`
2. Request URL: `https://your-domain.com/webhooks/slack`

```bash
export SLACK_BOT_TOKEN="xoxb-..."
export SLACK_SIGNING_SECRET="..."
export ENABLED_CHANNELS=slack
python main.py
```

## Cold Mode

Cold Mode is a safety mechanism that checks:
1. Data source reliability
2. Parameter ranges (z-score)
3. Confidence threshold (>0.7)
4. Action reversibility
5. Fallback availability

## License

MIT
