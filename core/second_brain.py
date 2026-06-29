"""Second Brain — long-term memory with confidence gating, FTS5 recall, and audit log.

The SecondBrain is the durable, user-facing memory layer. It is intentionally
separate from `core/memory.py` (which holds sessions/conversations/knowledge)
because the data shapes, access patterns, and lifecycle rules are different.

Data model (10 types):
    identity | preference | goal | project | habit
    | decision | constraint | relationship | episode | reflection

Confidence gating (anti-corruption):
    < 0.6   → discarded (not stored)
    0.6-0.7 → status='pending'  (NOT auto-injected; shown in review queue)
    > 0.7   → status='active'    (auto-injected on recall)

Conflict resolution (when a new memory's content is substring-similar to an
existing active one with similarity > 0.85):
    Both high (>0.7)       → new wins; old archived with audit row
    Old high, new low      → keep old; discard new
    Both pending           → keep the older pending; discard new

Decay: importance * 0.95^(days_since_last_reference) < 0.1 AND age > 21d → archived.
Pinned memories are exempt from decay.

Storage: SQLite with WAL + FTS5 virtual table for keyword search.
All operations are audited in `memory_audit`.
"""
from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "memory.db"
# No global lock: SQLite WAL mode + busy_timeout=5000 handles concurrent access.
# Each call to _conn() opens a fresh, thread-safe connection.

VALID_TYPES = frozenset({
    "identity", "preference", "goal", "project", "habit",
    "decision", "constraint", "relationship", "episode", "reflection",
})
VALID_STATUSES = frozenset({"pending", "active", "archived", "rejected"})

CONFIDENCE_DISCARD_MAX = 0.6
CONFIDENCE_PENDING_MAX = 0.7
SOURCE_QUOTE_MAX_CHARS = 200
DECAY_DAYS = 21
DECAY_IMPORTANCE_FLOOR = 0.1
DECAY_RATE = 0.95
CONFLICT_SCAN_CAP = 1000
CONFLICT_SUBSTRING_MIN_LEN = 12
AUDIT_RETENTION_DAYS = 90

CORE_BLOCK_LABELS = ("user", "persona", "project_state", "current_focus")
CORE_BLOCK_MAX_CHARS = 2000


# ── Schema ────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS core_blocks (
    label TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL,
    updated_by TEXT NOT NULL DEFAULT 'user',
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL NOT NULL,
    importance REAL NOT NULL,
    durability REAL NOT NULL,
    source_session_id TEXT,
    source_quote TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    pinned INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    last_referenced REAL,
    user_id TEXT NOT NULL DEFAULT 'user_legacy',
    access_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(source_session_id);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type, status);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, status, created_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content, type,
    content='memories', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, type) VALUES (new.rowid, new.content, new.type);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, type) VALUES('delete', old.rowid, old.content, old.type);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, type) VALUES('delete', old.rowid, old.content, old.type);
    INSERT INTO memories_fts(rowid, content, type) VALUES (new.rowid, new.content, new.type);
END;

