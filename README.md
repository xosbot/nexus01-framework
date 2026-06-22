<p align="center">
  <img src="https://img.shields.io/badge/version-0.3.0-blue?style=for-the-badge" alt="version">
  <img src="https://img.shields.io/badge/python-3.11+-green?style=for-the-badge&logo=python&logoColor=white" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-purple?style=for-the-badge" alt="license">
  <img src="https://img.shields.io/badge/tests-19%20passing-brightgreen?style=for-the-badge&logo=pytest&logoColor=white" alt="tests">
  <img src="https://img.shields.io/badge/phase-3%20deploy-orange?style=for-the-badge" alt="phase">
</p>

<h1 align="center">NEXUS-01</h1>

<p align="center">
  <strong>The Agentic AI Framework</strong><br>
  Build autonomous AI agents that gather intelligence, analyze patterns, and execute tasks.<br>
  Docker sandboxed. Telegram controlled. Cloud LLM fallback. Local-first.
</p>

<p align="center">
  <a href="https://nexus01-framework.vercel.app">Website</a> ·
  <a href="https://nexus01-framework.vercel.app/docs/">Documentation</a> ·
  <a href="https://nexus01-framework.vercel.app/docs/quickstart.html">Quickstart</a> ·
  <a href="https://github.com/xosbot/nexus01-framework">GitHub</a>
</p>

---

## What is NEXUS-01?

NEXUS-01 is a modular, production-grade agentic AI framework built in Python. It orchestrates multiple specialized AI agents that communicate via a message bus, reason through a ReAct loop, and execute tasks in Docker sandboxes — all controlled from your phone via Telegram.

**Key features:**

- 🐳 **Docker Sandbox** — Executor agent runs in isolated containers with CPU/memory limits, network disabled, read-only root
- 📱 **Telegram HITL** — Inline keyboard approval for destructive operations. Approve from your phone.
- 🔍 **Firecrawl OSINT** — Structured intelligence reports with Firecrawl scraping and DuckDuckGo fallback
- ⚡ **Cloud LLM Router** — Ollama → Gemini → Groq → Claude fallback chain with tiered routing and circuit breaker
- 🛡️ **Cold Mode** — 5-step risk gate that blocks dangerous actions before they execute
- 🧠 **ReAct Agent Loop** — Reason + Act with parallel tool execution and RAG context injection
- 📊 **Structured Logging** — JSON + human-readable log formatters for production observability

## Architecture

```
                    ┌─────────────────────────────────┐
                    │       TELEGRAM BOT (HITL)        │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │           GATEWAY                │
                    │   Multi-channel + Routing        │
                    └───────────────┬─────────────────┘
                                    │
                    ┌───────────────▼─────────────────┐
                    │         MESSAGE BUS              │
                    │   asyncio.Queue / Redis Streams  │
                    └───┬───────────┬───────────┬─────┘
                        │           │           │
                ┌───────▼──┐  ┌─────▼────┐  ┌──▼───────┐
                │   OSINT   │  │ EXECUTOR │  │ ANALYST  │
                │   Agent   │  │  Agent   │  │  Agent   │
                └───────┬──┘  └─────┬────┘  └──┬───────┘
                        │           │           │
                ┌───────▼───────────▼───────────▼───────┐
                │           ORCHESTRATOR                 │
                │       ReAct Loop + Tool Delegation     │
                └───┬───────────┬───────────┬───────────┘
                    │           │           │
            ┌───────▼──┐  ┌────▼─────┐  ┌──▼──────────┐
            │COLD MODE │  │LLM ROUTER│  │ RAG + MEMORY │
            │  Gate    │  │Multi-LLM │  │ ChromaDB     │
            └──────────┘  └──────────┘  └──────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) installed and running
- Docker (optional, for sandboxed executor)

### Installation

```bash
# Clone
git clone https://github.com/xosbot/nexus01-framework.git
cd nexus01-framework

# Install dependencies
pip install -r requirements.txt

# Pull a model
ollama pull llama3.1

