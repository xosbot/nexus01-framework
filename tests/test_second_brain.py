"""Tests for core/second_brain.py.

Each test uses a fresh in-memory or temp-file SQLite database to avoid cross-test pollution.
External concurrency is verified by spinning 10 concurrent add tasks against a shared file.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from core.second_brain import (
    DECAY_DAYS,
    SOURCE_QUOTE_MAX_CHARS,
    SecondBrain,
)


@pytest.fixture
def brain(tmp_path: Path) -> SecondBrain:
    db = tmp_path / "memory.db"
    b = SecondBrain(db_path=db)
    return b


# ── add_memory: confidence gating ─────────────────────────────────────────


def test_add_high_confidence_is_active(brain: SecondBrain) -> None:
    m = brain.add_memory(
        type="preference", content="User prefers dark mode",
        confidence=0.9, importance=0.8, durability=0.9,
        source_session_id="s1", source_quote="I love dark mode",
    )
    assert m["status"] == "active"
    assert m["confidence"] == 0.9
    assert m["content"] == "User prefers dark mode"
    assert m["id"].startswith("mem_")


def test_add_medium_confidence_is_pending(brain: SecondBrain) -> None:
    m = brain.add_memory(
        type="identity", content="User lives in Berlin",
        confidence=0.65, importance=0.5, durability=0.7,
        source_session_id="s1", source_quote="I'm in Berlin",
    )
    assert m["status"] == "pending"


def test_add_low_confidence_is_discarded(brain: SecondBrain) -> None:
    m = brain.add_memory(
        type="identity", content="User mentioned coffee",
        confidence=0.4, importance=0.3, durability=0.3,
        source_session_id="s1", source_quote="coffee is okay",
    )
    assert m["status"] == "discarded"
    # No row in DB
    assert brain.list_memories(status="pending") == []
    assert brain.list_memories(status="active") == []
    # Audit row was still recorded
    audit = brain.audit_log()
    assert any(a["op"] == "discard" for a in audit)


def test_add_validates_type(brain: SecondBrain) -> None:
    with pytest.raises(ValueError, match="invalid memory type"):
        brain.add_memory(
            type="bogus", content="x", confidence=0.9,
            importance=0.5, durability=0.5,
        )


def test_add_validates_content_not_empty(brain: SecondBrain) -> None:
    with pytest.raises(ValueError, match="content cannot be empty"):
        brain.add_memory(
            type="identity", content="   ", confidence=0.9,
            importance=0.5, durability=0.5,
        )


def test_add_clamps_confidence(brain: SecondBrain) -> None:
    m = brain.add_memory(
        type="preference", content="clamp test", confidence=1.5,
        importance=0.5, durability=0.5,
    )
    assert m["confidence"] == 1.0
    m = brain.add_memory(
        type="preference", content="clamp test 2", confidence=-0.5,
        importance=0.5, durability=0.5,
    )
    assert m["status"] == "discarded"


def test_add_truncates_source_quote(brain: SecondBrain) -> None:
    long_quote = "x" * 500
    m = brain.add_memory(
        type="identity", content="long quote test", confidence=0.9,
        importance=0.5, durability=0.5, source_quote=long_quote,
    )
    assert len(m["source_quote"]) == SOURCE_QUOTE_MAX_CHARS


# ── list_memories / list_pending ───────────────────────────────────────────


def test_list_filters_by_status_and_type(brain: SecondBrain) -> None:
    brain.add_memory(type="preference", content="p1", confidence=0.9, importance=0.5, durability=0.5)
    brain.add_memory(type="preference", content="p2", confidence=0.65, importance=0.5, durability=0.5)
    brain.add_memory(type="identity", content="i1", confidence=0.9, importance=0.5, durability=0.5)

    actives = brain.list_memories(status="active")
    assert len(actives) == 2
    assert all(m["status"] == "active" for m in actives)

    pendings = brain.list_pending()
    assert len(pendings) == 1
    assert pendings[0]["status"] == "pending"

    prefs = brain.list_memories(status="active", type="preference")
    assert len(prefs) == 1
    assert prefs[0]["type"] == "preference"


def test_list_orders_by_confidence_desc(brain: SecondBrain) -> None:
    brain.add_memory(type="preference", content="low", confidence=0.75, importance=0.5, durability=0.5)
    brain.add_memory(type="preference", content="high", confidence=0.95, importance=0.5, durability=0.5)
    rows = brain.list_memories(status="active", type="preference")
    assert rows[0]["content"] == "high"
    assert rows[1]["content"] == "low"


# ── update / delete / approve / reject / pin ──────────────────────────────


def test_update_memory(brain: SecondBrain) -> None:
    m = brain.add_memory(type="preference", content="orig", confidence=0.9,
                        importance=0.5, durability=0.5)
    updated = brain.update_memory(m["id"], importance=0.99)
    assert updated["importance"] == 0.99


def test_update_memory_validates_type(brain: SecondBrain) -> None:
    m = brain.add_memory(type="preference", content="x", confidence=0.9,
                        importance=0.5, durability=0.5)
    with pytest.raises(ValueError, match="invalid memory type"):
        brain.update_memory(m["id"], type="bogus")


def test_update_memory_missing_raises(brain: SecondBrain) -> None:
    with pytest.raises(KeyError):
        brain.update_memory("mem_nonexistent", importance=0.5)


def test_delete_memory_audited(brain: SecondBrain) -> None:
    m = brain.add_memory(type="preference", content="bye", confidence=0.9,
                        importance=0.5, durability=0.5)
    assert brain.delete_memory(m["id"]) is True
    assert brain.get(m["id"]) is None
    audit = brain.audit_log(memory_id=m["id"])
    assert any(a["op"] == "delete" for a in audit)


def test_delete_memory_missing_returns_false(brain: SecondBrain) -> None:
    assert brain.delete_memory("mem_doesnotexist") is False


def test_approve_pending_makes_active(brain: SecondBrain) -> None:
    m = brain.add_memory(type="preference", content="pending", confidence=0.65,
                        importance=0.5, durability=0.5)
    assert m["status"] == "pending"
    a = brain.approve_memory(m["id"])
    assert a["status"] == "active"


def test_approve_active_raises(brain: SecondBrain) -> None:
    m = brain.add_memory(type="preference", content="already active", confidence=0.9,
                        importance=0.5, durability=0.5)
    with pytest.raises(ValueError, match="not pending"):
        brain.approve_memory(m["id"])


def test_reject_pending(brain: SecondBrain) -> None:
    m = brain.add_memory(type="preference", content="reject me", confidence=0.65,
                        importance=0.5, durability=0.5)
    r = brain.reject_memory(m["id"])
    assert r["status"] == "rejected"
    assert brain.list_memories(status="rejected")[0]["id"] == m["id"]


def test_pin_memory_toggles_pinned(brain: SecondBrain) -> None:
    m = brain.add_memory(type="preference", content="pin me", confidence=0.9,
                        importance=0.1, durability=0.5)
    assert m["pinned"] == 0
    p = brain.pin_memory(m["id"], pinned=True)
    assert p["pinned"] == 1
    p2 = brain.pin_memory(m["id"], pinned=False)
    assert p2["pinned"] == 0


# ── FTS5 search & recall ──────────────────────────────────────────────────


def test_search_finds_by_keyword(brain: SecondBrain) -> None:
    brain.add_memory(type="project", content="Building NEXUS-01 framework",
                    confidence=0.9, importance=0.9, durability=0.9)
    brain.add_memory(type="preference", content="Likes dark mode in editors",
                    confidence=0.9, importance=0.5, durability=0.9)

    hits = brain.search("NEXUS-01")
    assert len(hits) >= 1
    assert "NEXUS-01" in hits[0]["content"]


def test_search_handles_special_chars(brain: SecondBrain) -> None:
    brain.add_memory(type="identity", content='User said "hello world" today',
                    confidence=0.9, importance=0.5, durability=0.5)
    # Quotes in query should not crash
    hits = brain.search('"hello world"')
    assert len(hits) >= 1


def test_search_empty_query_returns_empty(brain: SecondBrain) -> None:
    brain.add_memory(type="identity", content="x", confidence=0.9, importance=0.5, durability=0.5)
    assert brain.search("") == []


def test_recall_filters_active_and_confidence(brain: SecondBrain) -> None:
    brain.add_memory(type="project", content="Working on NEXUS-01", confidence=0.95,
                    importance=0.9, durability=0.9)  # active
    brain.add_memory(type="project", content="NEXUS-01 has a memory feature", confidence=0.65,
                    importance=0.5, durability=0.5)  # pending
    brain.add_memory(type="project", content="NEXUS-01 architecture", confidence=0.5,
                    importance=0.3, durability=0.3)  # discarded

    recalled = brain.recall_for_context("NEXUS-01", n=5, min_confidence=0.7)
    assert len(recalled) == 1
    assert recalled[0]["confidence"] >= 0.7


def test_recall_bumps_access_count(brain: SecondBrain) -> None:
    m = brain.add_memory(type="project", content="NEXUS-01 phase 1", confidence=0.9,
                        importance=0.9, durability=0.9)
    assert m["access_count"] == 0
    recalled = brain.recall_for_context("NEXUS-01", n=5)
    assert recalled[0]["access_count"] >= 1
    # last_referenced should be set
    assert recalled[0]["last_referenced"] is not None


# ── Conflict resolution ──────────────────────────────────────────────────


def test_conflict_both_high_new_wins(brain: SecondBrain) -> None:
    old = brain.add_memory(
        type="preference", content="User prefers dark mode for all editors",
        confidence=0.9, importance=0.8, durability=0.9,
    )
    new = brain.add_memory(
        type="preference", content="User prefers dark mode for all editors",
        confidence=0.95, importance=0.9, durability=0.9,
    )
    # New wins, old archived
    assert new["id"] != old["id"]
    assert brain.get(old["id"])["status"] == "archived"
    assert brain.get(new["id"])["status"] == "active"
    audit = brain.audit_log(memory_id=old["id"])
    assert any(a["op"] == "archive" and "superseded" in (a.get("note") or "") for a in audit)


def test_conflict_old_high_new_low_keeps_old(brain: SecondBrain) -> None:
    old = brain.add_memory(
        type="preference", content="User prefers dark mode for all editors",
        confidence=0.95, importance=0.9, durability=0.9,
    )
    result = brain.add_memory(
        type="preference", content="User prefers dark mode for all editors",  # same content
        confidence=0.65, importance=0.5, durability=0.5,
    )
    # New discarded, old stays
    assert result["status"] == "discarded"
    assert brain.get(old["id"])["status"] == "active"


def test_conflict_both_pending_keeps_older(brain: SecondBrain) -> None:
    old = brain.add_memory(
        type="identity", content="User works at a startup in Berlin",
        confidence=0.65, importance=0.5, durability=0.5,
    )
    result = brain.add_memory(
        type="identity", content="User works at a startup in Berlin",  # same
        confidence=0.62, importance=0.5, durability=0.5,
    )
    assert result["status"] == "discarded"
    # Older pending survives
    assert brain.get(old["id"])["status"] == "pending"


def test_short_content_skips_conflict_scan(brain: SecondBrain) -> None:
    # Content < CONFLICT_SUBSTRING_MIN_LEN (12) is not scanned
    brain.add_memory(type="identity", content="hi", confidence=0.9, importance=0.5, durability=0.5)
    result = brain.add_memory(type="identity", content="hi", confidence=0.9, importance=0.5, durability=0.5)
    # Both stored because no conflict scan
    assert result["status"] == "active"


# ── Decay ─────────────────────────────────────────────────────────────────


def test_decay_archives_old_low_importance(brain: SecondBrain) -> None:
    """A memory created >21d ago with low importance + no references should be archived."""
    mid = "mem_test_old"
    old_ts = time.time() - (DECAY_DAYS + 5) * 86400
    # Insert directly to control created_at
    with brain._conn() as c:
        c.execute(
            """INSERT INTO memories
               (id, type, content, confidence, importance, durability,
                source_session_id, source_quote, status, pinned,
                created_at, last_referenced, access_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (mid, "preference", "old low imp", 0.9, 0.05, 0.5,
             "s1", "", "active", 0, old_ts, None, 0),
        )
    archived = brain.run_decay()
    assert archived == 1
    assert brain.get(mid)["status"] == "archived"


