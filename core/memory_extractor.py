"""LLM-based fact extraction for the second brain.

After each chat turn, this module:
  1. Sends (user_msg, assistant_msg) to a cheap-tier LLM with a strict JSON-only prompt
  2. Parses the response (defensively — handles markdown fences, plain text JSON, refusals)
  3. Clamps confidence/importance/durability to [0, 1]
  4. Truncates source_quote to 200 chars
  5. Calls SecondBrain.add_memory for each fact (brain handles confidence gating)

Defensive measures:
  - JSON parse failure → log, return [] (no storage, no audit pollution)
  - LLM refusal / empty / non-JSON → return [] gracefully
  - Missing fields → skip that fact, continue with others
  - Invalid type → skip, log warning
  - All facts go through the same add_memory path so confidence gating is uniform

Called from: api/server.py chat_stream (fire-and-forget, debounced 30s per session)
Also called from: core/dreamer.py (Phase 3, background re-extraction)
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Protocol

from core.second_brain import SOURCE_QUOTE_MAX_CHARS, SecondBrain

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 30.0

# Control chars: C0 (\x00-\x1f) except whitespace \t\n\r, plus C1 (\x80-\x9f).
# These can be smuggled into a quote by a hostile or buggy LLM and break the
# admin UI (or smuggle ANSI escape sequences into a terminal viewer).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# ANSI CSI escape: ESC [ ... letter (parameter range 0x30-0x3f, intermediate
# 0x20-0x2f, final 0x40-0x7e). This regex matches the common form.
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _sanitize_source_quote(raw: str) -> str:
    """Strip control chars + ANSI escapes, normalize whitespace, cap length.

    Defense in depth: source_quote is stored verbatim from the LLM output.
    A prompt-injection scenario or a buggy LLM could embed C0/C1 control
    chars, terminal escape sequences, or other invisible text. We strip
    those before storage so the admin UI and audit log render cleanly.

    Preserves \n, \r, \t (legitimate whitespace). Strips everything else
    in C0/C1, plus full ANSI CSI sequences (ESC [ ... letter).
    """
    if not raw:
        return ""
    cleaned = _ANSI_CSI_RE.sub("", raw)
    cleaned = _CONTROL_CHARS_RE.sub("", cleaned)
    # Collapse runs of spaces (NOT tabs — tabs are meaningful in a quote)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()[:SOURCE_QUOTE_MAX_CHARS]

_EXTRACTION_PROMPT = """You are a memory curator for an AI assistant. Given the
following conversation turn, extract 0-3 facts that would be useful to remember
about the user in future conversations.

For each fact, output a JSON object with:
- type: one of identity|preference|goal|project|habit|decision|constraint|relationship|episode|reflection
- content: a short, self-contained statement of the fact (one sentence)
- confidence: 0.0-1.0 — how sure are you this is a real fact, not a passing remark?
  - 0.6+ only if the user explicitly stated it
  - 0.8+ only if it's clearly important and likely to persist
- importance: 0.0-1.0 — how important is this to remember?
- durability: 0.0-1.0 — how stable is this fact over time? (preferences > passing moods)
- source_quote: the exact sentence from the conversation that justifies this fact

Output a JSON array. Empty array if nothing worth remembering.
Output ONLY valid JSON, no commentary, no markdown fences.

Conversation:
USER: {user_msg}
ASSISTANT: {assistant_msg}
"""


class LLMProtocol(Protocol):
    """Anything with an async complete() method that returns a string."""
    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...


class MemoryExtractor:
    """Extracts structured memories from chat turns via the LLM."""

    def __init__(self, llm: LLMProtocol, brain: SecondBrain) -> None:
        self._llm = llm
        self._brain = brain
        self._last_extraction_ts: dict[str, float] = {}  # session_id → ts

    async def extract_from_turn(
        self, user_msg: str, assistant_msg: str, session_id: str = "",
        *, debounce: bool = True, user_id: str = "user_legacy",
    ) -> list[dict]:
        """Extract memories from a single turn. Returns list of stored memory dicts.

        If `debounce=True` and the same session_id was extracted within
        _DEBOUNCE_SECONDS, returns [] without calling the LLM.
        """
        if debounce and session_id:
            now = time.time()
            last = self._last_extraction_ts.get(session_id, 0)
            if now - last < _DEBOUNCE_SECONDS:
                return []
            self._last_extraction_ts[session_id] = now

        if not (user_msg and user_msg.strip()):
            return []

        prompt = _EXTRACTION_PROMPT.format(
            user_msg=user_msg.strip()[:2000],
            assistant_msg=(assistant_msg or "").strip()[:2000],
        )
        messages = [
            {"role": "system", "content": "You are a precise memory curator. Output only valid JSON."},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = await self._llm.complete(messages, agent="memory_extractor")
        except Exception as exc:
            logger.warning("[memory_extractor] LLM call failed: %s", exc)
            return []

        facts = self._parse_facts(raw)
        stored: list[dict] = []
        for fact in facts:
            memory = self._store_fact(fact, session_id, user_id=user_id)
            if memory is None:
                continue
            status = memory.get("status", "")
            if status in {"discarded", "rejected"}:
                continue
            stored.append(memory)
        return stored

    async def extract_from_conversation(
        self, messages: list[dict[str, str]], session_id: str = "",
        *, user_id: str = "user_legacy",
    ) -> list[dict]:
        """Extract from a full conversation. Splits into (user, assistant) pairs.

        Useful for the dreamer in Phase 3.
        """
        stored: list[dict] = []
        i = 0
        while i < len(messages) - 1:
            if messages[i].get("role") == "user" and messages[i + 1].get("role") == "assistant":
                turn_memories = await self.extract_from_turn(
                    messages[i]["content"],
                    messages[i + 1]["content"],
                    session_id=session_id,
                    debounce=False,
                    user_id=user_id,
                )
                stored.extend(turn_memories)
                i += 2
            else:
                i += 1
        return stored

    # ── Parsing ──────────────────────────────────────────────────────────

    def _parse_facts(self, raw: str) -> list[dict]:
        """Parse the LLM's response into a list of fact dicts.

        Handles: plain JSON array, JSON wrapped in markdown fences, JSON with
        leading/trailing prose, malformed JSON (returns []).
        """
        if not raw or not raw.strip():
            return []
        text = raw.strip()

        # Strip markdown code fences: ```json ... ``` or ``` ... ```
        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

        # Find the first JSON array in the text
        bracket_start = text.find("[")
        bracket_end = text.rfind("]")
        if bracket_start == -1 or bracket_end == -1 or bracket_end <= bracket_start:
            logger.debug("[memory_extractor] no JSON array in response: %r", raw[:200])
            return []

        candidate = text[bracket_start:bracket_end + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            logger.warning("[memory_extractor] JSON parse failed: %s; raw=%r", exc, raw[:200])
            return []

        if not isinstance(parsed, list):
            return []
        return [f for f in parsed if isinstance(f, dict)]

    def _store_fact(self, fact: dict, session_id: str, *, user_id: str = "user_legacy") -> dict | None:
        """Validate and persist a single fact. Returns the memory dict or None."""
        try:
            content = str(fact.get("content", "")).strip()
            if not content:
                return None
            mtype = str(fact.get("type", "")).strip()
            quote = _sanitize_source_quote(str(fact.get("source_quote", "")))
            confidence = float(fact.get("confidence", 0))
            importance = float(fact.get("importance", 0.5))
            durability = float(fact.get("durability", 0.5))
        except (TypeError, ValueError) as exc:
            logger.warning("[memory_extractor] bad fact shape: %s; fact=%r", exc, fact)
            return None

        try:
            return self._brain.add_memory(
                type=mtype,
                content=content,
                confidence=confidence,
                importance=importance,
                durability=durability,
                source_session_id=session_id,
                source_quote=quote,
                user_id=user_id,
            )
        except ValueError as exc:
            # Invalid type or empty content — skip silently
            logger.debug("[memory_extractor] rejected fact: %s", exc)
            return None