CREATE TABLE IF NOT EXISTS memory_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    memory_id TEXT,
    op TEXT NOT NULL,
    old_content TEXT,
    new_content TEXT,
    actor TEXT,
    session_id TEXT,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_memory ON memory_audit(memory_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON memory_audit(ts DESC);
"""


# ── Helpers ───────────────────────────────────────────────────────────────

def _fts_escape(query: str) -> str:
    """Sanitize a query for FTS5 MATCH.

    FTS5 parses raw query text as a search expression (tokenized). Special
    chars like `"`, `(`, `)`, `*`, `:` have meaning. We escape them by
    quoting each word individually, which gives us tokenized AND matching
    without phrase-exact requirements.

    This means "what python version" becomes `"what" "python" "version"`,
    which matches any document containing all three tokens (FTS5 default
    is implicit AND for space-separated quoted terms).
    """
    if not query:
        return '""'
    tokens = query.split()
    if not tokens:
        return '""'
    quoted = []
    for t in tokens:
        # Strip FTS5 special chars from each token; collapse double-quotes
        cleaned = t.replace('"', '').replace("(", "").replace(")", "").replace(":", "").replace("*", "")
        if cleaned:
            quoted.append(f'"{cleaned}"')
    return " ".join(quoted) if quoted else '""'


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _now() -> float:
    return time.time()


def _new_id() -> str:
    return "mem_" + uuid.uuid4().hex[:12]


# ── Class ─────────────────────────────────────────────────────────────────

class SecondBrain:
    """Durable long-term memory store with confidence gating and audit log."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(str(self.db_path), timeout=5.0, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=5000")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(_SCHEMA)
            # Backfill pinned column on existing tables (idempotent)
            cols = {r[1] for r in c.execute("PRAGMA table_info(memories)").fetchall()}
            if "pinned" not in cols:
                c.execute("ALTER TABLE memories ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            # Phase 2.3: user_id column on memories (idempotent)
            if "user_id" not in cols:
                c.execute(
                    "ALTER TABLE memories ADD COLUMN user_id TEXT NOT NULL DEFAULT 'user_legacy'"
                )
                c.execute("CREATE INDEX IF NOT EXISTS idx_memories_user "
                          "ON memories(user_id, status, created_at DESC)")

    # ── Core blocks ─────────────────────────────────────────────────────

    def get_core_blocks(self) -> dict[str, str]:
        with self._conn() as c:
            rows = c.execute("SELECT label, value FROM core_blocks").fetchall()
        return {r["label"]: r["value"] for r in rows}

    def get_core_block(self, label: str) -> str:
        if label not in CORE_BLOCK_LABELS:
            raise ValueError(f"invalid core block label: {label}")
        with self._conn() as c:
            row = c.execute("SELECT value FROM core_blocks WHERE label=?", (label,)).fetchone()
        return row["value"] if row else ""

    def set_core_block(self, label: str, value: str, actor: str = "user") -> dict:
        if label not in CORE_BLOCK_LABELS:
            raise ValueError(f"invalid core block label: {label}")
        value = (value or "")[:CORE_BLOCK_MAX_CHARS]
        now = _now()
        with self._conn() as c:
            existing = c.execute("SELECT version FROM core_blocks WHERE label=?", (label,)).fetchone()
            if existing is None:
                c.execute(
                    "INSERT INTO core_blocks (label, value, updated_at, updated_by, version) VALUES (?,?,?,?,1)",
                    (label, value, now, actor),
                )
            else:
                c.execute(
                    "UPDATE core_blocks SET value=?, updated_at=?, updated_by=?, version=version+1 WHERE label=?",
                    (value, now, actor, label),
                )
            row = c.execute("SELECT * FROM core_blocks WHERE label=?", (label,)).fetchone()
        self._audit(memory_id=None, op="core_block_update", old_content=None,
                    new_content=value, actor=actor, session_id="", note=label)
        return _row_to_dict(row) or {}

    # ── Memories: writes ────────────────────────────────────────────────

    def add_memory(
        self,
        *,
        type: str,
        content: str,
        confidence: float,
        importance: float,
        durability: float,
        source_session_id: str = "",
        source_quote: str = "",
        status: str | None = None,
        user_id: str | None = None,
    ) -> dict:
        if type not in VALID_TYPES:
            raise ValueError(f"invalid memory type: {type}")
        confidence = max(0.0, min(1.0, float(confidence)))
        importance = max(0.0, min(1.0, float(importance)))
        durability = max(0.0, min(1.0, float(durability)))
        content = (content or "").strip()
        if not content:
            raise ValueError("content cannot be empty")
        source_quote = (source_quote or "")[:SOURCE_QUOTE_MAX_CHARS]

        from core.users import LEGACY_USER_ID
        owner = user_id or LEGACY_USER_ID

        # Confidence gating: discard below threshold
        if confidence < CONFIDENCE_DISCARD_MAX:
            self._audit(
                memory_id=None, op="discard", old_content=None, new_content=content,
                actor="extractor", session_id=source_session_id,
                note=f"low confidence {confidence:.2f} user={owner}",
            )
            return {"status": "discarded", "reason": f"confidence {confidence:.2f} < {CONFIDENCE_DISCARD_MAX}"}

        # Determine initial status
        if status is None:
            status = "pending" if confidence < CONFIDENCE_PENDING_MAX else "active"
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")

        # Conflict resolution: scan active memories for substring match (within same user)
        conflict = self._find_conflict(content, type, user_id=owner)
        if conflict is not None:
            return self._resolve_conflict(
                candidate={"type": type, "content": content, "confidence": confidence,
                           "importance": importance, "durability": durability,
                           "source_session_id": source_session_id, "source_quote": source_quote,
                           "status": status, "user_id": owner},
                existing=conflict,
            )

        return self._insert_memory(
            type=type, content=content, confidence=confidence,
            importance=importance, durability=durability,
            source_session_id=source_session_id, source_quote=source_quote,
            status=status, user_id=owner,
        )

    def _insert_memory(
        self, *, type: str, content: str, confidence: float, importance: float,
        durability: float, source_session_id: str, source_quote: str, status: str,
        user_id: str,
    ) -> dict:
        mid = _new_id()
        now = _now()
        with self._conn() as c:
            c.execute(
                """INSERT INTO memories
                   (id, type, content, confidence, importance, durability,
                    source_session_id, source_quote, status, pinned,
                    created_at, last_referenced, access_count, user_id)
                   VALUES (?,?,?,?,?,?,?,?,?,0,?,NULL,0,?)""",
                (mid, type, content, confidence, importance, durability,
                 source_session_id, source_quote, status, now, user_id),
            )
            row = c.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        self._audit(
            memory_id=mid, op="add", old_content=None, new_content=content,
            actor="extractor" if status == "pending" else "user",
            session_id=source_session_id, note=f"type={type} conf={confidence:.2f} user={user_id}",
        )
        return _row_to_dict(row) or {}

    def update_memory(self, memory_id: str, **fields) -> dict:
        allowed = {"type", "content", "confidence", "importance", "durability", "status", "pinned"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            raise ValueError("no updatable fields provided")
        if "type" in updates and updates["type"] not in VALID_TYPES:
            raise ValueError(f"invalid memory type: {updates['type']}")
        if "status" in updates and updates["status"] not in VALID_STATUSES:
            raise ValueError(f"invalid status: {updates['status']}")
        if "confidence" in updates:
            updates["confidence"] = max(0.0, min(1.0, float(updates["confidence"])))

        with self._conn() as c:
            existing = c.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not existing:
                raise KeyError(memory_id)
            set_clause = ", ".join(f"{k}=?" for k in updates)
            params = list(updates.values()) + [memory_id]
            c.execute(f"UPDATE memories SET {set_clause} WHERE id=?", params)
            new_row = c.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        self._audit(
            memory_id=memory_id, op="update", old_content=existing["content"],
            new_content=new_row["content"] if new_row else None,
            actor="user", session_id="", note=f"fields={list(updates.keys())}",
        )
        return _row_to_dict(new_row) or {}

    def delete_memory(self, memory_id: str, actor: str = "user") -> bool:
        with self._conn() as c:
            existing = c.execute("SELECT content FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not existing:
                return False
            c.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self._audit(
            memory_id=memory_id, op="delete", old_content=existing["content"],
            new_content=None, actor=actor, session_id="", note="",
        )
        return True

    def approve_memory(self, memory_id: str, actor: str = "user") -> dict:
        with self._conn() as c:
            existing = c.execute("SELECT status FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not existing:
                raise KeyError(memory_id)
            if existing["status"] != "pending":
                raise ValueError(f"memory {memory_id} is not pending (status={existing['status']})")
            c.execute("UPDATE memories SET status='active' WHERE id=?", (memory_id,))
            row = c.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        self._audit(
            memory_id=memory_id, op="approve", old_content=None, new_content=None,
            actor=actor, session_id="", note="",
        )
        return _row_to_dict(row) or {}

    def reject_memory(self, memory_id: str, actor: str = "user") -> dict:
        with self._conn() as c:
            existing = c.execute("SELECT status FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not existing:
                raise KeyError(memory_id)
            if existing["status"] != "pending":
                raise ValueError(f"memory {memory_id} is not pending (status={existing['status']})")
            c.execute("UPDATE memories SET status='rejected' WHERE id=?", (memory_id,))
            row = c.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        self._audit(
            memory_id=memory_id, op="reject", old_content=None, new_content=None,
            actor=actor, session_id="", note="",
        )
        return _row_to_dict(row) or {}

    def pin_memory(self, memory_id: str, pinned: bool = True) -> dict:
        with self._conn() as c:
            existing = c.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            if not existing:
                raise KeyError(memory_id)
            c.execute("UPDATE memories SET pinned=? WHERE id=?", (1 if pinned else 0, memory_id))
            row = c.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        self._audit(
            memory_id=memory_id, op="pin" if pinned else "unpin",
            old_content=None, new_content=None, actor="user", session_id="", note="",
        )
        return _row_to_dict(row) or {}

    # ── Conflict resolution ──────────────────────────────────────────────

    def _find_conflict(self, content: str, type: str, *, user_id: str = "user_legacy") -> dict | None:
        """Substring match for v1, scoped to one user. Capped at CONFLICT_SCAN_CAP rows."""
        content_lower = content.lower()
        if len(content_lower) < CONFLICT_SUBSTRING_MIN_LEN:
            return None
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM memories WHERE status IN ('active','pending') AND type=? AND user_id=? "
                "ORDER BY confidence DESC LIMIT ?",
                (type, user_id, CONFLICT_SCAN_CAP),
            ).fetchall()
        for r in rows:
            existing = (r["content"] or "").lower()
            if len(existing) < CONFLICT_SUBSTRING_MIN_LEN:
                continue
            if content_lower in existing or existing in content_lower:
                return _row_to_dict(r)
        return None

    def _resolve_conflict(self, candidate: dict, existing: dict) -> dict:
        new_conf = candidate["confidence"]
        old_conf = existing["confidence"]
        # Both high → new wins, old archived
        if new_conf >= CONFIDENCE_PENDING_MAX and old_conf >= CONFIDENCE_PENDING_MAX:
            self._archive_with_audit(existing, reason="superseded_by_new")
            return self._insert_memory(
                type=candidate["type"], content=candidate["content"],
                confidence=candidate["confidence"], importance=candidate["importance"],
                durability=candidate["durability"],
                source_session_id=candidate["source_session_id"],
                source_quote=candidate["source_quote"], status=candidate["status"],
                user_id=candidate.get("user_id", "user_legacy"),
            )
        # Old high, new low → keep old, discard new
        if old_conf >= CONFIDENCE_PENDING_MAX and new_conf < CONFIDENCE_PENDING_MAX:
            self._audit(
                memory_id=existing["id"], op="discard", old_content=None,
                new_content=candidate["content"], actor="extractor",
                session_id=candidate["source_session_id"],
                note=f"conflict: existing active supersedes candidate (conf {new_conf:.2f})",
            )
            return {"status": "discarded", "reason": "existing active memory supersedes", "kept": existing["id"]}
        # Both pending → keep older (existing), discard new
        self._audit(
            memory_id=existing["id"], op="discard", old_content=None,
            new_content=candidate["content"], actor="extractor",
            session_id=candidate["source_session_id"],
            note="conflict: both pending, keeping older",
        )
        return {"status": "discarded", "reason": "pending duplicate", "kept": existing["id"]}

    def _archive_with_audit(self, memory: dict, *, reason: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE memories SET status='archived' WHERE id=?", (memory["id"],))
        self._audit(
            memory_id=memory["id"], op="archive", old_content=memory["content"],
            new_content=None, actor="extractor", session_id="", note=reason,
        )

    # ── Memories: queries ───────────────────────────────────────────────

    def list_memories(
        self, *, status: str = "active", type: str | None = None, limit: int = 50,
        user_id: str | None = None, include_all: bool = False,
    ) -> list[dict]:
        sql = "SELECT * FROM memories WHERE status=?"
        params: list[Any] = [status]
        if type is not None:
            sql += " AND type=?"
            params.append(type)
        if user_id is not None and not include_all:
            sql += " AND user_id=?"
            params.append(user_id)
        sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [d for d in (_row_to_dict(r) for r in rows) if d is not None]

    def list_pending(self, limit: int = 50, *, user_id: str | None = None, include_all: bool = False) -> list[dict]:
        return self.list_memories(status="pending", limit=limit, user_id=user_id, include_all=include_all)

    def search(
        self, query: str, n: int = 10, *,
        user_id: str | None = None, include_all: bool = False,
    ) -> list[dict]:
        """FTS5 keyword search. Returns memories with status='active' (any confidence)."""
        if not query.strip():
            return []
        escaped = _fts_escape(query)
        sql = """SELECT m.* FROM memories m
                 JOIN memories_fts f ON m.rowid = f.rowid
                 WHERE memories_fts MATCH ? AND m.status='active'"""
        params: list[Any] = [escaped]
        if user_id is not None and not include_all:
            sql += " AND m.user_id=?"
            params.append(user_id)
        sql += " ORDER BY rank LIMIT ?"
        params.append(n)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [d for d in (_row_to_dict(r) for r in rows) if d is not None]

    def recall_for_context(
        self, query: str, n: int = 5, min_confidence: float = 0.7,
        *, user_id: str | None = None, include_all: bool = False,
    ) -> list[dict]:
        """FTS5 + confidence filter. Bumps access counters atomically before returning."""
        if not query.strip():
            return []
        escaped = _fts_escape(query)
        now = _now()
        where_extra = ""
        params_pre: list[Any] = []
        if user_id is not None and not include_all:
            where_extra = " AND m.user_id=?"
            params_pre.append(user_id)
        with self._conn() as c:
            # Pre-bump access counters for matching rows so the returned
            # records reflect the access that just happened.
            c.execute(
                f"""UPDATE memories
                   SET access_count=access_count+1, last_referenced=?
                   WHERE id IN (
                     SELECT m.id FROM memories m
                     JOIN memories_fts f ON m.rowid = f.rowid
                     WHERE memories_fts MATCH ? AND m.status='active' AND m.confidence >= ?{where_extra}
                     ORDER BY rank, m.confidence DESC LIMIT ?
                   )""",
                (now, escaped, min_confidence, *params_pre, n),
            )
            rows = c.execute(
                f"""SELECT m.* FROM memories m
                   JOIN memories_fts f ON m.rowid = f.rowid
                   WHERE memories_fts MATCH ? AND m.status='active' AND m.confidence >= ?{where_extra}
                   ORDER BY rank, m.confidence DESC LIMIT ?""",
                (escaped, min_confidence, *params_pre, n),
            ).fetchall()
        return [d for d in (_row_to_dict(r) for r in rows) if d is not None]

    def get(self, memory_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return _row_to_dict(row)

    def record_injection(self, memory_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE memories SET access_count=access_count+1, last_referenced=? WHERE id=?",
                (_now(), memory_id),
            )

    # ── Decay ───────────────────────────────────────────────────────────

    def run_decay(self, *, days: int = DECAY_DAYS, floor: float = DECAY_IMPORTANCE_FLOOR) -> int:
        """Archive old low-importance active memories. Returns count archived."""
        now = _now()
        cutoff_created = now - days * 86400
        archived_ids: list[tuple[str, str, float]] = []  # (id, content, effective)
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM memories WHERE status='active' AND pinned=0 AND created_at < ?",
                (cutoff_created,),
            ).fetchall()
            for r in rows:
                days_since_ref = 0.0
                if r["last_referenced"]:
                    days_since_ref = (now - r["last_referenced"]) / 86400
                effective = (r["importance"] or 0) * (DECAY_RATE ** days_since_ref)
                if effective < floor:
                    c.execute("UPDATE memories SET status='archived' WHERE id=?", (r["id"],))
                    archived_ids.append((r["id"], r["content"], effective))
        # Audit after the main transaction closes (avoids cross-connection lock)
        for mid, content, effective in archived_ids:
            self._audit(
                memory_id=mid, op="decay_archive", old_content=content, new_content=None,
                actor="dreamer", session_id="", note=f"effective={effective:.3f} < {floor}",
            )
        # Opportunistic: prune audit log rows older than retention cutoff
        # (does not block on result — best-effort, safe to call from any path)
        self.prune_audit()
        return len(archived_ids)

    # ── Audit retention ─────────────────────────────────────────────────

    def prune_audit(self, *, days: int = AUDIT_RETENTION_DAYS) -> int:
        """Delete audit rows older than `days`. Returns count deleted.

        Keeps the audit table from growing unbounded over years of use.
        Memories themselves are not affected — only the per-op audit trail.
        Call explicitly (e.g. from the dreaming subagent) or let
        `run_decay()` do it opportunistically.
        """
        cutoff = _now() - days * 86400
        with self._conn() as c:
            cur = c.execute("DELETE FROM memory_audit WHERE ts < ?", (cutoff,))
        deleted = cur.rowcount
        if deleted:
            logger.info("audit: pruned %d rows older than %dd", deleted, days)
        return deleted

    # ── Audit ───────────────────────────────────────────────────────────

    def _audit(
        self, *, memory_id: str | None, op: str, old_content: str | None,
        new_content: str | None, actor: str, session_id: str, note: str,
    ) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO memory_audit (ts, memory_id, op, old_content, new_content, actor, session_id, note)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (_now(), memory_id, op,
                 (old_content or "")[:1000], (new_content or "")[:1000],
                 actor, session_id, (note or "")[:500]),
            )

    def audit_log(self, limit: int = 100, memory_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM memory_audit"
        params: list[Any] = []
        if memory_id is not None:
            sql += " WHERE memory_id=?"
            params.append(memory_id)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [d for d in (_row_to_dict(r) for r in rows) if d is not None]

    def stats(self) -> dict:
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"]
            by_status = c.execute("SELECT status, COUNT(*) AS n FROM memories GROUP BY status").fetchall()
            by_type = c.execute("SELECT type, COUNT(*) AS n FROM memories GROUP BY type").fetchall()
            by_conf = c.execute(
                """SELECT
                    SUM(CASE WHEN confidence < 0.6 THEN 1 ELSE 0 END) AS low,
                    SUM(CASE WHEN confidence >= 0.6 AND confidence < 0.7 THEN 1 ELSE 0 END) AS pending_bucket,
                    SUM(CASE WHEN confidence >= 0.7 THEN 1 ELSE 0 END) AS high
                   FROM memories"""
            ).fetchone()
            pending_count = c.execute("SELECT COUNT(*) AS n FROM memories WHERE status='pending'").fetchone()["n"]
        return {
            "total": total,
            "pending": pending_count,
            "by_status": {r["status"]: r["n"] for r in by_status},
            "by_type": {r["type"]: r["n"] for r in by_type},
            "by_confidence_bucket": {
                "low_<0.6": by_conf["low"] or 0,
                "pending_0.6-0.7": by_conf["pending_bucket"] or 0,
                "active_>=0.7": by_conf["high"] or 0,
            },
        }
