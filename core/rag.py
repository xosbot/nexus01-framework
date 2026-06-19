"""RAG — document ingestion and semantic search (ChromaDB + optional Supabase)."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            break_at = text.rfind("\n\n", start, end)
            if break_at == -1:
                break_at = text.rfind(" ", start, end)
            if break_at > start:
                end = break_at
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end - overlap, start + 1)
    return chunks


class RAGStore:
    def __init__(
        self,
        chroma_path: str = "./data/chromadb",
        supabase_url: str = "",
        supabase_key: str = "",
        collection_name: str = "tradecraft",
    ):
        self.collection_name = collection_name
        self._chroma = None
        self._collection = None
        self._embed_fn = None
        self._supabase_url = supabase_url.rstrip("/") if supabase_url else ""
        self._supabase_key = supabase_key
        self._memory_store: dict[str, dict] = {}
        self._init_chroma(chroma_path)

    def _init_chroma(self, path: str) -> None:
        try:
            import chromadb
            Path(path).mkdir(parents=True, exist_ok=True)
            self._chroma = chromadb.PersistentClient(path=path)
            self._collection = self._chroma.get_or_create_collection(self.collection_name)
            logger.info("RAG: ChromaDB collection '%s' ready", self.collection_name)
        except Exception as exc:
            logger.warning("RAG: ChromaDB unavailable: %s", exc)

    def _get_embedder(self):
        if self._embed_fn:
            return self._embed_fn
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            self._embed_fn = lambda texts: model.encode(texts).tolist()
            return self._embed_fn
        except Exception as exc:
            logger.warning("RAG: sentence-transformers unavailable: %s", exc)
            return None

    def ingest_file(self, path: Path, source: str | None = None) -> int:
        if not path.exists():
            return 0
        text = path.read_text(encoding="utf-8", errors="ignore")
        return self.ingest_text(text, source=source or path.name, metadata={"path": str(path)})

    def ingest_text(self, text: str, source: str = "manual", metadata: dict | None = None) -> int:
        chunks = chunk_text(text)
        if not chunks:
            return 0
        meta = metadata or {}
        ids, docs, metas = [], [], []
        for i, chunk in enumerate(chunks):
            doc_id = hashlib.md5(f"{source}:{i}:{chunk[:50]}".encode()).hexdigest()
            ids.append(doc_id)
            docs.append(chunk)
            metas.append({**meta, "source": source, "chunk": i})
        if self._collection:
            embedder = self._get_embedder()
            if embedder:
                embeddings = embedder(docs)
                self._collection.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
            else:
                self._collection.upsert(ids=ids, documents=docs, metadatas=metas)
        else:
            for i, doc_id in enumerate(ids):
                self._memory_store[doc_id] = {"content": docs[i], "metadata": metas[i]}
        if self._supabase_url and self._supabase_key:
            self._upsert_supabase(ids, docs, metas)
        return len(chunks)

    def ingest_directory(self, directory: Path, pattern: str = "**/*.md") -> dict:
        directory = Path(directory)
        stats = {"files": 0, "chunks": 0, "errors": []}
        if not directory.exists():
            return stats
        for path in directory.glob(pattern):
            if not path.is_file():
                continue
            try:
                n = self.ingest_file(path)
                stats["files"] += 1
                stats["chunks"] += n
            except Exception as exc:
                stats["errors"].append(f"{path}: {exc}")
        return stats

    def search(self, query: str, n: int = 5) -> list[dict[str, Any]]:
        if self._collection:
            try:
                embedder = self._get_embedder()
                if embedder:
                    emb = embedder([query])
                    results = self._collection.query(query_embeddings=emb, n_results=n)
                else:
                    results = self._collection.query(query_texts=[query], n_results=n)
                output = []
                for i, doc in enumerate(results.get("documents", [[]])[0]):
                    meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
                    dist = results.get("distances", [[]])[0][i] if results.get("distances") else None
                    output.append({"content": doc, "metadata": meta, "distance": dist})
                return output
            except Exception as exc:
                logger.warning("RAG search failed: %s", exc)
        return self._memory_search(query, n)

    def _memory_search(self, query: str, n: int) -> list[dict[str, Any]]:
        if not self._memory_store:
            return []
        terms = set(query.lower().split())
        scored = []
        for item in self._memory_store.values():
            content = item["content"].lower()
            score = sum(1 for t in terms if t in content)
            if score:
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"content": s[1]["content"], "metadata": s[1]["metadata"]} for s in scored[:n]]

    def format_context(self, query: str, n: int = 3) -> str:
        hits = self.search(query, n)
        if not hits:
            return ""
        parts = []
        for h in hits:
            src = h.get("metadata", {}).get("source", "unknown")
            parts.append(f"[{src}]\n{h['content']}")
        return "\n\n---\n\n".join(parts)

    def stats(self) -> dict:
        count = self._collection.count() if self._collection else len(self._memory_store)
        return {
            "collection": self.collection_name,
            "documents": count,
            "chroma_enabled": self._collection is not None,
            "supabase_enabled": bool(self._supabase_url and self._supabase_key),
            "embedder": self._embed_fn is not None,
        }

    def _upsert_supabase(self, ids: list[str], docs: list[str], metas: list[dict]) -> None:
        try:
            import httpx
            embedder = self._get_embedder()
            if not embedder:
                return
            embeddings = embedder(docs)
            rows = [
                {"id": ids[i], "content": docs[i], "metadata": metas[i], "embedding": embeddings[i]}
                for i in range(len(ids))
            ]
            headers = {
                "apikey": self._supabase_key,
                "Authorization": f"Bearer {self._supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            }
            with httpx.Client(timeout=30) as client:
                client.post(f"{self._supabase_url}/rest/v1/rag_documents", json=rows, headers=headers)
        except Exception as exc:
            logger.debug("Supabase upsert skipped: %s", exc)