# Run
python main.py
```

That's it. You should see the NEXUS-01 prompt. Type `help` to see available commands.

### Headless mode (API + Telegram, no terminal)

```bash
python main.py --no-cli
```

### With Telegram

```bash
export TELEGRAM_TOKEN="your-bot-token-from-botfather"
python main.py --no-cli
```

Then message your bot on Telegram. Send `/start` to begin.

## Agents

| Agent | File | Purpose | Capabilities |
|-------|------|---------|-------------|
| **OSINT** | `agents/osint.py` | Intelligence gathering | Web search, Firecrawl scraping, structured reports |
| **Executor** | `agents/executor.py` | Command execution | Docker sandbox, file ops, Cold Mode gated |
| **Analyst** | `agents/analyst.py` | Pattern analysis | Data analysis, anomaly detection, RAG-grounded |
| **Orchestrator** | `agents/orchestrator.py` | Reasoning + routing | ReAct loop, intent classification, multi-agent chains |

### Usage

```bash
# From CLI
nexus> osint AI agent frameworks 2026
nexus> exec ls -la /tmp
nexus> analyst analyze this data for anomalies
nexus> research cybersecurity trends and assess risk

# From Telegram
osint research competitor X and summarize risks
exec python3 deploy.py
```

## Interfaces

| Interface | Command | URL |
|-----------|---------|-----|
| **Web Dashboard** | `python main.py` | http://127.0.0.1:8765 |
| **Terminal (embedded)** | `python main.py` | CLI in same process |
| **Terminal (remote)** | `python nexus_cli.py` | Connects to API |
| **Telegram** | Set `TELEGRAM_TOKEN` | Primary mobile control |

## Web OS Dashboard

Interactive control surface at `/`:

- **Overview** — Stats, agent activity, LLM provider status
- **Terminal / Chat** — WebSocket chat with session history
- **Projects** — Organize work into projects
- **Sessions** — Conversation threads across all channels
- **Memory** — Knowledge store + semantic vector search
- **RAG** — ChromaDB document search
- **Costs** — Per-request LLM cost tracking

## Configuration

### Option 1: config.yaml

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your settings
```

### Option 2: Environment Variables

```bash
# Core
export OLLAMA_URL="http://localhost:11434"
export OLLAMA_MODEL="llama3.1"
export COLD_MODE_ENABLED="true"
export REQUIRE_APPROVAL_FOR_EXEC="true"

# API + Web
export API_HOST="0.0.0.0"
export API_PORT="8765"
export ENABLE_WEB_UI="true"
export ENABLE_CLI="true"

# Telegram
export TELEGRAM_TOKEN="your-bot-token"
export TELEGRAM_ALLOWED_USERS="your-telegram-id"

# Cloud LLM (optional — fallback when Ollama fails)
export GEMINI_API_KEY=""
export GROQ_API_KEY=""
export OPENAI_API_KEY=""
export ANTHROPIC_API_KEY=""

# Phase 3 — Deploy
export EXECUTOR_SANDBOX_ENABLED="true"
export STRUCTURED_LOG_JSON="false"
export BUS_BACKEND="local"        # "local" or "redis"
export REDIS_URL="redis://localhost:6379"

# Firecrawl (optional — falls back to httpx)
export FIRECRAWL_API_KEY=""
```

### Full config.yaml reference

```yaml
ollama_url: "http://localhost:11434"
ollama_model: "llama3.1"
cold_mode_enabled: true
require_approval_for_exec: true

# API + Web OS
enable_web_ui: true
enable_cli: true
api_host: "0.0.0.0"
api_port: 8765

# Channels
enabled_channels:
  - telegram

# Telegram
telegram_token: ""
telegram_allowed_users: []

# Cloud LLM
# GEMINI_API_KEY, GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY

# Phase 2 — Cloud Brain
bus_backend: local          # local | redis
redis_url: "redis://localhost:6379"
use_react_loop: true
rag_enabled: true
auto_ingest_docs: true
docs_path: ".."
# supabase_url: ""
# supabase_key: ""

# Phase 3 — Deploy
executor_sandbox_enabled: true
structured_log_json: false
```

## Channels

