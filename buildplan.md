# NEXUS-01 — Build Plan

**Status:** Phase 1 (agentic chat + memory + tools) complete on https://navos.space  
**Audience:** NEXUS-01 maintainers (xosbot + team)  
**Last updated:** 2026-06-29

---

## 0. What we have today

### Shipped (8 commits on `xosbot/nexus01-framework` main)

| Layer | Module | Purpose |
|------|--------|---------|
| Backend | `core/soul.py` | Markdown-driven personality (soul/personality/taste/heartbeat) |
| Backend | `core/events.py` | SQLite event log, queryable, 12+ event kinds |
| Backend | `core/permissions.py` | Per-session Ask/Allow modes |
| Backend | `core/slash.py` | 12 in-chat slash commands (`/help`, `/status`, `/events`, `/mode`, `/soul`, `/theme`, `/memory`, `/providers`, `/budget`, `/agents`, `/model`, `/clear`) |
| Backend | `core/llm_hooks.py` | Soul injection + event emission wrapper |
| Backend | `core/llm_client.py` | Updated to inject soul into system prompt |
| Backend | `core/llm_router.py` | Extended streaming signature (session_id, agent) |
| Backend | `api/server.py` | New endpoints: `/api/soul`, `/api/events`, `/api/permissions`, slash interception in streaming |
| Backend | `core/llm_config.yaml` + `config_manager.py` | NVIDIA NIM providers (3 model variants across cheap/standard/premium) |
| Frontend | `web/os/index.html` (251 lines) | 56px rail + main chat; slide-out drawers; modal |
| Frontend | `web/os/styles.css` (1355 lines) | Dark/light themes, animations, mobile-responsive |
| Frontend | `web/os/app.js` (924 lines) | Chat controller: streaming, slash, voice, attach, theme |
| Frontend | `web/os/admin.js` (532 lines) | 9 admin views (Overview, Memory, Projects, Knowledge, Agents, Approvals, Events, Soul, Settings) |
| Infra | nginx + certbot | https://navos.space → http://127.0.0.1:8765, TLS cert valid until Sep 20 2026 |
| Infra | systemd unit | `nexus01.service` running, JSON logs, auto-restart |

### Existing but not wired into the chat path

- **Orchestrator + agents** (`agents/orchestrator.py`, `osint.py`, `analyst.py`, `executor.py`): full agent stack exists but the dashboard's chat endpoint (`/api/chat/stream`) calls `llm.stream()` directly, bypassing the orchestrator. Tool calls and multi-agent chains don't surface in the chat UI.
- **Tool registry** (`core/tool_registry.py`): a registry exists with OpenAI tool-call schema, but no tools are registered and the chat endpoint doesn't pass them to the LLM.
- **RAG** (`core/rag.py`): ChromaDB-backed, but the chat UI doesn't show which chunks fed which answer.
- **Cost tracker** (`core/cost_tracker.py`): records spend, but no dashboard view.
- **Memory** (`core/memory.py`): projects, sessions, tasks, knowledge, conversations — but no long-term personalization layer.
- **Brain** (`core/brain/`): episodic/semantic/procedural/working memory — but it's a stub, not user-facing.
- **Cold mode** (`core/cold_mode.py`): 5-step safety gate. Already enforced by gateway. Approval UI exists in composer.

### Existing infra (not in this rebuild but used)

- Docker sandbox for executor
- Telegram, WhatsApp, Discord, Slack, Signal, Teams channels (all via gateway)
- Redis bus (already running)
- WebSocket chat (full response, not streamed)

---

## 1. The plan in one paragraph

Build a self-improving agent that lives in the chat. Each chat turn, IVA recalls relevant long-term memories, decides whether to use tools or route through the orchestrator, streams every step to the UI, and writes back what it learned — with confidence scoring, conflict resolution, decay, and a user-visible review queue so the memory can grow without being corrupted. Add per-user auth, cost dashboard, document/RAG ingestion, then a dreaming background process that self-improves the system prompt. Vanilla HTML/CSS/JS frontend throughout, FastAPI backend, SQLite + FTS5 storage.

---

## 2. Architecture: current vs target

