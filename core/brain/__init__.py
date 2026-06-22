"""IVA Brain — Second Brain Architecture.

Inspired by human neural systems, the brain module provides:
- Episodic Memory (events, conversations)
- Semantic Memory (knowledge, facts)
- Procedural Memory (how-to, workflows)
- Working Memory (current context)
- Decision Engine (planning, reasoning)
- Priority System (urgency, importance)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from dataclasses import dataclass, field

from core.memory import Memory
from core.rag import RAG


@dataclass
class MemoryEntry:
    id: str
    type: str  # episodic, semantic, procedural, working
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5
    confidence: float = 0.8
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    access_count: int = 0
    last_accessed: str = ""
    decay_rate: float = 0.01

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "metadata": self.metadata,
            "importance": self.importance,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "tags": self.tags,
            "sources": self.sources,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
        }

    def access(self) -> None:
        self.access_count += 1
        self.last_accessed = datetime.now(timezone.utc).isoformat()

    def calculate_strength(self) -> float:
        time_factor = 1.0 / (1.0 + self.decay_rate * self.access_count)
        return self.importance * self.confidence * time_factor


class IVABrain:
    """IVA's cognitive system — second brain architecture."""

    def __init__(self, memory: Memory, rag: RAG):
        self.memory = memory
        self.rag = rag
        self.working_memory: list[MemoryEntry] = []
        self.episodic: list[MemoryEntry] = []
        self.semantic: list[MemoryEntry] = []
        self.procedural: list[MemoryEntry] = []
        self._max_working = 10
        self._max_episodic = 1000
        self._load_from_storage()

    def _load_from_storage(self) -> None:
        try:
            knowledge = self.memory.get_all_knowledge()
            for item in knowledge:
                entry = MemoryEntry(
                    id=item.get("id", ""),
                    type=item.get("type", "semantic"),
                    content=item.get("content", ""),
                    metadata=item.get("metadata", {}),
                    importance=item.get("importance", 0.5),
                    confidence=item.get("confidence", 0.8),
                    tags=item.get("tags", []),
                    sources=item.get("sources", []),
                )
                if entry.type == "semantic":
                    self.semantic.append(entry)
                elif entry.type == "procedural":
                    self.procedural.append(entry)
        except Exception:
            pass

    def think(self, context: str, query: str = "") -> str:
        relevant = self._retrieve_relevant(context + " " + query)
        working = self._update_working_memory(context)
        return self._synthesize_response(context, relevant, working)

    def remember(self, content: str, memory_type: str = "episodic",
                 importance: float = 0.5, tags: list[str] = None,
                 sources: list[str] = None) -> MemoryEntry:
        entry = MemoryEntry(
            id=f"{memory_type}_{int(time.time())}",
            type=memory_type,
            content=content,
            importance=importance,
            tags=tags or [],
            sources=sources or [],
        )
        if memory_type == "episodic":
            self.episodic.append(entry)
            if len(self.episodic) > self._max_episodic:
                self.episodic.pop(0)
        elif memory_type == "semantic":
            self.semantic.append(entry)
        elif memory_type == "procedural":
            self.procedural.append(entry)
        self.memory.save_knowledge(
            f"{memory_type}_{entry.id}",
            content,
            {"type": memory_type, "importance": importance,
             "tags": tags or [], "sources": sources or []}
        )
        return entry

    def recall(self, query: str, memory_type: str = None,
               limit: int = 10) -> list[MemoryEntry]:
        results = []
        all_memory = self.episodic + self.semantic + self.procedural
        if memory_type:
            all_memory = [m for m in all_memory if m.type == memory_type]
        query_lower = query.lower()
        for entry in all_memory:
            score = self._calculate_relevance(entry, query_lower)
            if score > 0.3:
                entry.access()
                results.append((score, entry))
        results.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in results[:limit]]

    def forget(self, entry_id: str) -> bool:
        for lst in [self.episodic, self.semantic, self.procedural]:
            for i, entry in enumerate(lst):
                if entry.id == entry_id:
                    lst.pop(i)
                    return True
        return False

    def consolidate(self) -> dict:
        stats = {
            "episodic": len(self.episodic),
            "semantic": len(self.semantic),
            "procedural": len(self.procedural),
            "working": len(self.working_memory),
        }
        self._consolidate_episodic()
        return stats

    def get_stats(self) -> dict:
        return {
            "episodic_count": len(self.episodic),
            "semantic_count": len(self.semantic),
            "procedural_count": len(self.procedural),
            "working_count": len(self.working_memory),
            "total_memories": len(self.episodic) + len(self.semantic) + len(self.procedural),
        }

    def _retrieve_relevant(self, query: str) -> list[MemoryEntry]:
        results = self.rag.search(query, n=5)
        entries = []
        for r in results:
            entry = MemoryEntry(
                id=f"rag_{hash(r.get('content', ''))}",
                type="semantic",
                content=r.get("content", ""),
                sources=[r.get("source", "")],
            )
            entries.append(entry)
        return entries

    def _update_working_memory(self, context: str) -> list[MemoryEntry]:
        entry = MemoryEntry(
            id=f"working_{int(time.time())}",
            type="working",
            content=context,
            importance=0.7,
        )
        self.working_memory.append(entry)
        if len(self.working_memory) > self._max_working:
            self.working_memory.pop(0)
        return self.working_memory

    def _synthesize_response(self, context: str, relevant: list[MemoryEntry],
                             working: list[MemoryEntry]) -> str:
        parts = []
        if relevant:
            parts.append("From my knowledge base:")
            for entry in relevant[:3]:
                parts.append(f"- {entry.content[:200]}")
        return "\n".join(parts) if parts else ""

    def _calculate_relevance(self, entry: MemoryEntry, query: str) -> float:
        content_lower = entry.content.lower()
        words = query.split()
        matches = sum(1 for w in words if w in content_lower)
        return matches / max(len(words), 1)

    def _consolidate_episodic(self) -> None:
        if len(self.episodic) > 100:
            important = [e for e in self.episodic if e.importance > 0.7]
            recent = self.episodic[-50:]
            self.episodic = important + recent
