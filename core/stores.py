from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime


class ProjectStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, name: str, description: str = "", metadata: dict | None = None) -> dict:
        pid = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO projects (id, name, description, status, created_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, name, description, "active", now, now, json.dumps(metadata or {})),
        )
        self._conn.commit()
        return self.get(pid)

    def list(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self._conn.execute("SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC", (status,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [self._row(r) for r in rows]

    def get(self, project_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._row(row) if row else None

    def update(self, project_id: str, **fields) -> dict | None:
        project = self.get(project_id)
        if not project:
            return None
        name = fields.get("name", project["name"])
        description = fields.get("description", project["description"])
        status = fields.get("status", project["status"])
        metadata = fields.get("metadata", project["metadata"])
        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE projects SET name=?, description=?, status=?, metadata=?, updated_at=? WHERE id=?",
            (name, description, status, json.dumps(metadata), now, project_id),
        )
        self._conn.commit()
        return self.get(project_id)

    def delete(self, project_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _row(row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": json.loads(row["metadata"] or "{}"),
        }


class SessionStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, title: str = "New Session", project_id: str | None = None, channel: str = "web", metadata: dict | None = None) -> dict:
        sid = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO sessions (id, project_id, title, channel, created_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, project_id, title, channel, now, now, json.dumps(metadata or {})),
        )
        self._conn.commit()
        return self.get(sid)

    def list(self, project_id: str | None = None, limit: int = 50) -> list[dict]:
        if project_id:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE project_id = ? ORDER BY updated_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def get(self, session_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._row(row) if row else None

    def touch(self, session_id: str, title: str | None = None) -> None:
        now = datetime.now().isoformat()
        if title:
            self._conn.execute("UPDATE sessions SET updated_at=?, title=? WHERE id=?", (now, title, session_id))
        else:
            self._conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        self._conn.commit()

    def delete(self, session_id: str) -> bool:
        self._conn.execute("DELETE FROM conversations WHERE session_id = ?", (session_id,))
        cur = self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _row(row) -> dict:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "channel": row["channel"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": json.loads(row["metadata"] or "{}"),
        }


class TaskStore:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(
        self,
        project_id: str,
        title: str,
        description: str = "",
        status: str = "pending",
        metadata: dict | None = None,
    ) -> dict:
        tid = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        self._conn.execute(
            """INSERT INTO tasks (id, project_id, title, description, status, payload, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tid, project_id, title, description, status, json.dumps(metadata or {}), now, now),
        )
        self._conn.commit()
        return self.get(tid)

    def list(self, project_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [self._row(r) for r in rows]

    def get(self, task_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row(row) if row else None

    def update(self, task_id: str, **fields) -> dict | None:
        task = self.get(task_id)
        if not task:
            return None
        now = datetime.now().isoformat()
        updates = []
        params: list = []
        for field_name in ("title", "description", "status", "project_id"):
            if field_name in fields:
                updates.append(f"{field_name} = ?")
                params.append(fields[field_name])
        if "completed_at" in fields:
            updates.append("completed_at = ?")
            params.append(fields["completed_at"])
        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(task_id)
            self._conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
            self._conn.commit()
        return self.get(task_id)

    def delete(self, task_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def progress(self, project_id: str) -> dict:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks WHERE project_id = ? GROUP BY status",
            (project_id,),
        ).fetchall()
        counts = {r["status"]: r["cnt"] for r in rows}
        total = sum(counts.values())
        done = counts.get("done", 0) + counts.get("completed", 0)
        return {
            "total": total,
            "done": done,
            "pending": counts.get("pending", 0),
            "in_progress": counts.get("in_progress", 0),
            "percent": round(done / total * 100, 1) if total > 0 else 0,
        }

    @staticmethod
    def _row(row) -> dict:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "payload": json.loads(row["payload"] or "{}"),
            "result": row["result"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "completed_at": row["completed_at"],
        }


class SettingsStore:
    """Key-value store for runtime settings in SQLite."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=?, updated_at=?",
            (key, value, now, value, now),
        )
        self._conn.commit()

    def delete(self, key: str) -> bool:
        cur = self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        self._conn.commit()
        return cur.rowcount > 0

    def list(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
        return {r[0]: r[1] for r in rows}

    def get_bool(self, key: str, default: bool = False) -> bool:
        val = self.get(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "yes")

    def get_int(self, key: str, default: int = 0) -> int:
        val = self.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except ValueError:
            return default