### 2.1 Current state (what the chat does today)

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (navos.space)                                          │
│  ┌─────────┐ ┌──────────────────────────────────────────────┐   │
│  │  Rail   │ │ Chat (max 760px)                            │   │
│  │  56px   │ │  • Welcome screen                          │   │
│  │         │ │  • User msg → bubble (right)                │   │
│  │         │ │  • Assistant msg → full-width (left)       │   │
│  └─────────┘ │  • RAG citations as expandable card          │   │
│              │  • Slash command → command-result card      │   │
│              │  • Composer: text + attach + voice         │   │
│              │  • Drawers: Sessions (left) + Admin (right) │   │
│              └──────────────────────────────────────────────┘   │
└──────────────┬──────────────────────────────────────────────────┘
               │ SSE /api/chat/stream
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI server.py                                               │
│   POST /api/chat/stream                                          │
│   ├─ if starts with "/": dispatch to core/slash.dispatch()       │
│   ├─ else: build messages, RAG.inject_top_3_sources              │
│   └─ return StreamingResponse:                                   │
│       event: sources → chunks → done | command → done | error    │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  LLM Router (core/llm_router.py)                                  │
│   • Injects soul (data/iva/*.md) into system prompt              │
│   • Tier-routes: cheap (Ollama/NIM-8B/Groq) → std (NIM-70B)     │
│     → premium (NIM-DeepSeek)                                    │
│   • Streams tokens                                                │
│   • Records cost + usage                                          │
└─────────────────────────────────────────────────────────────────┘

✗ Tool calls, OSINT, analyst, executor, cold-mode gate, memory:
  NOT REACHED from the chat path. Only the WebSocket path.
```

### 2.2 Target after Phase 1 (agentic chat + memory + tools)

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser (navos.space)                                          │
│  ┌─────────┐ ┌──────────────────────────────────────────────┐   │
│  │  Rail   │ │ Chat                                         │   │
│  │  56px   │ │  • User msg                                  │   │
│  │         │ │  • Agent step cards (collapsible):          │   │
│  │         │ │     "🧠 analyst reasoning..."               │   │
│  │         │ │     "🔍 searching the web..."               │   │
│  │         │ │     "⚡ exec ls -la  [approve]"              │   │
│  │         │ │  • Memory recall chip (top of msg):         │   │
│  │         │ │     "Used: 3 memories" → expand              │   │
│  │         │ │  • Final answer (markdown + code highlight)  │   │
│  │         │ │  • Slash → command-result card               │   │
│  │         │ │  • Memory proposal chip:                    │   │
│  │         │ │     "💡 I learned: you work on NEXUS-01"    │   │
│  │         │ │     [✓ accept]  [✗ reject]                   │   │
│  │         │ │  • Composer                                   │   │
│  │         │ │  • Drawers: Sessions + Admin (Memory tab)    │   │
│  └─────────┘ └──────────────────────────────────────────────┘   │
└──────────────┬──────────────────────────────────────────────────┘
               │ SSE
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  POST /api/chat/stream  (orchestrator-aware)                    │
│  1. Slash? → dispatch to slash handler                           │
│  2. Recall memories → top-K facts injected into system prompt     │
│  3. RAG: search documents → top-3 sources injected as context    │
│  4. Inject soul (always)                                        │
│  5. Pass tool list (web_search, exec, rag_query, ...) to LLM     │
│  6. Stream:                                                      │
│     event: memory_recall  → {used: [...]}                        │
│     event: rag_sources     → {sources: [...]}                    │
│     event: agent_step      → {agent, action, input, output}        │
│     event: tool_call       → {id, name, args}                     │
│     event: tool_result     → {id, name, content}                  │
│     event: approval_requested → {approval_id, description}        │
│     event: chunk           → {content: "..."}                    │
│     event: memory_proposed → {memory_id, content, confidence}     │
│     event: done            → {session_id, full_text}              │
└──────────────┬──────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Agent Loop                                                      │
│   ┌──────────────────────────────────────────────────────────┐   │
│   │ Orchestrator  ─routes by intent & complexity              │   │
│   └────┬────────┬──────────┬──────────┬────────────────────┘   │
│        │        │          │          │                          │
│   ┌────▼──┐ ┌───▼───┐ ┌────▼───┐ ┌────▼──────┐                  │
│   │ OSINT │ │Analyst│ │Executor│ │Chat (LLM) │                  │
│   │ web   │ │reason │ │ Docker │ │ direct   │                  │
│   │ search│ │       │ │ sandbox│ │          │                  │
│   └───────┘ └───────┘ └────────┘ └──────────┘                  │
│                                                                  │
│   Tools (core/tool_registry.py):                                │
│   • web_search(query) → results[]                               │
│   • fetch_url(url)    → text                                    │
│   • exec(cmd)         → stdout/stderr  (cold-mode gated)         │
│   • rag_query(q)      → chunks[]                                │
│   • read_file(path)   → contents (within scope)                 │
│   • list_dir(path)    → entries[]                                │
│   • memory_recall(q)  → memories[]                               │
│   • memory_store(t,c) → {memory_id, status}                      │
└─────────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Memory Layer (Phase 1)                                          │
│                                                                  │
│   ┌─────────────── Core blocks (in-context) ───────────────┐    │
│   │  user | persona | project_state | current_focus        │    │
│   │  Editable from dashboard, versioned in audit log      │    │
│   └────────────────────────────────────────────────────────┘    │
│                                                                  │
│   ┌── Long-term memory (SQLite + FTS5) ────────────────────┐    │
│   │  10 types: identity, preference, goal, project,         │    │
│   │  habit, decision, constraint, relationship, episode,    │    │
│   │  reflection                                           │    │
│   │  Fields: type, content, confidence, importance,        │    │
│   │  durability, source_session, source_quote, status,     │    │
│   │  created_at, last_referenced, access_count              │    │
│   │  Auto-inject only if confidence > 0.7                   │    │
│   │  Conflict: new high-conf replaces old; log to audit     │    │
│   │  Decay: low-importance auto-archive after 21d unused    │    │
│   └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│   ┌── Review queue (user-facing) ─────────────────────────┐    │
│   │  Pending memories shown in Memory admin tab             │    │
│   │  [✓ accept] [✗ reject]  one click each                  │    │
│   │  Pending memories NOT auto-injected                    │    │
│   └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│   ┌── Audit log ────────────────────────────────────────────┐   │
│   │  Every add/update/delete/inject logged to events.db    │   │
│   │  Visible in Event log tab with filter by memory kind    │   │
│   └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Long-term target (after all 3 phases)

```
┌─────────────────────────────────────────────────────────────────┐
│  Multi-user (Phase 2)                                           │
│   • Users (id, email, name, role, created_at)                    │
│   • API keys (hashed, scoped: admin | user | readonly)           │
│   • Sessions scoped to user_id (not single global)              │
│   • Memory scoped to user_id (per-user second brain)            │
│   • OAuth (Google, GitHub) optional login                       │
│   • Teams: shared projects, shared RAG, NOT shared memory        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Observability & Self-Improvement (Phase 3)                     │
│   • Prometheus metrics endpoint (/metrics)                       │
│   • Structured JSON logs → Loki (or local file with grep)        │
│   • Dreaming subagent (background, every 60min):                │
│     - Read last N conversations                                  │
│     - Re-extract memories                                        │
│     - Merge duplicates                                           │
│     - Promote/demote importance                                  │
│     - Update core blocks based on stable patterns                │
│   • Self-evolving prompts:                                      │
│     - Meta-agent watches successful chats                        │
│     - Suggests edits to soul.md / personality.md                 │
│     - User approves via Soul tab                                │
│   • Skills marketplace (Mercury pattern)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Data model

### 3.1 Core blocks (in-context)

```sql
CREATE TABLE core_blocks (
    label TEXT PRIMARY KEY,           -- 'user' | 'persona' | 'project_state' | 'current_focus'
    value TEXT NOT NULL,
    updated_at REAL NOT NULL,
    updated_by TEXT DEFAULT 'user',    -- 'user' | 'auto' | 'dreamer'
    version INTEGER NOT NULL DEFAULT 1
);
```

Always loaded into system prompt. Capped at 4 blocks, 2000 chars each. Displayed in the **Memory admin tab** as a "Core" section.

### 3.2 Long-term memories

```sql
CREATE TABLE memories (
    id TEXT PRIMARY KEY,                -- uuid hex
    type TEXT NOT NULL,                  -- identity|preference|goal|project|habit|decision|constraint|relationship|episode|reflection
    content TEXT NOT NULL,
    confidence REAL NOT NULL,            -- 0-1, LLM-assigned at extraction
    importance REAL NOT NULL,           -- 0-1, decays over time
    durability REAL NOT NULL,            -- 0-1, how stable is this fact
    source_session_id TEXT,             -- which conversation extracted it
    source_quote TEXT,                  -- exact quote from conversation
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|active|archived|rejected
    created_at REAL NOT NULL,
    last_referenced REAL,
    access_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_memories_status ON memories(status, confidence DESC);
CREATE INDEX idx_memories_session ON memories(source_session_id);
CREATE INDEX idx_memories_type ON memories(type, status);

-- Full-text search
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, type,
    content='memories', content_rowid='rowid'
);

-- Audit log
CREATE TABLE memory_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    memory_id TEXT,
    op TEXT NOT NULL,                    -- add|update|delete|inject|approve|reject|expire|promote|demote
    old_content TEXT,
    new_content TEXT,
    actor TEXT,                          -- 'extractor' | 'user' | 'dreamer' | 'recall'
    session_id TEXT,
    note TEXT
);
```

### 3.3 Tool calls (Phase 1)

```sql
CREATE TABLE tool_invocations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    args_json TEXT,
    result_text TEXT,
    started_at REAL NOT NULL,
    finished_at REAL,
    status TEXT NOT NULL DEFAULT 'pending'  -- pending|ok|error|timeout|denied
);
```

### 3.4 Users (Phase 2)

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',  -- admin|user|readonly
    password_hash TEXT,                 -- argon2id
    oauth_provider TEXT,                -- 'google' | 'github' | NULL
    oauth_id TEXT,
    created_at REAL NOT NULL,
    last_seen REAL
);

CREATE TABLE api_keys (
    key_hash TEXT PRIMARY KEY,          -- sha256 of the raw key
    user_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'user', -- admin|user|readonly
    name TEXT,
    created_at REAL NOT NULL,
    last_used REAL,
    expires_at REAL
);
```

### 3.5 Sessions (extend existing)

`memory.sessions` table already exists. Add `user_id` and `shared` columns in Phase 2.

---

## 4. Anti-corruption mechanisms (the user's #1 concern)

This is the part that determines whether the memory system is actually trustworthy.

### 4.1 Confidence gating

| Confidence | Behavior |
|-----------|----------|
| < 0.6 | Don't store. Discard after extraction. |
| 0.6 - 0.7 | Store as `pending`. Show in review queue. Don't auto-inject. |
| 0.7 - 0.85 | Store as `active`. Auto-inject when relevant. |
| > 0.85 | Store as `active`. Auto-inject AND boost importance. |

The LLM is told: "Only assign confidence > 0.6 if the user explicitly stated this as a fact about themselves, a project, or a durable preference."

### 4.2 Conflict resolution

When a new memory arrives that semantically matches an existing one (cosine similarity > 0.85 over embeddings, or simple substring match fallback):

1. **Both high confidence (>0.7)**: New memory wins (newer is more accurate). Log the conflict to audit. Old memory's `access_count` and `last_referenced` preserved in audit row.
2. **Old high, new low**: Keep old. Discard new.
3. **Both pending**: Merge into the older one (the one already in the review queue).

### 4.3 Decay & pruning

- `importance * 0.95^(days_since_last_reference)` → effective importance
- If effective importance < 0.1 AND age > 21 days → status = `archived`
- Archived memories are not auto-injected, but are searchable and recoverable from the admin tab
- User can pin a memory to skip decay (add `pinned INTEGER DEFAULT 0` in Phase 2)

### 4.4 User controls

- **Memory admin tab**: search, filter by type/status, view all pending, accept/reject in bulk
- **`/memory list`**: show last 20 memories with confidence + status
- **`/memory show <id>`**: full record + source quote
- **`/memory forget <id>`**: delete with audit
- **`/memory pause`**: stop auto-extraction for this session
- **`/memory audit [n]`**: last N memory operations

### 4.5 Source attribution

Every memory has `source_session_id` and `source_quote`. The audit tab lets you click any memory to see the exact conversation that produced it. This means a user can always ask "why do you think that about me?" and get a verifiable answer.

---

## 5. Phase 1: agentic chat + memory + tools

**Goal:** The chat becomes an actual agent. Long-term memory that doesn't rot.

### 1.1 — `core/second_brain.py` (SQLite + FTS5 + 10 types + core blocks)

**Files:** `core/second_brain.py` (new, ~400 lines), `tests/test_second_brain.py` (new, ~200 lines)

**API surface:**

```python
class SecondBrain:
    def __init__(self, db_path: str = "./data/memory.db"):
        # opens SQLite, creates tables, FTS5 virtual table
        ...

    # Core blocks
    def get_core_blocks(self) -> dict[str, str]: ...
    def set_core_block(self, label: str, value: str, actor: str = "user") -> dict: ...
    def get_core_block(self, label: str) -> str: ...

    # Long-term memories
    def add_memory(self, type: str, content: str, *,
                   confidence: float, importance: float, durability: float,
                   source_session_id: str, source_quote: str) -> dict: ...
    def update_memory(self, memory_id: str, **fields) -> dict: ...
    def delete_memory(self, memory_id: str, actor: str = "user") -> bool: ...
    def approve_memory(self, memory_id: str, actor: str = "user") -> dict: ...
    def reject_memory(self, memory_id: str, actor: str = "user") -> dict: ...
    def pin_memory(self, memory_id: str, pinned: bool) -> dict: ...

    # Queries
    def list_memories(self, *, status: str = "active",
                      type: str | None = None, limit: int = 50) -> list[dict]: ...
    def list_pending(self, limit: int = 50) -> list[dict]: ...
    def search(self, query: str, n: int = 10) -> list[dict]: ...
    def recall_for_context(self, query: str, n: int = 5,
                           min_confidence: float = 0.7) -> list[dict]: ...
    def get(self, memory_id: str) -> dict | None: ...

    # Decay & conflict
    def run_decay(self) -> int:  # returns count archived
    def resolve_conflict(self, new_memory: dict) -> dict:  # returns winning memory
    def record_injection(self, memory_id: str) -> None:  # bump access_count + last_referenced

    # Audit
    def audit_log(self, limit: int = 100, memory_id: str | None = None) -> list[dict]: ...
    def stats(self) -> dict:  # total, by_type, by_status, by_confidence_bucket
```

**Tests:**
- Add memory → appears in list
- Update with conflict → resolves correctly
- Recall by query → returns only active high-confidence
- Decay archives old low-importance
- Audit log captures every op
- FTS5 search finds by keyword

### 1.2 — `core/memory_extractor.py` (LLM-based extraction)

**Files:** `core/memory_extractor.py` (new, ~250 lines)

**Architecture:** Takes a (user_msg, assistant_msg) pair (or a full conversation), calls the LLM with a structured prompt, parses the response, and calls `second_brain.add_memory()` for each fact.

**Prompt strategy:**

```python
EXTRACTION_PROMPT = """You are a memory curator for an AI assistant. Given the
following conversation turn, extract 0-3 facts that would be useful to remember
about the user in future conversations.

For each fact, output a JSON object with:
- type: one of identity|preference|goal|project|habit|decision|constraint|relationship|episode|reflection
- content: a short, self-contained statement of the fact (one sentence)
- confidence: 0.0-1.0 — how sure are you this is a real fact, not a passing remark?
  - 0.6+ only if the user explicitly stated it
  - 0.8+ only if it's clearly important and likely to persist
- importance: 0.0-1.0 — how important is this to remember?
- durability: 0.0-1.0 — how stable is this fact over time? (preferences > passing moods)
- source_quote: the exact sentence from the conversation that justifies this fact

Output an array. Empty array if nothing worth remembering.
Output ONLY valid JSON, no commentary.

Conversation:
USER: {user_msg}
ASSISTANT: {assistant_msg}
"""
```

**Called from:** After each chat turn in the streaming endpoint (fire-and-forget task). Also called from the dreaming subagent in Phase 3.

**Defensive measures:**
- JSON parse failure → log error, return empty (no storage)
- LLM refuses → empty array
- All facts must have confidence in 0-1 range (clamp)
- Source quote must be ≤200 chars

### 1.3 — `core/memory_recall.py` (hybrid keyword + semantic recall)

**Files:** `core/memory_recall.py` (new, ~150 lines)

**Strategy:** Two-stage retrieval.

1. **FTS5 keyword search** for exact phrase matches (always available, fast)
2. **Semantic search via embeddings** if ChromaDB has the memory embedded

**For Phase 1, we start with FTS5 only.** ChromaDB embedding of memories is Phase 2 (when users will have enough memories for embeddings to matter).

**API:**

```python
class MemoryRecall:
    def __init__(self, brain: SecondBrain):
        self.brain = brain

    def recall(self, query: str, n: int = 5, min_confidence: float = 0.7) -> list[dict]:
        # FTS5 search, filter by confidence + status='active'
        # Returns ranked list of memories
        ...

    def format_for_context(self, memories: list[dict], budget_chars: int = 900) -> str:
        # Format as a context block to inject into system prompt
        # Like: "## Relevant memories\n- [preference] User prefers dark mode (conf 0.9)\n..."
        ...

    def format_compact(self, n: int) -> str:
        # One-line summary for slash command: "12 active memories (8 pref, 2 goal, 2 project)"
        ...
```

**Called from:** Start of every chat turn (before sending to LLM), and from `/memory` slash command.

### 1.4 — `core/tool_registry.py` (already exists, extend it)

**No new file.** Extend the existing one to:
- Add a `stream_invoke()` async generator that yields progress events
- Standardize tool result format (success/error/denied)
- Register the chat-relevant tools: `web_search`, `fetch_url`, `exec`, `rag_query`, `memory_recall`, `memory_store`

**Tools to register in Phase 1:**

| Tool | Description | Cold-mode gated? |
|------|-------------|------------------|
| `web_search(query)` | Search the web via DuckDuckGo HTML or Firecrawl | No |
| `fetch_url(url)` | Fetch a URL, return extracted text | No |
| `exec(cmd)` | Run a shell command in Docker sandbox | **Yes** (always) |
| `rag_query(query)` | Search local knowledge base | No |
| `memory_recall(query)` | Explicitly recall memories on a topic | No |
| `memory_store(content)` | Explicitly store a memory (high confidence) | No |

### 1.5 — Wire orchestrator + tools into `/api/chat/stream`

**File:** `api/server.py` (extend existing endpoint)

**New event types in SSE stream:**

```python
{
  "type": "memory_recall",
  "memories": [{...}, ...]              # top-K recalled, with confidence
}
{
  "type": "agent_step",
  "agent": "osint",
  "action": "web_search",
  "input": "...",
  "output": "...",
  "duration_ms": 1234
}
{
  "type": "tool_call",
  "id": "tc_abc123",
  "name": "web_search",
  "args": {"query": "..."}
}
{
  "type": "tool_result",
  "id": "tc_abc123",
  "name": "web_search",
  "content": "...",
  "ok": true,
  "duration_ms": 2345
}
{
  "type": "approval_requested",
  "approval_id": "apr_xyz",
  "description": "Execute: rm -rf /tmp/build",
  "tool": "exec"
}
{
  "type": "memory_proposed",
  "memory_id": "mem_123",
  "type": "preference",
  "content": "User prefers concise answers",
  "confidence": 0.85
}
```

**Routing logic:**

```
incoming message
  ↓
slash? → dispatch → command event → done
  ↓
complex? (orchestrator._is_complex_query)
  ├─ yes → orchestrator.handle() → emit agent_step, tool_call, tool_result
  ↓
  tools available? (if LLM returns tool_calls in stream)
  └─ → invoke tool → emit tool_call, tool_result → loop back to LLM
  ↓
  final answer → emit chunk
  ↓
  memory_extractor.run() (async) → emit memory_proposed for each
  ↓
  done
```

**LLM streaming with tools:** the `NexusLLM.stream()` becomes `stream_with_tools()` that accepts a tool registry. When the LLM returns a `tool_calls` delta, the endpoint invokes the tool, then resumes streaming with the tool result appended. This is how OpenAI function calling works.

**Implementation:** Add a thin wrapper `core/llm_agent.py` that handles the tool-calling loop, calls the LLM, parses tool_calls, invokes tools, feeds results back, repeats until final answer.

### 1.6 — Memory admin tab in dashboard

**File:** `web/os/admin.js` (extend)

**New tab: Memory** (replacing the current "Knowledge" sub-section). Three sub-tabs:

1. **Core** — 4 editable blocks (user, persona, project_state, current_focus). Markdown editor. Save/reload.
2. **Long-term** — searchable list of all memories. Filter by type, status, confidence. Show source quote on hover. Approve/reject pending. Pin. Delete.
3. **Review queue** — pending memories only. Big "Accept" / "Reject" buttons. Bulk accept if confidence > 0.8.

**Style:** Use the same `.kv-row` and `.section-title` patterns. Memory items show type as a colored badge (cyan=preference, green=identity, purple=goal, etc.).

### 1.7 — New slash commands

Extend `core/slash.py`:

| Command | Description |
|---------|-------------|
| `/memory` | Show summary: 12 active, 3 pending, last 5 |
| `/memory list [type]` | List all memories of a type (default: all) |
| `/memory show <id>` | Full record + source quote |
| `/memory forget <id>` | Delete a memory |
| `/memory pause` | Stop auto-extraction for this session |
| `/memory resume` | Re-enable |
| `/remember <text>` | Manually store a high-confidence memory (0.95) |
| `/forget <id>` | Same as /memory forget |
| `/tools` | List available tools |
| `/who` | Show current core blocks (user, persona, etc.) |

### 1.8 — Frontend: tool call cards, agent step cards, memory chips

**File:** `web/os/app.js` (extend)

**New message event types to handle:**

- `memory_recall` → render a small chip at the top of the assistant message: "🧠 3 memories used" → click to expand
- `agent_step` → render as a collapsible card: agent icon, action, input/output preview, duration
- `tool_call` → render an inline card with the tool name, args, pending state (spinner)
- `tool_result` → update the same card with result + duration + ok/error indicator
- `approval_requested` → show the composer approval bar inline (in addition to the existing one)
- `memory_proposed` → render a "💡 I learned..." chip at the bottom of the message with [✓ accept] [✗ reject] buttons

**CSS:** Add to `web/os/styles.css`:
- `.agent-step` — collapsed by default, click to expand
- `.tool-call` — pending (spinner) → done (✓ + duration) → error (red)
- `.memory-chip` — small, accent-colored
- `.approval-inline` — small bar that appears inline in the message

### 1.9 — End-to-end test, commit, push

**Tests:**
- `tests/test_second_brain.py` — unit tests
- `tests/test_memory_extractor.py` — mock LLM, verify schema
- `tests/test_chat_agent.py` — end-to-end: send "what's the latest AI news" → check sources event, chunks, done
- `tests/test_chat_exec.py` — send "exec ls" → check approval event, approve → check exec result

**Commit strategy:** 8 small commits (one per slice), all pushed in one batch:
1. `feat(memory): core/second_brain.py — SQLite + FTS5 + 10 types`
2. `feat(memory): extractor — LLM-based fact extraction`
3. `feat(memory): recall — FTS5 + format for context injection`
4. `feat(tools): chat tools — web_search, fetch_url, exec, rag_query, memory_*`
5. `feat(agent): core/llm_agent.py — tool-calling loop with progress events`
6. `feat(api): orchestrator + tools in /api/chat/stream`
7. `feat(dashboard): Memory admin tab + tool call cards + memory chips`
8. `feat(slash): /memory, /remember, /forget, /tools, /who`

**Headless browser test:** Same script as before, but now sends a message that triggers tool use (e.g. "what's the latest Python release") and verifies the agent step card appears.

---

## 6. Phase 2: multi-user + auth + polish

**Goal:** You and your team can use the same deployment with isolated data, real cost tracking, and document upload.

### 2.1 — User accounts

- `core/users.py` (new): `UserStore` with argon2id password hashing, email lookup, role check
- `api/auth.py` (extend): add `POST /api/auth/login` (returns JWT), `POST /api/auth/register`, `GET /api/auth/me`
- Frontend: replace API key modal with login form; show user name in topbar; logout button

### 2.2 — Scoped API keys

- `POST /api/auth/keys` — generate a new key (returns raw key once, stores hash)
- `GET /api/auth/keys` — list user's keys (masked)
- `DELETE /api/auth/keys/{id}` — revoke
- Backward compatible: existing `X-API-Key` header still works, but maps to a user

### 2.3 — Per-user data isolation

- `memory.sessions.user_id` — new column, populated on create
- `core/second_brain.py` — filter by `user_id` in all queries
- `core/memory.py` — same
- WebSocket: auth on connect, scope messages to user

### 2.4 — OAuth (Google, GitHub)

- `core/oauth.py` (new): OAuth flow handlers
- `GET /api/auth/oauth/{provider}/start` — redirect to provider
- `GET /api/auth/oauth/{provider}/callback` — exchange code, create/link user

### 2.5 — Team-shared projects

- `memory.projects` already has `owner_id` semantics
- Add `team_id` and `members` table for explicit access control
- Sessions can be tagged with project_id (already supported) and shared with team

### 2.6 — Cost dashboard

- New `core/cost_dashboard.py`: aggregate `cost_tracker` data per day, per provider, per agent
- New admin tab: **Costs** with a chart (Chart.js already loaded)
- Per-day bars, per-provider pie, top-agents table
- Budget alerts: `GET /api/costs/budget?month=2026-06` returns spend vs limit

### 2.7 — Document upload → RAG

- New `POST /api/documents/upload` — multipart upload
- File saved to `data/uploads/<user_id>/<doc_id>.<ext>`
- Async task: extract text, chunk, embed, store in ChromaDB with `user_id` filter
- New admin tab: **Documents** showing upload status, chunk count, last reindex
- Drag-drop already works in the composer; just need to route the file to the upload endpoint

---

## 7. Phase 3: dreaming, self-improvement, polish

**Goal:** IVA gets smarter over time, the deployment is production-grade.

### 3.1 — Dreaming subagent (background)

- `core/dreamer.py` (new): runs every 60 min via `asyncio.create_task` started in `main.py`
- Reads last 20 conversations from `memory.list_conversations`
- Calls LLM to:
  - Identify patterns across conversations
  - Merge duplicate memories
  - Promote/demote importance based on observed relevance
  - Update core blocks if stable patterns emerge (only with `actor='dreamer'` so user can see)
- Emits events for every change

### 3.2 — Self-evolving prompts

- `core/prompt_evolver.py` (new): watches `core/events.db` for `slash_command` and `error` events
- If a prompt consistently gets corrections (user rephrases, uses /clear, etc.), meta-agent suggests a soul.md edit
- Suggests appear in the **Soul** admin tab as a diff
- User approves with one click

### 3.3 — Skills marketplace

- `core/skills.py` already exists; extend with:
  - `GET /api/skills/marketplace` — list skills from a JSON registry URL
  - `POST /api/skills/install` — fetch SKILL.md, validate, install
  - Skills are auto-injected as tools if they declare a `tool` schema

### 3.4 — Voice output (TTS)

- `core/tts.py`: pick a TTS provider (Edge TTS free, OpenAI TTS paid, or local pyttsx3)
- Frontend: speaker button next to assistant messages; reads the markdown-rendered text aloud
- New slash command: `/voice` toggles auto-speak

### 3.5 — Production observability

- `GET /metrics` — Prometheus text format (counters: chat_messages, llm_tokens, tool_invocations, errors, etc.)
- Structured JSON logs: rotate daily, keep 7 days
- Health check: `GET /health` returns 200 if bus + LLM + RAG are all reachable

### 3.6 — Hetzner deploy kit

- `deploy/hetzner/terraform/` — full infra (CX22, floating IP, DNS, firewall)
- `deploy/hetzner/ansible.yml` — install Docker, clone repo, configure systemd
- `deploy/hetzner/caddy.conf` — Caddy reverse proxy with auto-TLS (simpler than nginx for new deploys)
- `deploy/hetzner/backup.sh` — nightly pgdump + tar to S3

---

## 8. Out of scope (for now)

- **Native mobile app** — the web dashboard is mobile-responsive enough
- **Multi-region deployment** — single VPS is fine for the team size
- **Self-hosted model serving at scale** — relying on Ollama + NIM cloud
- **Voice cloning** — generic TTS voices are good enough
- **Browser extension** — the web dashboard is the canonical surface
- **Public API for third parties** — team-only auth for now

## 8a. Known gaps (called out 2026-06-29 after Phase 1 audit)

These are limitations in the shipped Phase 1 that we explicitly defer — they
are not bugs, but they are worth knowing about so the system isn't oversold:

- **`memory_recall` is FTS5 keyword-only.** Semantic recall via ChromaDB
  embeddings is deferred to Phase 2 (when there are enough memories per user
  for embeddings to add value). Don't promise "IVA will find semantically
  similar memories" yet — it does literal token match.
- **No headless-browser E2E in CI.** The "End-to-end test passes in headless
  browser" success criterion is satisfied manually against `https://navos.space`
  but is NOT yet a CI check. The `tests/test_browser.py` suite covers the
  Playwright wrapper itself (graceful degradation when Playwright is missing)
  but does not actually drive a real browser against a running server.
- **`memory_recall` is per-process.** There is no shared recall service; each
  NEXUS-01 process has its own SQLite memory file. Multi-process deployments
  would need a shared recall layer (also Phase 2).
- **Audit retention is opportunistic.** `prune_audit()` runs from
  `run_decay()` (which runs from the dreaming subagent in Phase 3). Until
  the dreamer exists, audit rows accumulate indefinitely. Workaround: call
  `SecondBrain.prune_audit()` manually, or schedule it.

---

## 9. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Memory corruption from low-quality facts | Confidence gating + review queue + audit log + per-memory delete |
| Tool loops (LLM calls same tool forever) | Max iterations (default 5), break the loop, emit `error` event |
| Long-running tools block the stream | `asyncio.wait_for` with per-tool timeout; emit `tool_result` with timeout status |
| Cost explosion from premium model | Per-session token budget; auto-fallback to cheaper tier over budget |
| Multi-user data leak | All queries filter by `user_id`; explicit test suite for cross-user access |
| Dreaming subagent producing bad edits | All dreamer writes go to `pending` status; user must approve |
| OAuth state confusion | Single source of truth in `users.oauth_provider` + `users.oauth_id` |
| Search/recall missing semantically similar facts | Embed memories in ChromaDB on store; use embedding similarity + FTS5 hybrid in Phase 2 |

---

## 10. Success criteria

### Phase 1 done when
- [ ] Chat: `web_search`, `fetch_url`, `exec`, `rag_query` all work end-to-end via the chat UI
- [ ] Tool calls show as cards in the message stream
- [ ] Long-term memory extracts facts from real conversations
- [ ] Pending memory shows in the Memory tab with one-click approve
- [ ] Pending memories are NOT auto-injected (anti-corruption verified)
- [ ] `/memory list`, `/memory forget`, `/remember` all work
- [ ] Cold-mode approval flow works for `exec` in the chat
- [ ] End-to-end test passes in headless browser
- [ ] Committed + pushed to `xosbot/nexus01-framework`

**Phase 1 — Hardening (added 2026-06-29):** the 8 Phase 1 slices above ship
the feature. Five follow-up hardening commits land the test infra,
streaming-cancellation coverage, audit retention, source-quote sanitization,
and an enriched `/health` endpoint. See git log for the full commit list.

### Phase 2 done when
- [ ] Two test users can log in and see isolated sessions/memory
- [ ] OAuth login with Google works
- [ ] Document upload → RAG ingestion shows in admin tab
- [ ] Cost dashboard shows per-provider daily spend
- [ ] Team members can see the same projects

### Phase 3 done when
- [ ] Dreaming runs at the 60-min mark, produces audit-logged memory updates
- [ ] Self-evolving prompt suggests edits to soul.md after detecting patterns
- [ ] Skills marketplace can install a community skill end-to-end
- [ ] `/metrics` endpoint shows real Prometheus output
- [ ] Hetzner deploy kit provisions a fresh VPS in <10 min

---

## 11. Timeline

| Phase | Estimated effort | Target completion |
|-------|------------------|-------------------|
| Phase 1 (memory + tool calling) | 4-6 hours of focused work | This session |
| Phase 2 (multi-user + polish) | 6-8 hours | Next session |
| Phase 3 (dreaming + observability) | 8-10 hours | Following session |

This is a plan for an autonomous run. I will commit and push after each phase. If something doesn't ship, we re-plan.

---

**Last updated:** 2026-06-29
**Owner:** NEXUS-01 maintainers
**Status:** Phase 0 + Phase 1 shipped. Phase 2 next.
