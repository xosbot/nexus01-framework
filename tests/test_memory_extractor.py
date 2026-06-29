"""Tests for core/memory_extractor.py."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.memory_extractor import MemoryExtractor
from core.second_brain import SOURCE_QUOTE_MAX_CHARS, SecondBrain


class MockLLM:
    """Returns a pre-canned response, or the next one in a sequence."""
    def __init__(self, responses: list[str] | str) -> None:
        self._responses = responses if isinstance(responses, list) else [responses]
        self._idx = 0
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append(messages)
        if self._idx >= len(self._responses):
            return self._responses[-1]
        out = self._responses[self._idx]
        self._idx += 1
        return out


@pytest.fixture
def brain(tmp_path: Path) -> SecondBrain:
    return SecondBrain(db_path=tmp_path / "memory.db")


def _valid_fact(content: str = "User prefers dark mode", conf: float = 0.85) -> dict[str, Any]:
    return {
        "type": "preference",
        "content": content,
        "confidence": conf,
        "importance": 0.8,
        "durability": 0.9,
        "source_quote": "I love dark mode",
    }


# ── Happy path ────────────────────────────────────────────────────────────


async def test_extract_valid_json_stores_memories(brain: SecondBrain) -> None:
    llm = MockLLM(json.dumps([_valid_fact("User prefers dark mode", 0.9),
                              _valid_fact("User works on NEXUS-01", 0.85),
                              _valid_fact("User lives in Berlin", 0.8)]))
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("Tell me about X", "Here is X", session_id="s1")
    assert len(result) == 3
    assert all(m["status"] == "active" for m in result)


async def test_extract_empty_array_is_success(brain: SecondBrain) -> None:
    llm = MockLLM("[]")
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("hi", "hello", session_id="s1")
    assert result == []


async def test_extract_markdown_fenced_json(brain: SecondBrain) -> None:
    fenced = "```json\n" + json.dumps([_valid_fact("User likes cats", 0.9)]) + "\n```"
    llm = MockLLM(fenced)
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("cats", "yes", session_id="s1")
    assert len(result) == 1
    assert result[0]["content"] == "User likes cats"


async def test_extract_json_with_prose_around_it(brain: SecondBrain) -> None:
    wrapped = f"Sure! Here's what I extracted:\n\n{json.dumps([_valid_fact('User is a developer', 0.9)])}\n\nHope that helps."
    llm = MockLLM(wrapped)
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("dev", "yes", session_id="s1")
    assert len(result) == 1


# ── Defensive ─────────────────────────────────────────────────────────────


async def test_extract_invalid_json_returns_empty(brain: SecondBrain) -> None:
    llm = MockLLM("not json at all")
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("hi", "hello", session_id="s1")
    assert result == []


async def test_extract_llm_refuses_returns_empty(brain: SecondBrain) -> None:
    llm = MockLLM("I cannot extract personal information from this conversation.")
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("hi", "hello", session_id="s1")
    assert result == []


async def test_extract_empty_response_returns_empty(brain: SecondBrain) -> None:
    llm = MockLLM("")
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("hi", "hello", session_id="s1")
    assert result == []


async def test_extract_llm_exception_returns_empty(brain: SecondBrain) -> None:
    class FailingLLM:
        async def complete(self, messages, **kw):
            raise RuntimeError("LLM down")
    ex = MemoryExtractor(FailingLLM(), brain)  # type: ignore[arg-type]
    result = await ex.extract_from_turn("hi", "hello", session_id="s1")
    assert result == []


async def test_extract_low_confidence_fact_discarded(brain: SecondBrain) -> None:
    """A fact with confidence 0.5 should be discarded by brain's gating."""
    llm = MockLLM(json.dumps([_valid_fact("User mentioned coffee", 0.5)]))
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("coffee", "yes", session_id="s1")
    assert result == []  # discarded
    # Audit row was still written
    assert any(a["op"] == "discard" for a in brain.audit_log())


async def test_extract_medium_confidence_is_pending(brain: SecondBrain) -> None:
    llm = MockLLM(json.dumps([_valid_fact("User likes tea", 0.65)]))
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("tea", "yes", session_id="s1")
    assert len(result) == 1
    assert result[0]["status"] == "pending"


