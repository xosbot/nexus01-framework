import sqlite3
import json
from datetime import datetime
from pathlib import Path

class Memory:
    def __init__(self, db_path: str = "./data/nexus.db", chroma_path: str = "./data/chromadb"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(chroma_path).mkdir(parents=True, exist_ok=True)
        self._init_sqlite(db_path)
        self._init_chroma(chroma_path)

    def _init_sqlite(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT DEFAULT 'pending',
                payload TEXT NOT NULL,
                result TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
        """)

    def _init_chroma(self, path: str):
        try:
            import chromadb
            self._chroma = chromadb.PersistentClient(path=path)
            self._collection = self._chroma.get_or_create_collection("nexus_memory")
        except Exception:
            self._collection = None

    def save_conversation(self, agent: str, role: str, content: str):
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO conversations (agent, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (agent, role, content, now)
        )
        self._conn.commit()
        if self._collection:
            self._collection.add(
                documents=[content],
                metadatas=[{"agent": agent, "role": role, "timestamp": now}],
                ids=[f"conv_{now}_{agent}"]
            )

    def search_similar(self, query: str, n: int = 5) -> list[dict]:
        if not self._collection:
            return []
        results = self._collection.query(query_texts=[query], n_results=n)
        output = []
        for i, doc in enumerate(results.get("documents", [[]])[0]):
            meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
            output.append({"content": doc, "metadata": meta})
        return output

    def save_knowledge(self, key: str, value: str, metadata: dict | None = None):
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO knowledge (key, value, metadata, timestamp) VALUES (?, ?, ?, ?)",
            (key, value, json.dumps(metadata or {}), now)
        )
        self._conn.commit()

    def get_context(self, agent: str, last_n: int = 10) -> list[dict[str, str]]:
        cursor = self._conn.execute(
            "SELECT role, content FROM conversations WHERE agent = ? ORDER BY id DESC LIMIT ?",
            (agent, last_n)
        )
        rows = cursor.fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
