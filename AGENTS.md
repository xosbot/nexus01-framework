# NEXUS-01 — Agentic AI OS

Local-first agentic framework. One agent that works beats ten that don't.

## Commands

```bash
# Install
pip install -r requirements.txt

# Run
python main.py

# Run headless (API + channels only, no CLI)
python main.py --no-cli

# Run without web dashboard
python main.py --no-web

# Run tests
pytest tests/ -v

# Run single test
pytest tests/test_cold_mode.py -v

# Lint
ruff check .

# Type check
mypy . --ignore-missing-imports
```

## Stack

- Python 3.11+, asyncio-native
- Ollama (local LLM) + cloud fallback (Gemini, Groq, OpenAI, Anthropic)
- SQLite + ChromaDB (vectors) + optional Supabase pgvector
- Redis Streams (durable bus, swappable via `BUS_BACKEND=redis`)
- httpx (async HTTP), PyYAML, rich (CLI)
- Docker (executor sandbox, Phase 3)
- python-telegram-bot (control channel)

## Architecture

```
nexus01-framework/
├── core/           # Bus, memory, LLM router, RAG, agent loop, sandbox
├── agents/         # OSINT, Executor, Analyst, Orchestrator
├── gateway/        # Multi-channel gateway (Telegram, WhatsApp, Discord, etc.)
├── gateway/channels/  # Per-channel adapters
├── tools/          # Web scraper, tool registry
├── api/            # FastAPI/uvicorn web dashboard + WebSocket
├── scripts/        # Ingestion, provisioning, deploy helpers
├── tests/          # pytest suite
├── data/           # SQLite DB, ChromaDB (gitignored)
└── web/            # Static dashboard assets
```

## Code Style

- Type hints on all function signatures
- `from __future__ import annotations` in every file
- f-strings over `.format()` or `%`
- Dataclasses over dicts for structured data
- Async/await everywhere — no blocking calls in hot paths
- Logger per module: `logger = logging.getLogger(__name__)`
- No comments unless explaining *why*, not *what*
- Max function length: ~50 lines. If longer, break it up.
- Imports: stdlib → third-party → local, separated by blank lines

## Testing

- Framework: pytest + pytest-asyncio
- One test file per module: `test_<module>.py`
- Mock external services (LLM, Redis, Docker) — never hit real APIs in tests
- Test cold mode gate logic thoroughly
- Run `pytest tests/ -v` before committing

## Phase 3 Focus (Deploy & Control)

- Docker sandbox for executor agent (isolation, resource limits)
- Telegram HITL: approval gates for destructive operations
- Hetzner CX22 provisioning + hardening
- CI/CD via GitHub Actions
- Structured JSON logging

## Boundaries

**Always do:**
- Run tests before marking work done
- Use cold mode gate for any destructive action
- Keep secrets in env vars, never in code or git
- Log structured JSON in production

**Ask first:**
- Adding new dependencies
- Changing the bus interface
- Modifying cold mode gate logic
- Provisions real infrastructure (VPS, domains)

**Never do:**
- Commit API keys, tokens, or passwords
- Skip cold mode checks for "convenience"
- Use `print()` in production code (use logger)
- Hardcode config values that should be env vars
