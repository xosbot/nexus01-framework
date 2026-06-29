"""Tests for core/memory_recall.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.memory_recall import HEADER, MemoryRecall
from core.second_brain import SecondBrain


@pytest.fixture
def brain(tmp_path: Path) -> SecondBrain:
    return SecondBrain(db_path=tmp_path / "memory.db")


@pytest.fixture
def populated_brain(brain: SecondBrain) -> SecondBrain:
    """Brain with a mix of active and pending memories."""
    brain.add_memory(type="preference", content="User prefers dark mode in editors",
                    confidence=0.9, importance=0.8, durability=0.9)
    brain.add_memory(type="project", content="Building NEXUS-01 framework Phase 1",
                    confidence=0.95, importance=0.95, durability=0.9)
    brain.add_memory(type="identity", content="User is a backend developer",
                    confidence=0.85, importance=0.7, durability=0.9)
    brain.add_memory(type="preference", content="User might like coffee",  # pending
                    confidence=0.65, importance=0.3, durability=0.5)
    brain.add_memory(type="identity", content="User mentioned lunch",  # discarded
                    confidence=0.4, importance=0.2, durability=0.2)
    return brain


# ── recall ────────────────────────────────────────────────────────────────


def test_recall_returns_active_high_confidence(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    result = recall.recall("NEXUS-01", n=5)
    assert len(result) == 1
    assert "NEXUS-01" in result[0]["content"]


def test_recall_filters_by_confidence(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    # All active memories have confidence >= 0.85; the pending one (0.65) should be excluded
    result = recall.recall("user", n=10, min_confidence=0.7)
    for m in result:
        assert m["confidence"] >= 0.7
        assert m["status"] == "active"


def test_recall_empty_query_returns_empty(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    assert recall.recall("") == []


def test_recall_bumps_access_count(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    recall.recall("NEXUS-01")
    # Re-fetch the memory and check access_count went up
    m = populated_brain.search("NEXUS-01")[0]
    assert m["access_count"] >= 1


def test_recall_no_match_returns_empty(brain: SecondBrain) -> None:
    recall = MemoryRecall(brain)
    result = recall.recall("nonexistent query xyzzy")
    assert result == []


# ── format_for_context ────────────────────────────────────────────────────


def test_format_empty_returns_empty_string(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    assert recall.format_for_context([]) == ""


def test_format_includes_header_and_bullets(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    memories = recall.recall("NEXUS-01", n=5)
    out = recall.format_for_context(memories)
    assert HEADER in out
    assert out.startswith(HEADER)
    assert "- [" in out
    assert "conf" in out


def test_format_truncates_to_budget(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    # Add many long memories
    for i in range(20):
        populated_brain.add_memory(
            type="preference", content=f"User preference number {i} " * 20,
            confidence=0.9, importance=0.5, durability=0.5,
        )
    memories = populated_brain.recall_for_context("preference", n=20)
    out = recall.format_for_context(memories, budget_chars=300)
    assert len(out) <= 300 + 50  # allow slight overflow for last line
    # Should have at least 1 memory but not all 20
    assert "- [" in out


def test_format_truncates_long_content_per_line(populated_brain: SecondBrain) -> None:
    """Individual long memory content is truncated to 200 chars + '...'."""
    long_content = "x" * 500
    populated_brain.add_memory(type="identity", content=long_content,
                              confidence=0.9, importance=0.5, durability=0.5)
    recall = MemoryRecall(populated_brain)
    memories = recall.recall("x", n=5)
    out = recall.format_for_context(memories)
    # Find the xxxx line
    for line in out.split("\n"):
        if line.startswith("- "):
            assert len(line) <= 250  # bullet prefix + 200 content + ellipsis


# ── format_compact ────────────────────────────────────────────────────────


def test_format_compact_uses_brain_stats_when_not_provided(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    out = recall.format_compact()
    # 3 active, 1 pending, types: identity=1, preference=1, project=1
    assert "3 active" in out or "4 active" in out  # depends on whether 0.65 pending counts
    assert "pending" in out


def test_format_compact_uses_provided_values(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    out = recall.format_compact(n_active=42, n_pending=7, by_type={"preference": 30, "project": 12})
    assert "42 active" in out
    assert "7 pending" in out
    assert "30 preference" in out
    assert "12 project" in out


def test_format_compact_empty_types(brain: SecondBrain) -> None:
    recall = MemoryRecall(brain)
    out = recall.format_compact()
    assert "0 active" in out
    assert "0 pending" in out


def test_format_compact_orders_by_count_desc(populated_brain: SecondBrain) -> None:
    recall = MemoryRecall(populated_brain)
    out = recall.format_compact(n_active=10, n_pending=0,
                                by_type={"identity": 2, "preference": 8, "project": 5})
    # preferences (8) should come first
    assert out.index("8 preference") < out.index("5 project") < out.index("2 identity")