| Channel | Setup | Notes |
|---------|-------|-------|
| **Telegram** | Create bot via [@BotFather](https://t.me/BotFather), set `TELEGRAM_TOKEN` | Inline approve/cancel buttons for exec |
| **WhatsApp** | Meta Cloud API, set webhook `/webhooks/whatsapp` | Needs `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` |
| **Discord** | Enable Message Content Intent, set `DISCORD_TOKEN` | Prefix-free, natural language routing |
| **Slack** | Event Subscriptions webhook `/webhooks/slack` | Needs `SLACK_BOT_TOKEN` + `SLACK_SIGNING_SECRET` |
| **Signal** | signal-cli HTTP daemon | Set `SIGNAL_API_URL` + `SIGNAL_ACCOUNT` |
| **Teams** | Azure AD app registration | Needs `TEAMS_APP_ID` + `TEAMS_APP_PASSWORD` |

## Docker Sandbox

The Executor agent runs commands inside isolated Docker containers:

- **Image:** `python:3.12-slim`
- **CPU:** 0.5 cores (configurable)
- **Memory:** 256MB (configurable)
- **Network:** Disabled
- **Filesystem:** Read-only root + writable `/tmp`
- **Timeout:** 30 seconds hard limit
- **Cleanup:** Auto-removed after execution

```python
from core.sandbox import DockerSandbox, SandboxConfig

config = SandboxConfig(cpu_limit=0.5, memory_limit="256m", timeout_seconds=30)
sandbox = DockerSandbox(config)
result = await sandbox.execute("print('hello')", language="python")
```

## Cold Mode

Cold Mode is a 5-step safety gate that runs before every critical action:

1. **Data Verification** — Is the source reliable?
2. **Parameter Validation** — Are values within normal ranges?
3. **Confidence Assessment** — Is model confidence ≥ 0.75?
4. **Risk Evaluation** — What happens if this is wrong?
5. **Fallback Determination** — Is there a safe default?

ALL PASS → Execute. ANY FAIL → Block + explain why.

## Telegram HITL

When an agent tries to run a destructive command:

1. Bot sends inline keyboard: ✅ Approve / ❌ Cancel
2. User taps a button from their phone
3. Bot executes (or cancels) and responds with the result
4. Full audit trail of all approval decisions
5. 5-minute timeout — auto-deny on expiry

## LLM Router

Multi-provider LLM with tiered routing:

| Tier | Providers | Use Case |
|------|-----------|----------|
| **cheap** | Ollama, Groq | Simple queries, classification |
| **standard** | Gemini, OpenAI | General reasoning, analysis |
| **premium** | Claude, GPT-4 | Complex reasoning, code gen |

Features:
- Circuit breaker (3 failures → skip provider)
- Streaming support
- Per-request cost tracking
- Automatic fallback chain

## RAG Pipeline

Document ingestion and semantic search:

```python
from core.rag import RAGStore

rag = RAGStore(chroma_path="./data/chromadb")

# Ingest
rag.ingest_file(Path("playbook.md"))
rag.ingest_directory(Path("./docs"), "**/*.md")

# Search
results = rag.search("cold mode protocol", n=5)

# Format for LLM
context = rag.format_context("cold mode protocol", n=3)
```

## Project Structure

```
nexus01-framework/
├── agents/                 # Agent implementations
│   ├── base.py             # Base agent class
│   ├── osint.py            # OSINT intelligence agent
│   ├── executor.py         # Docker-sandboxed executor
│   ├── analyst.py          # Pattern analysis agent
│   └── orchestrator.py     # ReAct reasoning loop
├── core/                   # Core framework
│   ├── bus.py              # Message bus (asyncio.Queue)
│   ├── bus_factory.py      # Bus backend selector
│   ├── redis_bus.py        # Redis Streams bus
│   ├── llm_router.py       # Multi-provider LLM router
│   ├── llm_client.py       # Ollama HTTP client
│   ├── cost_tracker.py     # Per-request cost tracking
│   ├── cold_mode.py        # 5-step safety gate
│   ├── memory.py           # SQLite + ChromaDB memory
│   ├── rag.py              # RAG pipeline
│   ├── sandbox.py          # Docker sandbox executor
│   ├── agent_loop.py       # ReAct agent loop
│   ├── tool_registry.py    # Tool registration system
│   ├── structured_logging.py # JSON + human log formatters
│   ├── stores.py           # Store abstractions
│   └── app.py              # App factory + service wiring
├── gateway/                # Multi-channel gateway
│   ├── gateway.py          # Message routing + HITL
│   ├── approvals.py        # Approval management
│   ├── hitl.py             # Human-in-the-loop manager
│   ├── types.py            # InboundMessage, GatewayResponse
│   ├── webhook_server.py   # Webhook handler
│   └── channels/           # Channel adapters
│       ├── telegram.py     # Telegram (inline keyboard)
│       ├── whatsapp.py     # WhatsApp (Meta Cloud API)
│       ├── discord_channel.py
│       ├── slack.py
│       ├── signal.py
│       └── teams.py
├── tools/                  # Agent tools
│   ├── web_scraper.py      # httpx + BeautifulSoup
│   └── firecrawl_scraper.py # Firecrawl + fallback
├── api/                    # Web dashboard + API
│   └── server.py           # FastAPI + WebSocket
├── scripts/                # Deployment helpers
│   ├── provision_hetzner.py # VPS provisioning
│   ├── deploy.sh           # Deployment script
│   └── ingest_docs.py      # RAG document ingestion
├── tests/                  # Test suite (19 tests)
│   ├── test_api.py
│   ├── test_bus_and_cold_mode.py
│   ├── test_gateway.py
│   └── test_phase2.py
├── docs/                   # Documentation hub
│   ├── index.html
│   ├── quickstart.html
│   ├── api.html
│   └── agents.html
├── web/os/                 # Dashboard static assets
├── css/                    # Stylesheets
├── main.py                 # Entry point
├── config.py               # Config loader
├── nexus_cli.py            # Remote CLI client
├── requirements.txt
├── Dockerfile
├── AGENTS.md               # Project conventions
├── opencode.json           # OpenCode agent config
└── .github/workflows/ci.yml # GitHub Actions CI
```

## Development

### Setup

```bash
pip install -r requirements.txt
```

### Run tests

```bash
# All tests
pytest tests/ -v

# Single test
pytest tests/test_cold_mode.py -v
```

### Lint and type check

```bash
ruff check .
mypy . --ignore-missing-imports
```

### Code conventions

See [`AGENTS.md`](AGENTS.md) for full project conventions. Key rules:

- `from __future__ import annotations` in every file
- Type hints on all function signatures
- `logger = logging.getLogger(__name__)` per module
- No `print()` — use `logger`
- Dataclasses for structured data
- Async/await everywhere
- One logical change per commit

## Deployment

### Local development

```bash
python main.py
```

### Docker

```bash
docker build -t nexus01 .
docker run -p 8765:8765 nexus01
```

### Hetzner VPS

```bash
export HCLOUD_TOKEN="your-token"
python scripts/provision_hetzner.py --name nexus-prod --type cx22
```

This provisions a CX22 (2 vCPU, 4GB RAM), installs Docker, configures UFW + fail2ban, creates a non-root user, and deploys the framework.

### CI/CD

GitHub Actions runs on every push:
1. **Lint** — `ruff check .`
2. **Type check** — `mypy`
3. **Test** — `pytest tests/ -v`
4. **Build** — Docker image build (main branch only)

## Phase Progress

| Phase | Name | Status | Cost |
|-------|------|--------|------|
| 0-1 | Local Seed + Agentic OS | ✅ Complete | $0/mo |
| 2 | Cloud Brain | ✅ Complete | ~$15/mo |
| 3 | Deploy & Control | 🔄 In Progress | ~$42/mo |
| 4 | Freedom Layer | ⏳ Deferred | ~€950/mo |

Phase 3 remaining:
- [ ] Provision Hetzner CX22 VPS
- [ ] Deploy to production
- [ ] End-to-end Telegram flow test
- [ ] Prometheus/Grafana monitoring (optional)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+, asyncio |
| LLM | Ollama + Gemini + Groq + OpenAI + Anthropic |
| Memory | SQLite + ChromaDB + optional Supabase pgvector |
| Message Bus | asyncio.Queue / Redis Streams |
| HTTP | httpx (async) |
| Telegram | python-telegram-bot v21+ |
| Web Dashboard | FastAPI + uvicorn + WebSocket |
| Sandbox | Docker (python:3.12-slim) |
| Scraping | Firecrawl + httpx + BeautifulSoup |
| Search | DuckDuckGo HTML |
| CLI | Rich |
| Config | PyYAML + env vars |
| Tests | pytest + pytest-asyncio |
| CI | GitHub Actions |
| Hosting | Vercel (static site) |

## Roadmap

See the full 12-week roadmap in [`build-plan.html`](https://nexus01-framework.vercel.app/build-plan.html) and the phase map in [`PHASE_MAP.md`](../PHASE_MAP.md).

## License

MIT

---

<p align="center">
  Built with precision. Powered by agents.<br>
  <sub>NEXUS-01 &copy; 2026</sub>
</p>