def test_decay_preserves_pinned(brain: SecondBrain) -> None:
    mid = "mem_pinned"
    old_ts = time.time() - (DECAY_DAYS + 5) * 86400
    with brain._conn() as c:
        c.execute(
            """INSERT INTO memories
               (id, type, content, confidence, importance, durability,
                source_session_id, source_quote, status, pinned,
                created_at, last_referenced, access_count)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (mid, "preference", "pinned low", 0.9, 0.05, 0.5,
             "s1", "", "active", 1, old_ts, None, 0),
        )
    archived = brain.run_decay()
    assert archived == 0
    assert brain.get(mid)["status"] == "active"


def test_decay_skips_recent(brain: SecondBrain) -> None:
    """Recent memories are not archived regardless of importance."""
    m = brain.add_memory(type="preference", content="recent low", confidence=0.9,
                        importance=0.05, durability=0.5)
    archived = brain.run_decay()
    assert archived == 0
    assert brain.get(m["id"])["status"] == "active"


# ── Core blocks ───────────────────────────────────────────────────────────


def test_core_blocks_crud(brain: SecondBrain) -> None:
    assert brain.get_core_blocks() == {}

    brain.set_core_block("user", "I am a developer")
    assert brain.get_core_block("user") == "I am a developer"
    assert brain.get_core_blocks() == {"user": "I am a developer"}

    brain.set_core_block("persona", "Friendly assistant")
    blocks = brain.get_core_blocks()
    assert blocks == {"user": "I am a developer", "persona": "Friendly assistant"}

    # Version increments on update
    with brain._conn() as c:
        v1 = c.execute("SELECT version FROM core_blocks WHERE label='user'").fetchone()
    brain.set_core_block("user", "Updated")
    with brain._conn() as c:
        v2 = c.execute("SELECT version FROM core_blocks WHERE label='user'").fetchone()
    assert v2["version"] == v1["version"] + 1


def test_core_block_validates_label(brain: SecondBrain) -> None:
    with pytest.raises(ValueError, match="invalid core block label"):
        brain.set_core_block("bogus", "x")


def test_core_block_truncates_to_max(brain: SecondBrain) -> None:
    long_val = "x" * 5000
    brain.set_core_block("user", long_val)
    stored = brain.get_core_block("user")
    assert len(stored) == 2000


# ── Audit log ─────────────────────────────────────────────────────────────


def test_audit_log_captures_every_op(brain: SecondBrain) -> None:
    m = brain.add_memory(type="preference", content="audit me", confidence=0.9,
                        importance=0.5, durability=0.5)
    brain.update_memory(m["id"], importance=0.8)
    brain.delete_memory(m["id"])
    audit = brain.audit_log()
    ops = {a["op"] for a in audit}
    assert "add" in ops
    assert "update" in ops
    assert "delete" in ops


def test_audit_log_filters_by_memory(brain: SecondBrain) -> None:
    m1 = brain.add_memory(type="preference", content="a", confidence=0.9,
                         importance=0.5, durability=0.5)
    m2 = brain.add_memory(type="preference", content="b", confidence=0.9,
                         importance=0.5, durability=0.5)
    brain.delete_memory(m1["id"])
    only_m2 = brain.audit_log(memory_id=m2["id"])
    assert all(a["memory_id"] == m2["id"] for a in only_m2)
    assert len(only_m2) >= 1


# ── Stats ─────────────────────────────────────────────────────────────────


def test_stats_aggregates(brain: SecondBrain) -> None:
    # a: pref, 0.9 → active; b: pref, 0.65 → pending; c: identity, 0.5 → discarded; d: identity, 0.4 → discarded
    brain.add_memory(type="preference", content="a", confidence=0.9, importance=0.5, durability=0.5)
    brain.add_memory(type="preference", content="b", confidence=0.65, importance=0.5, durability=0.5)
    brain.add_memory(type="identity", content="c", confidence=0.5, importance=0.5, durability=0.5)
    brain.add_memory(type="identity", content="d", confidence=0.4, importance=0.5, durability=0.5)
    s = brain.stats()
    assert s["total"] == 2  # only stored memories (c and d were discarded)
    assert s["by_type"]["preference"] == 2
    assert s["by_type"].get("identity", 0) == 0
    assert s["by_confidence_bucket"]["active_>=0.7"] == 1
    assert s["by_confidence_bucket"]["pending_0.6-0.7"] == 1
    assert s["by_confidence_bucket"]["low_<0.6"] == 0  # discarded not counted
    assert s["pending"] == 1


# ── Concurrency ───────────────────────────────────────────────────────────


def test_concurrent_adds_dont_busy_error(tmp_path: Path) -> None:
    """WAL + busy_timeout should let 10 threads write concurrently without SQLITE_BUSY."""
    db = tmp_path / "concurrent.db"
    brain = SecondBrain(db_path=db)
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            brain.add_memory(
                type="identity", content=f"concurrent worker {i}",
                confidence=0.9, importance=0.5, durability=0.5,
                source_session_id=f"s{i}", source_quote=f"q{i}",
            )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"concurrent writes failed: {errors}"
    assert len(brain.list_memories(status="active")) == 10


# ── Audit retention ────────────────────────────────────────────────────


def test_prune_audit_deletes_old_rows_keeps_new(tmp_path: Path) -> None:
    """prune_audit(days) should drop rows older than the cutoff and keep newer ones."""
    import time
    from core.second_brain import AUDIT_RETENTION_DAYS

    db = tmp_path / "audit_prune.db"
    brain = SecondBrain(db_path=db)

    # Add one memory to generate real audit rows via the proper API
    mem = brain.add_memory(
        type="identity", content="auditable fact",
        confidence=0.9, importance=0.5, durability=0.5,
        source_session_id="s", source_quote="q",
    )

    # Manually backdate 100 audit rows to be very old, plus 100 fresh ones
    very_old_ts = time.time() - (AUDIT_RETENTION_DAYS + 30) * 86400
    with brain._conn() as c:
        for _ in range(100):
            c.execute(
                "INSERT INTO memory_audit (ts, memory_id, op, actor, session_id, note) "
                "VALUES (?, ?, 'synthetic', 'test', 's', 'old')",
                (very_old_ts, mem["id"]),
            )
        for _ in range(100):
            c.execute(
                "INSERT INTO memory_audit (ts, memory_id, op, actor, session_id, note) "
                "VALUES (?, ?, 'synthetic', 'test', 's', 'new')",
                (time.time(), mem["id"]),
            )

    pre = brain.audit_log(limit=1000)
    assert len(pre) >= 200  # 100 old + 100 new (plus add_memory's own rows)

    deleted = brain.prune_audit()
    assert deleted == 100, f"expected 100 old rows pruned, got {deleted}"

    post = brain.audit_log(limit=1000)
    # No row should have a note of 'old' anymore
    assert not any(r.get("note") == "old" for r in post)
    # All remaining rows have note 'new' or are from add_memory's own audit
    notes = {r.get("note") for r in post}
    assert "old" not in notes


def test_prune_audit_with_no_old_rows_is_noop(tmp_path: Path) -> None:
    """prune_audit() on a fresh DB returns 0 and does nothing harmful."""
    db = tmp_path / "fresh.db"
    brain = SecondBrain(db_path=db)
    deleted = brain.prune_audit()
    assert deleted == 0


def test_run_decay_triggers_prune_audit_opportunistically(tmp_path: Path) -> None:
    """run_decay() should call prune_audit() at the end (opportunistic retention)."""
    import time
    db = tmp_path / "decay_prune.db"
    brain = SecondBrain(db_path=db)

    # Insert a very old synthetic audit row
    very_old_ts = time.time() - (365 * 86400)  # 1 year old
    with brain._conn() as c:
        c.execute(
            "INSERT INTO memory_audit (ts, memory_id, op, actor, session_id, note) "
            "VALUES (?, NULL, 'synthetic', 'test', 's', 'very old')",
            (very_old_ts,),
        )

    # run_decay() will see no memories to decay but should still prune audit
    brain.run_decay()
    post = brain.audit_log(limit=1000)
    assert not any(r.get("note") == "very old" for r in post)
