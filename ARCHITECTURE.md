# NEXUS-01 — Minimal Viable Agentic Framework

**Version:** 0.1.0
**Date:** 2026-06-18
**Philosophy:** One agent that works beats ten that don't.

---

## What This Is

A local-first agentic framework that runs on your machine with zero infrastructure.
No VPS. No Docker. No paid APIs. Just Python + Ollama.

## What This Is NOT

This is not the full NEXUS-01 vision. This is the seed — the smallest thing that works.
Once this works, you scale by:
- Adding agents (copy `osint.py`, change the prompt)
- Adding tools (add a file in `tools/`)
- Swapping SQLite for Postgres when you outgrow it
- Swapping asyncio.Queue for Redis when you need persistence

## Architecture

```
┌─────────────────────────────────────────────────┐
│              TELEGRAM BOT (Control)              │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│                   MAIN LOOP                      │
│          Routes messages to agents               │
└───┬──────────────┬──────────────┬───────────────┘
    │              │              │
┌───▼───┐    ┌────▼────┐   ┌────▼────┐
│ OSINT │    │EXECUTOR │   │ANALYST  │
│ Agent │    │ Agent   │   │ Agent   │
└───┬───┘    └────┬────┘   └────┬────┘
    │              │              │
    └──────────────┼──────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│              MESSAGE BUS (asyncio.Queue)          │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│              KNOWLEDGE LAYER                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ SQLite   │  │ ChromaDB │  │  Memory  │      │
│  │ (State)  │  │ (Vectors)│  │ (Buffer) │      │
│  └──────────┘  └──────────┘  └──────────┘      │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│              INFERENCE LAYER                      │
│  ┌──────────────────────────────────────────┐   │
│  │  Ollama (local) — Llama 3 / Mistral      │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

## Components

| Component | File | Lines | Purpose |
|-----------|------|-------|---------|
| Message Bus | `core/bus.py` | ~40 | asyncio.Queue inter-agent messaging |
| Memory | `core/memory.py` | ~80 | SQLite + ChromaDB persistence |
| LLM Client | `core/llm.py` | ~60 | Ollama HTTP client |
| Cold Mode | `core/cold_mode.py` | ~70 | Risk gating protocol |
| Agent Base | `agents/base.py` | ~60 | Agent lifecycle + tool binding |
| OSINT Agent | `agents/osint.py` | ~80 | Web scraping intelligence |
| Executor Agent | `agents/executor.py` | ~70 | Command execution |
| Analyst Agent | `agents/analyst.py` | ~70 | Pattern analysis |
| Orchestrator | `agents/orchestrator.py` | ~90 | Intent routing + agent chains |
| Web Scraper | `tools/web_scraper.py` | ~50 | httpx + BeautifulSoup + search |
| Config | `config.py` | ~30 | YAML config loader |
| Main | `main.py` | ~80 | Entry point + CLI |

**Total: ~870 lines of Python.**

## Quick Start

```bash
# 1. Install Ollama (https://ollama.ai)
curl -fsSL https://ollama.ai/install.sh | sh

# 2. Pull a model
ollama pull llama3.2

# 3. Install dependencies
cd nexus01-framework
pip install -r requirements.txt

# 4. Run
python main.py
```

## How It Works

1. You type a command in the terminal (or Telegram)
2. Main routes it to the right agent
3. Agent uses tools to gather data
4. Agent asks Ollama for reasoning
5. Agent stores results in memory
6. Cold Mode gates risky actions
7. Response comes back to you

## Cold Mode Protocol

Before any critical action, the agent runs a 5-step checklist:

1. **Data Verification** — Is source reliable?
2. **Parameter Validation** — Within normal ranges?
3. **Confidence Assessment** — Model confidence ≥ 0.75?
4. **Risk Evaluation** — What happens if wrong?
5. **Fallback Determination** — Is there a safe default?

ALL PASS → Execute. ANY FAIL → Block + explain why.

## Scaling Path

```
v0.1 (now)     → 1 agent, local, SQLite, asyncio.Queue
v0.2 (next)    → 3 agents, Telegram bot, ChromaDB vectors
v0.3 (later)   → Multi-user, Ollama on GPU, Postgres
v1.0 (future)  → VPS, Redis bus, multiple LLM providers
```

---

*The automation system isn't luck. It's designed. Start small. Ship fast. Scale later.*
