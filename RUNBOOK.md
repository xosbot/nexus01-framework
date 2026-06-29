# NEXUS-01 — Operations Runbook

Quick reference for running, debugging, and recovering a NEXUS-01 deployment.
For architecture and design, see `buildplan.md`. For local dev, see `AGENTS.md`.

## Service control (systemd)

The service runs as `nexus01.service` under systemd. Logs go to journald.

```bash
# Status
sudo systemctl status nexus01

# Start / stop / restart
sudo systemctl start nexus01
sudo systemctl stop nexus01
sudo systemctl restart nexus01

# Live logs (last 100 lines, follow)
sudo journalctl -u nexus01 -n 100 -f

# Last 24h of logs as JSON (for grep / log shippers)
sudo journalctl -u nexus01 --since "24 hours ago" -o json

# Boot logs (why it crashed)
sudo journalctl -u nexus01 -b
```

## Health checks

```bash
# Liveness — fast, no external calls
curl -fsS https://navos.space/health

# Richer status (sessions, providers, RAG counts)
curl -fsS https://navos.space/api/system/status

# Authenticated overview (needs $NEXUS_API_KEY)
curl -fsS -H "X-API-Key: $NEXUS_API_KEY" https://navos.space/api/overview
```

A healthy `/health` returns:
```json
{"status": "ok", "service": "nexus-os", "ollama": true, "redis": true, "db": "ok", "uptime": "3h 12m"}
```

If `ollama: false`, the local LLM is unreachable. Check `ollama serve` and
that `OLLAMA_NUM_PARALLEL` is set. If `redis: false`, the in-memory bus
fallback is in use (single-process only) — check `systemctl status redis`.

## Data files

| What | Path | Notes |
|------|------|-------|
| Main SQLite | `/root/nexus01-framework/data/memory.db` | Sessions, projects, knowledge, cost |
| Second Brain | `/root/nexus01-framework/data/memory.db` (same file, separate tables) | Long-term memories, audit log |
| ChromaDB | `/root/nexus01-framework/data/chroma/` | RAG vector store |
| Soul / personality | `/root/nexus01-framework/data/iva/*.md` | Editable from dashboard |
| Cost tracker | Inside `memory.db` (`cost_events` table) | Per-call USD spend |
| Uploads | `/root/nexus01-framework/data/uploads/` | Phase 2 — not yet wired |

## Inspecting the database

```bash
# Recent memories (status, type, confidence, content)
sqlite3 data/memory.db "SELECT id, status, type, confidence, substr(content,1,80) FROM memories ORDER BY created_at DESC LIMIT 20;"

# Last 20 audit events for a specific memory
sqlite3 data/memory.db "SELECT ts, op, actor, note FROM memory_audit WHERE memory_id='mem_abc123' ORDER BY ts DESC LIMIT 20;"

# Cost summary (last 30 days)
sqlite3 data/memory.db "SELECT date(ts,'unixepoch') AS day, provider, model, SUM(cost_usd) FROM cost_events WHERE ts > strftime('%s','now','-30 days') GROUP BY day, provider ORDER BY day DESC;"

# Pending memories (awaiting user approval)
sqlite3 data/memory.db "SELECT id, type, confidence, content FROM memories WHERE status='pending';"
```

## Manual memory operations

```bash
# Approve all pending memories with confidence > 0.8 (one-off, not for prod)
sqlite3 data/memory.db "UPDATE memories SET status='active' WHERE status='pending' AND confidence >= 0.8;"

# Pin a memory (skips decay)
sqlite3 data/memory.db "UPDATE memories SET pinned=1 WHERE id='mem_abc123';"

# Delete a memory and audit the deletion
sqlite3 data/memory.db "DELETE FROM memories WHERE id='mem_abc123';"
sqlite3 data/memory.db "INSERT INTO memory_audit (ts, memory_id, op, actor, note) VALUES (strftime('%s','now'), 'mem_abc123', 'delete', 'ops', 'manual cleanup');"
```

## Audit retention

`memory_audit` is pruned by `SecondBrain.prune_audit()` (default 90 days,
configurable via `AUDIT_RETENTION_DAYS`). It runs opportunistically from
`run_decay()`. Until the dreaming subagent (Phase 3) exists, prune manually:

```bash
# Quick Python one-liner — opens the DB, prunes, exits
python -c "from core.second_brain import SecondBrain; print(SecondBrain('./data/memory.db').prune_audit(days=90), 'rows pruned')"
```

## Database rotation / backup

```bash
# Hot backup (SQLite WAL is safe to copy while service is running)
cp data/memory.db data/memory.db.bak.$(date +%F)
cp data/memory.db-wal data/memory.db-wal.bak.$(date +%F) 2>/dev/null || true
cp data/memory.db-shm data/memory.db-shm.bak.$(date +%F) 2>/dev/null || true

# Or use sqlite3 .backup (atomic, recommended)
sqlite3 data/memory.db ".backup data/memory.db.bak.$(date +%F)"

# Restore: stop the service first
sudo systemctl stop nexus01
mv data/memory.db data/memory.db.bad
cp data/memory.db.bak.2026-06-29 data/memory.db
sudo systemctl start nexus01
```

## When Ollama is down

The system degrades gracefully — chat still streams tool calls and memory
operations, but the LLM itself returns an error. Check:

```bash
# Is Ollama running?
curl -sS --max-time 3 http://127.0.0.1:11434/api/version

# Is the configured model loaded?
ollama list
ollama pull qwen3:8b   # if missing

# Restart if stuck
sudo systemctl restart ollama   # if systemd-managed
# or:
pkill ollama && ollama serve &
```

## When Redis is down

NEXUS-01 falls back to the in-process bus (`NEXUS_BUS_BACKEND=inmemory`).
Multi-channel gateway features (Telegram, Discord, etc.) won't be visible
across processes, but the web chat still works.

```bash
sudo systemctl status redis
sudo systemctl restart redis
```

## Cold mode (safety gate)

Cold mode is a 5-step safety gate that runs before any `EXECUTE`-class
operation (shell exec, social posts, etc.). It is enforced by
`core/cold_mode.py` and the gateway.

```bash
# Disable cold mode (NOT recommended for prod)
NEXUS_COLD_MODE_ENABLED=false  # set in /etc/nexus01/nexus01.env

# View pending approvals (commands blocked by cold mode)
curl -fsS -H "X-API-Key: $NEXUS_API_KEY" https://navos.space/api/approvals

# Approve / deny one
curl -fsS -X POST -H "X-API-Key: $NEXUS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"approval_id":"apr_xyz","approved":true,"session_id":"s1"}' \
  https://navos.space/api/approvals/apr_xyz/respond
```

## API key rotation

```bash
# Generate a new key (you'll only see the raw value once)
curl -fsS -X POST -H "X-API-Key: $NEXUS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"rotated-2026-06","scope":"admin"}' \
  https://navos.space/api/auth/keys

# List existing keys (masked)
curl -fsS -H "X-API-Key: $NEXUS_API_KEY" https://navos.space/api/auth/keys

# Revoke
curl -fsS -X DELETE -H "X-API-Key: $NEXUS_API_KEY" \
  https://navos.space/api/auth/keys/key_abc123
```

## Emergency stop

If the agent is misbehaving and you need to halt it fast:

```bash
# Stop the service (no requests served, state preserved)
sudo systemctl stop nexus01

# If you need to also stop Ollama (no LLM at all)
sudo systemctl stop ollama

# Nuclear: stop everything and flush
sudo systemctl stop nexus01 ollama redis nginx
```

To bring it back: `sudo systemctl start nginx redis ollama nexus01`.

## Logs to grep when something is wrong

| Symptom | Grep for |
|---------|----------|
| LLM not responding | `LLM failed` / `circuit open` / `ollama` |
| Tool call failing | `tool.*failed` / `tool timed out` |
| Memory not extracted | `memory_extractor` / `JSON parse failed` |
| Cold mode blocking legit action | `cold_mode` / `approval` |
| Bus / channel issues | `gateway` / `bus` / channel name (e.g. `telegram`) |
| Auth failures | `401` / `403` in nginx log + `auth` in app log |
| Cost spike | `cost_events` in DB; `cost` in app log |

## Versioning

Current version: see `api/server.py` (`app.version`) and the latest tag on
`xosbot/nexus01-framework` main. Phase 1 + hardening shipped 2026-06-29.
Phase 2 (multi-user + auth) is next per `buildplan.md`.
