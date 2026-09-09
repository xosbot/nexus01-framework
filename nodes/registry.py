"""Durable NodeRegistry — SQLite/WAL, UTC timestamps, parameterized SQL."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from nodes.identity import NodeIdentity, NodeSession, NodeState, validate_node_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class NodeNotFound(RuntimeError):
    pass


class DuplicateNode(RuntimeError):
    pass


class NodeRegistry:
    """Durable registry: nodes + sessions + events. Survives restart."""

    def __init__(self, db_path: str | Path = "data/xos_nodes.db") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    role TEXT NOT NULL,
                    capabilities TEXT NOT NULL DEFAULT '[]',
                    working_directory TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT 'STOPPED',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS node_sessions (
                    session_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    pid INTEGER,
                    state TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    exit_code INTEGER,
                    last_seen_at TEXT NOT NULL,
                    FOREIGN KEY(node_id) REFERENCES nodes(node_id)
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_node ON node_sessions(node_id);
                CREATE TABLE IF NOT EXISTS node_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    node_id TEXT NOT NULL,
                    session_id TEXT,
                    correlation_id TEXT,
                    provider TEXT NOT NULL DEFAULT '',
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_events_node ON node_events(node_id, id);
                CREATE INDEX IF NOT EXISTS idx_events_session ON node_events(session_id, id);
                """
            )

    # -- nodes --

    def register_node(
        self,
        *,
        node_id: str,
        name: str,
        provider: str,
        role: str = "coder",
        capabilities: list[str] | None = None,
        working_directory: str = "",
    ) -> NodeIdentity:
        validate_node_id(node_id)
        if not name or not provider:
            raise ValueError("name and provider are required")
        created = _now_iso()
        with self._lock, self._conn:
            exists = self._conn.execute(
                "SELECT 1 FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if exists:
                raise DuplicateNode(f"node_id {node_id} already registered")
            self._conn.execute(
                """INSERT INTO nodes
                   (node_id, name, provider, role, capabilities, working_directory, state, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'STOPPED', ?)""",
                (
                    node_id,
                    name,
                    provider,
                    role,
                    json.dumps(capabilities or [], sort_keys=True),
                    working_directory,
                    created,
                ),
            )
            self._append_event_locked(
                node_id=node_id,
                session_id=None,
                correlation_id=None,
                provider=provider,
                event_type="node.registered",
                data={"name": name, "role": role},
            )
        return self.get_node(node_id)

    def get_node(self, node_id: str) -> NodeIdentity:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                raise NodeNotFound(node_id)
            return self._node_from_row(row)

    def list_nodes(self) -> list[NodeIdentity]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM nodes ORDER BY node_id").fetchall()
            return [self._node_from_row(r) for r in rows]

    def update_node(self, node_id: str, **fields) -> NodeIdentity:
        allowed = {"name", "provider", "role", "capabilities", "working_directory"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_node(node_id)
        with self._lock, self._conn:
            self.get_node(node_id)
            if "capabilities" in updates:
                updates["capabilities"] = json.dumps(updates["capabilities"], sort_keys=True)
            sets = ", ".join(f"{k}=?" for k in updates)
            self._conn.execute(
                f"UPDATE nodes SET {sets} WHERE node_id=?",
                (*updates.values(), node_id),
            )
        return self.get_node(node_id)

    def update_state(self, node_id: str, state: NodeState) -> None:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE nodes SET state=? WHERE node_id=?", (state.value, node_id)
            )
            if cur.rowcount != 1:
                raise NodeNotFound(node_id)

    def get_state(self, node_id: str) -> NodeState:
        with self._lock:
            row = self._conn.execute(
                "SELECT state FROM nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            if row is None:
                raise NodeNotFound(node_id)
            return NodeState(row["state"])

    # -- sessions --

    def start_session(self, node_id: str, pid: int | None) -> NodeSession:
        self.get_node(node_id)
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        now = _now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT INTO node_sessions
                   (session_id, node_id, pid, state, started_at, ended_at, exit_code, last_seen_at)
                   VALUES (?, ?, ?, 'RUNNING', ?, NULL, NULL, ?)""",
                (session_id, node_id, pid, now, now),
            )
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> NodeSession:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM node_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None:
                raise NodeNotFound(session_id)
            return self._session_from_row(row)

    def list_sessions(self, node_id: str) -> list[NodeSession]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM node_sessions WHERE node_id=? ORDER BY started_at",
                (node_id,),
            ).fetchall()
            return [self._session_from_row(r) for r in rows]

    def touch_session(self, session_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE node_sessions SET last_seen_at=? WHERE session_id=?",
                (_now_iso(), session_id),
            )

    def end_session(
        self, session_id: str, *, exit_code: int | None = None, state: str = "STOPPED"
    ) -> NodeSession:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE node_sessions SET ended_at=?, exit_code=?, state=? WHERE session_id=?",
                (_now_iso(), exit_code, state, session_id),
            )
            if cur.rowcount != 1:
                raise NodeNotFound(session_id)
        return self.get_session(session_id)

    # -- events --

    def append_event(
        self,
        *,
        node_id: str,
        event_type: str,
        session_id: str | None = None,
        correlation_id: str | None = None,
        provider: str = "",
        data: dict | None = None,
    ) -> str:
        with self._lock, self._conn:
            return self._append_event_locked(
                node_id=node_id,
                session_id=session_id,
                correlation_id=correlation_id,
                provider=provider,
                event_type=event_type,
                data=data or {},
            )

    def _append_event_locked(
        self,
        *,
        node_id: str,
        session_id: str | None,
        correlation_id: str | None,
        provider: str,
        event_type: str,
        data: dict,
    ) -> str:
        event_id = f"nev_{uuid.uuid4().hex[:12]}"
        # bound data to avoid unbounded growth
        blob = json.dumps(data, sort_keys=True, default=str)[:4000]
        self._conn.execute(
            """INSERT INTO node_events
               (event_id, node_id, session_id, correlation_id, provider, event_type, created_at, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                node_id,
                session_id,
                correlation_id,
                provider,
                event_type,
                _now_iso(),
                blob,
            ),
        )
        return event_id

    def list_events(
        self, node_id: str | None = None, limit: int = 200
    ) -> list[dict]:
        with self._lock:
            if node_id:
                rows = self._conn.execute(
                    "SELECT * FROM node_events WHERE node_id=? ORDER BY id ASC LIMIT ?",
                    (node_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM node_events ORDER BY id ASC LIMIT ?", (limit,)
                ).fetchall()
            out = []
            for r in rows:
                out.append(
                    {
                        "event_id": r["event_id"],
                        "node_id": r["node_id"],
                        "session_id": r["session_id"],
                        "correlation_id": r["correlation_id"],
                        "provider": r["provider"],
                        "event_type": r["event_type"],
                        "created_at": r["created_at"],
                        "data": json.loads(r["data"] or "{}"),
                    }
                )
            return out

    @staticmethod
    def _node_from_row(row: sqlite3.Row) -> NodeIdentity:
        return NodeIdentity(
            node_id=row["node_id"],
            name=row["name"],
            provider=row["provider"],
            role=row["role"],
            capabilities=json.loads(row["capabilities"] or "[]"),
            working_directory=row["working_directory"] or "",
            created_at=row["created_at"],
        )

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> NodeSession:
        return NodeSession(
            session_id=row["session_id"],
            node_id=row["node_id"],
            pid=row["pid"],
            state=NodeState(row["state"]),
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            exit_code=row["exit_code"],
            last_seen_at=row["last_seen_at"],
        )
