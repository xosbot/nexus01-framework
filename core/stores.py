import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path


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
