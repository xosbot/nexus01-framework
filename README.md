# NEXUS-01

A minimal agentic AI framework powered by local LLMs.

## What is NEXUS-01?

NEXUS-01 is a lightweight agentic framework that orchestrates multiple AI agents using:
- **Ollama** for local LLM inference (no API costs)
- **SQLite + ChromaDB** for structured and semantic memory
- **Async message bus** for agent communication
- **Cold Mode** safety checks before critical actions

## Quick Start

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
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   OSINT     │     │  Analyst    │     │  Executor   │
│   Agent     │     │   Agent     │     │   Agent     │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────┴──────┐
                    │ Message Bus │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌────┴────┐ ┌────┴────┐
        │  Memory   │ │   LLM   │ │  Cold   │
        │(SQLite +  │ │(Ollama) │ │  Mode   │
        │ ChromaDB) │ │         │ │         │
        └───────────┘ └─────────┘ └─────────┘
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

Create `config.yaml` or use environment variables:

```yaml
ollama_url: http://localhost:11434
ollama_model: llama3.1
telegram_token: ""  # Optional
database_path: ./data/nexus.db
chroma_path: ./data/chromadb
cold_mode_enabled: true
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
