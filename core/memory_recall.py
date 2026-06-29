"""Memory recall — pre-prompt memory injection and compact summaries.

This module is a thin wrapper around SecondBrain that:
  1. Recalls memories relevant to a query (FTS5 + confidence filter, via brain)
  2. Formats the recalled list as a system-prompt context block (budget-aware)
  3. Produces compact one-line summaries for the /memory slash command

This is a built-in pre-prompt step that runs on every chat turn, before the
message hits the LLM. It is NOT exposed as a callable tool — the LLM never
chooses whether to recall. (Buildplan §1.5, B.5.)
"""
from __future__ import annotations

import logging
from typing import Any

from core.second_brain import SecondBrain

logger = logging.getLogger(__name__)

DEFAULT_BUDGET_CHARS = 900
HEADER = "## Relevant memories"


class MemoryRecall:
    """Wraps SecondBrain to provide recall + formatting for chat injection."""

    def __init__(self, brain: SecondBrain) -> None:
        self._brain = brain

    def recall(
        self, query: str, n: int = 5, min_confidence: float = 0.7,
    ) -> list[dict]:
        """Return up to n active memories matching the query, confidence >= min_confidence."""
        return self._brain.recall_for_context(query, n=n, min_confidence=min_confidence)

    def format_for_context(
        self, memories: list[dict], budget_chars: int = DEFAULT_BUDGET_CHARS,
    ) -> str:
        """Format a list of memories as a context block to inject into the system prompt.

        If empty, returns empty string. Otherwise returns a header + bullet list,
        truncated to fit within budget_chars (drops trailing memories if needed).
        """
        if not memories:
            return ""
        lines = [f"{HEADER} ({len(memories)})"]
        used = len(lines[0])
        for m in memories:
            line = self._format_line(m)
            # +1 for the newline
            if used + len(line) + 1 > budget_chars:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    def format_compact(
        self, n_active: int | None = None, n_pending: int | None = None,
        by_type: dict[str, int] | None = None,
    ) -> str:
        """One-line summary for the /memory slash command and Memory admin tab.

        If n_active/n_pending/by_type are not provided, queries the brain.
        """
        if n_active is None or n_pending is None or by_type is None:
            stats = self._brain.stats()
            n_active = n_active if n_active is not None else stats["total"] - stats.get("pending", 0)
            n_pending = n_pending if n_pending is not None else stats.get("pending", 0)
            by_type = by_type if by_type is not None else stats.get("by_type", {})
        if not by_type:
            return f"{n_active} active memories, {n_pending} pending review"
        type_str = ", ".join(f"{count} {t}" for t, count in sorted(by_type.items(), key=lambda x: -x[1]))
        return f"{n_active} active memories, {n_pending} pending ({type_str})"

    @staticmethod
    def _format_line(memory: dict[str, Any]) -> str:
        mtype = memory.get("type", "memory")
        content = (memory.get("content") or "").strip()
        conf = memory.get("confidence", 0)
        # Truncate very long content to keep the block tight
        if len(content) > 200:
            content = content[:197] + "..."
        return f"- [{mtype}, conf {conf:.2f}] {content}"
