"""Structured event log — durable, queryable, replayable.

Every meaningful action in NEXUS-01 emits an event:
  - chat_received       : user message arrived
  - llm_call_started    : LLM streaming began
  - llm_chunk           : a token was emitted (coalesced for storage)
  - llm_call_finished   : LLM completed
  - tool_invoked        : a tool ran
  - tool_finished       : tool returned
  - approval_requested  : destructive action needs OK
  - approval_resolved   : approved or denied
  - agent_routed        : orchestrator picked an agent
  - session_started     : new session
  - session_ended       : session archived
  - error               : unhandled exception

Events are stored in SQLite (data/events.db) and exposed via:
  GET  /api/events?limit=N&since=TS&type=KIND
  GET  /api/events/stats

This is the auditable substrate — every dashboard view, every agent step,
every approval can be reconstructed from this stream.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "events.db"
_lock = threading.Lock()

_KNOWN_KINDS = frozenset({
    "chat_received", "llm_call_started", "llm_call_finished",
    "tool_invoked", "tool_finished", "approval_requested",
    "approval_resolved", "agent_routed", "session_started",
    "session_ended", "error", "system", "slash_command",
})


@dataclass
class Event:
    id: str
    ts: float
    kind: str
    session_id: str
    agent: str
    level: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.ts)) + f".{int((self.ts % 1) * 1000):03d}Z",
            "kind": self.kind,
            "session_id": self.session_id,
            "agent": self.agent,
            "level": self.level,
            "message": self.message,
            "data": self.data,
        }


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(_DB_PATH), timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _ensure_schema(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            ts REAL NOT NULL,
            kind TEXT NOT NULL,
            session_id TEXT,
            agent TEXT,
            level TEXT NOT NULL DEFAULT 'info',
            message TEXT,
            data TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, ts DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, ts DESC)")


def emit(
    kind: str,
    message: str = "",
    *,
    session_id: str = "",
    agent: str = "",
    level: str = "info",
    data: dict | None = None,
) -> str:
    if kind not in _KNOWN_KINDS:
        level = "warn" if level == "info" else level
    eid = uuid.uuid4().hex[:16]
    ts = time.time()
    payload = json.dumps(data or {}, ensure_ascii=False)
    with _lock, _conn() as c:
        _ensure_schema(c)
        c.execute(
            "INSERT INTO events (id, ts, kind, session_id, agent, level, message, data) VALUES (?,?,?,?,?,?,?,?)",
            (eid, ts, kind, session_id, agent, level, message[:500], payload),
        )
    return eid


def query(
    limit: int = 100,
    since: float = 0.0,
    kind: str | None = None,
    session_id: str | None = None,
) -> list[dict]:
    with _lock, _conn() as c:
        _ensure_schema(c)
        sql = "SELECT * FROM events WHERE ts >= ?"
        params: list[Any] = [since]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows = c.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d.get("data") or "{}")
        except json.JSONDecodeError:
            d["data"] = {}
        d["iso"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(d["ts"])) + f".{int((d['ts'] % 1) * 1000):03d}Z"
        out.append(d)
    return out


def stats() -> dict[str, Any]:
    with _lock, _conn() as c:
        _ensure_schema(c)
        total = c.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
        by_kind = c.execute(
            "SELECT kind, COUNT(*) AS n FROM events GROUP BY kind ORDER BY n DESC"
        ).fetchall()
        last_hour = c.execute(
            "SELECT COUNT(*) AS n FROM events WHERE ts >= ?",
            (time.time() - 3600,),
        ).fetchone()["n"]
        last_24h = c.execute(
            "SELECT COUNT(*) AS n FROM events WHERE ts >= ?",
            (time.time() - 86400,),
        ).fetchone()["n"]
    return {
        "total": total,
        "last_hour": last_hour,
        "last_24h": last_24h,
        "by_kind": {r["kind"]: r["n"] for r in by_kind},
    }


def clear() -> int:
    with _lock, _conn() as c:
        _ensure_schema(c)
        n = c.execute("DELETE FROM events").rowcount
    return n
