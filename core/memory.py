import sqlite3
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from core.stores import ProjectStore, SessionStore, TaskStore
from core.users import UserStore
from core.api_keys import ApiKeyStore

logger = logging.getLogger(__name__)


class Memory:
    def __init__(self, db_path: str = "./data/nexus.db", chroma_path: str = "./data/chromadb"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(chroma_path).mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_sqlite(db_path)
        self._init_chroma(chroma_path)
        self.projects = ProjectStore(self._conn)
        self.sessions = SessionStore(self._conn)
        self.tasks = TaskStore(self._conn)
        self.users = UserStore(self._conn)
        self.api_keys = ApiKeyStore(self._conn)

    def _init_sqlite(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                agent TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                timestamp TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                project_id TEXT,
                title TEXT DEFAULT '',
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                payload TEXT NOT NULL DEFAULT '{}',
                result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                title TEXT NOT NULL,
                channel TEXT DEFAULT 'web',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                password_hash TEXT,
                oauth_provider TEXT,
                oauth_id TEXT,
                created_at TEXT NOT NULL,
                last_seen TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_users_oauth ON users(oauth_provider, oauth_id);
            CREATE TABLE IF NOT EXISTS api_keys (
                key_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'user',
                name TEXT,
                created_at TEXT NOT NULL,
                last_used TEXT,
                expires_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id, created_at DESC);
        """)
        self._migrate_columns()

    def _migrate_columns(self):
        conv_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(conversations)").fetchall()}
        if "session_id" not in conv_cols:
            self._conn.execute("ALTER TABLE conversations ADD COLUMN session_id TEXT")
            self._conn.commit()
        sess_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "expires_at" not in sess_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN expires_at TEXT")
            self._conn.commit()

    def _init_chroma(self, path: str):
        try:
            import chromadb
            self._chroma = chromadb.PersistentClient(path=path)
            self._collection = self._chroma.get_or_create_collection("nexus_memory")
        except Exception:
            self._collection = None

    def cleanup_expired_sessions(self, max_age_hours: int = 24) -> int:
        cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
        count = self._conn.execute(
            "DELETE FROM sessions WHERE (expires_at IS NOT NULL AND expires_at < ?) OR (expires_at IS NULL AND updated_at < ?)",
            (datetime.now().isoformat(), cutoff),
        ).rowcount
        if count:
            self._conn.commit()
            logger = __import__("logging").getLogger(__name__)
            logger.info("[memory] Cleaned %d expired sessions", count)
        return count

    def set_session_expiry(self, session_id: str, hours: int = 24) -> None:
        expires = (datetime.now() + timedelta(hours=hours)).isoformat()
        self._conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?",
            (expires, session_id),
        )
        self._conn.commit()

    def save_conversation(self, agent: str, role: str, content: str, session_id: str | None = None):
        now = datetime.now().isoformat()
        if session_id:
            row = self._conn.execute(
                "SELECT expires_at FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row and row["expires_at"] and row["expires_at"] < now:
                return
        self._conn.execute(
            "INSERT INTO conversations (session_id, agent, role, content, timestamp) VALUES (?, ?, ?, ?, ?)",
            (session_id, agent, role, content, now),
        )
        self._conn.commit()
        if session_id:
            self.sessions.touch(session_id)
        if self._collection:
            self._collection.add(
                documents=[content],
                metadatas=[{"agent": agent, "role": role, "timestamp": now, "session_id": session_id or ""}],
                ids=[f"conv_{now}_{agent}_{hash(content) % 10**8}"],
            )

    def list_conversations(self, session_id: str | None = None, agent: str | None = None, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM conversations WHERE 1=1"
        params: list = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if agent:
            query += " AND agent = ?"
            params.append(agent)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in reversed(rows)]

    def search_similar(self, query: str, n: int = 5) -> list[dict]:
        if not self._collection:
            return []
        results = self._collection.query(query_texts=[query], n_results=n)
        output = []
        for i, doc in enumerate(results.get("documents", [[]])[0]):
            meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
            output.append({"content": doc, "metadata": meta})
        return output

    def list_knowledge(self, limit: int = 100, offset: int = 0) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM knowledge ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset)
        ).fetchall()
        return [
            {
                "id": r["id"],
                "key": r["key"],
                "value": r["value"],
                "metadata": json.loads(r["metadata"] or "{}"),
                "timestamp": r["timestamp"],
            }
            for r in rows
        ]

    def delete_knowledge(self, key: str) -> bool:
        cur = self._conn.execute("DELETE FROM knowledge WHERE key = ?", (key,))
        self._conn.commit()
        return cur.rowcount > 0

    def save_knowledge(self, key: str, value: str, metadata: dict | None = None):
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO knowledge (key, value, metadata, timestamp) VALUES (?, ?, ?, ?)",
            (key, value, json.dumps(metadata or {}), now),
        )
        self._conn.commit()

    def get_context(self, agent: str, last_n: int = 10, session_id: str | None = None) -> list[dict[str, str]]:
        if session_id:
            cursor = self._conn.execute(
                "SELECT role, content FROM conversations WHERE agent = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
                (agent, session_id, last_n),
            )
        else:
            cursor = self._conn.execute(
                "SELECT role, content FROM conversations WHERE agent = ? ORDER BY id DESC LIMIT ?",
                (agent, last_n),
            )
        rows = cursor.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def stats(self) -> dict:
        conv_count = self._conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        knowledge_count = self._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        session_count = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        project_count = self._conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        agents = self._conn.execute(
            "SELECT agent, COUNT(*) as c FROM conversations GROUP BY agent"
        ).fetchall()
        return {
            "conversations": conv_count,
            "knowledge": knowledge_count,
            "sessions": session_count,
            "projects": project_count,
            "by_agent": {r["agent"]: r["c"] for r in agents},
            "vector_enabled": self._collection is not None,
        }