async def test_extract_truncates_long_source_quote(brain: SecondBrain) -> None:
    long_quote = "x" * 500
    fact = _valid_fact("User x")
    fact["source_quote"] = long_quote
    llm = MockLLM(json.dumps([fact]))
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("x", "x", session_id="s1")
    assert len(result[0]["source_quote"]) == SOURCE_QUOTE_MAX_CHARS


async def test_extract_invalid_type_fact_skipped(brain: SecondBrain) -> None:
    bad_fact = _valid_fact("User x")
    bad_fact["type"] = "not_a_real_type"
    llm = MockLLM(json.dumps([bad_fact]))
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("x", "x", session_id="s1")
    assert result == []


async def test_extract_missing_content_fact_skipped(brain: SecondBrain) -> None:
    bad_fact = _valid_fact("")
    llm = MockLLM(json.dumps([bad_fact]))
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("x", "x", session_id="s1")
    assert result == []


async def test_extract_partial_bad_facts_keeps_good(brain: SecondBrain) -> None:
    """One valid + one bad → one stored."""
    facts = [_valid_fact("good", 0.9), {"type": "bogus", "content": "bad", "confidence": 0.9}]
    llm = MockLLM(json.dumps(facts))
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("x", "x", session_id="s1")
    assert len(result) == 1
    assert result[0]["content"] == "good"


# ── Debounce ──────────────────────────────────────────────────────────────


async def test_debounce_suppresses_rapid_calls(brain: SecondBrain) -> None:
    llm = MockLLM(json.dumps([_valid_fact("debounce test", 0.9)]))
    ex = MemoryExtractor(llm, brain)
    r1 = await ex.extract_from_turn("a", "a", session_id="sess1", debounce=True)
    r2 = await ex.extract_from_turn("b", "b", session_id="sess1", debounce=True)
    assert len(r1) == 1
    assert r2 == []  # debounced
    # LLM only called once
    assert len(llm.calls) == 1


async def test_debounce_per_session(brain: SecondBrain) -> None:
    llm = MockLLM(json.dumps([_valid_fact("x", 0.9)]))
    ex = MemoryExtractor(llm, brain)
    r1 = await ex.extract_from_turn("a", "a", session_id="sess1", debounce=True)
    r2 = await ex.extract_from_turn("b", "b", session_id="sess2", debounce=True)
    assert len(r1) == 1
    assert len(r2) == 1


async def test_debounce_disabled(brain: SecondBrain) -> None:
    llm = MockLLM(json.dumps([_valid_fact("x", 0.9)]))
    ex = MemoryExtractor(llm, brain)
    r1 = await ex.extract_from_turn("a", "a", session_id="s1", debounce=False)
    r2 = await ex.extract_from_turn("b", "b", session_id="s1", debounce=False)
    assert len(r1) == 1
    assert len(r2) == 1


# ── Conversation extraction ───────────────────────────────────────────────


async def test_extract_from_conversation_pairs(brain: SecondBrain) -> None:
    llm = MockLLM(json.dumps([_valid_fact("conv fact", 0.9)]))
    ex = MemoryExtractor(llm, brain)
    msgs = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a2"},
    ]
    result = await ex.extract_from_conversation(msgs, session_id="s1")
    # Two (u, a) pairs → two LLM calls → two memories (debounce disabled)
    assert len(result) == 2


async def test_extract_from_conversation_skips_unpaired(brain: SecondBrain) -> None:
    llm = MockLLM(json.dumps([_valid_fact("x", 0.9)]))
    ex = MemoryExtractor(llm, brain)
    msgs = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "u1"},
        # no assistant reply
    ]
    result = await ex.extract_from_conversation(msgs, session_id="s1")
    assert result == []


# ── Edge cases ────────────────────────────────────────────────────────────


async def test_extract_empty_user_message_returns_empty(brain: SecondBrain) -> None:
    llm = MockLLM(json.dumps([_valid_fact()]))
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("", "hello", session_id="s1")
    assert result == []
    assert len(llm.calls) == 0


async def test_extract_clamps_confidence_to_valid_range(brain: SecondBrain) -> None:
    """If LLM sends confidence > 1, brain clamps to 1.0."""
    fact = _valid_fact("clamp", conf=1.5)
    llm = MockLLM(json.dumps([fact]))
    ex = MemoryExtractor(llm, brain)
    result = await ex.extract_from_turn("x", "x", session_id="s1")
    assert result[0]["confidence"] == 1.0
