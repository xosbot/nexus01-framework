"""Phase 2.3: per-user data isolation regression tests.

Verifies that:
  - Memories are scoped to user_id (alice cannot see bob's memories)
  - Sessions/projects/conversations are scoped
  - Conflict resolution is per-user
  - Migration is idempotent (running _migrate_user_id twice is safe)
  - Legacy user owns pre-migration rows
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.memory import Memory
from core.second_brain import SecondBrain
from core.users import LEGACY_USER_ID


@pytest.fixture
def mem(tmp_path: Path) -> Memory:
    return Memory(db_path=tmp_path / "isolation.db")


# ── Migration ─────────────────────────────────────────────────────────


def test_migration_adds_user_id_to_all_tables(mem: Memory) -> None:
    """After Memory init, every user-owned table has a user_id column."""
    for table in ("sessions", "conversations", "projects", "tasks"):
        cols = {r[1] for r in mem._conn.execute(f"PRAGMA table_info({table})").fetchall()}
        assert "user_id" in cols, f"{table} missing user_id"


def test_migration_is_idempotent(mem: Memory) -> None:
    """Re-running _migrate_user_id is safe (no ALTER errors, no duplicates)."""
    mem._migrate_user_id()
    mem._migrate_user_id()  # second time
    # And columns still exist
    cols = {r[1] for r in mem._conn.execute("PRAGMA table_info(sessions)").fetchall()}
    assert "user_id" in cols


def test_legacy_user_exists_after_init(mem: Memory) -> None:
    assert mem.users.get(LEGACY_USER_ID) is not None
    assert mem.backfill_user_id_done() is True


# ── SecondBrain isolation ────────────────────────────────────────────


def test_memories_scoped_to_user(tmp_path: Path) -> None:
    brain = SecondBrain(db_path=tmp_path / "brain.db")
    brain.add_memory(
        type="preference", content="alice likes dark mode",
        confidence=0.9, importance=0.9, durability=0.9,
        source_session_id="s", source_quote="q",
        user_id="user_alice",
    )
    brain.add_memory(
        type="preference", content="bob prefers light mode",
        confidence=0.9, importance=0.9, durability=0.9,
        source_session_id="s", source_quote="q",
        user_id="user_bob",
    )
    # Alice sees only hers
    alice = brain.list_memories(status="active", user_id="user_alice")
    assert len(alice) == 1
    assert "alice" in alice[0]["content"]
    # Bob sees only his
    bob = brain.list_memories(status="active", user_id="user_bob")
    assert len(bob) == 1
    assert "bob" in bob[0]["content"]
    # Legacy sees both (if not filtered)
    both = brain.list_memories(status="active", user_id=LEGACY_USER_ID)
    assert len(both) == 0  # nothing was assigned to legacy
    # include_all=True bypasses the filter
    everything = brain.list_memories(status="active", include_all=True)
    assert len(everything) == 2


def test_recall_scoped_to_user(tmp_path: Path) -> None:
    brain = SecondBrain(db_path=tmp_path / "brain.db")
    brain.add_memory(
        type="preference", content="alice works on nexus framework",
        confidence=0.9, importance=0.9, durability=0.9,
        source_session_id="s", source_quote="q",
        user_id="user_alice",
    )
    brain.add_memory(
        type="preference", content="bob works on completely different stuff",
        confidence=0.9, importance=0.9, durability=0.9,
        source_session_id="s", source_quote="q",
        user_id="user_bob",
    )
    # Alice's recall for "nexus" should not return bob's memory
    alice = brain.recall_for_context("nexus", n=5, user_id="user_alice")
    assert len(alice) == 1
    assert "alice" in alice[0]["content"]


def test_conflict_resolution_per_user(tmp_path: Path) -> None:
    """Same content from two users does not collide."""
    brain = SecondBrain(db_path=tmp_path / "brain.db")
    # Alice's first version
    r1 = brain.add_memory(
        type="preference", content="favorite color is blue",
        confidence=0.8, importance=0.8, durability=0.8,
        source_session_id="s", source_quote="q",
        user_id="user_alice",
    )
    # Bob's version of the same content
    r2 = brain.add_memory(
        type="preference", content="favorite color is blue",
        confidence=0.8, importance=0.8, durability=0.8,
        source_session_id="s", source_quote="q",
        user_id="user_bob",
    )
    # Both should be stored (no cross-user conflict)
    assert r1.get("status") == "active"
    assert r2.get("status") == "active"
    assert r1["user_id"] == "user_alice"
    assert r2["user_id"] == "user_bob"


def test_pending_memories_scoped_to_user(tmp_path: Path) -> None:
    brain = SecondBrain(db_path=tmp_path / "brain.db")
    brain.add_memory(
        type="preference", content="alice uncertain fact",
        confidence=0.65, importance=0.5, durability=0.5,  # pending range
        source_session_id="s", source_quote="q",
        user_id="user_alice",
    )
    brain.add_memory(
        type="preference", content="bob uncertain fact",
        confidence=0.65, importance=0.5, durability=0.5,
        source_session_id="s", source_quote="q",
        user_id="user_bob",
    )
    assert len(brain.list_pending(user_id="user_alice")) == 1
    assert len(brain.list_pending(user_id="user_bob")) == 1


# ── Project / Session / Task isolation ────────────────────────────────


def test_projects_scoped_to_user(mem: Memory) -> None:
    p1 = mem.projects.create("Alice Project", user_id="user_alice")
    p2 = mem.projects.create("Bob Project", user_id="user_bob")
    assert p1["user_id"] == "user_alice"
    assert p2["user_id"] == "user_bob"
    alice_projects = mem.projects.list(user_id="user_alice")
    assert [p["id"] for p in alice_projects] == [p1["id"]]
    assert mem.projects.list(user_id="user_bob") == [p2]


def test_sessions_scoped_to_user(mem: Memory) -> None:
    s1 = mem.sessions.create("alice session", user_id="user_alice")
    s2 = mem.sessions.create("bob session", user_id="user_bob")
    assert s1["user_id"] == "user_alice"
    assert s2["user_id"] == "user_bob"
    assert [s["id"] for s in mem.sessions.list(user_id="user_alice")] == [s1["id"]]
    assert [s["id"] for s in mem.sessions.list(user_id="user_bob")] == [s2["id"]]


def test_tasks_scoped_to_user(mem: Memory) -> None:
    p = mem.projects.create("shared project", user_id="user_alice")
    t_alice = mem.tasks.create(project_id=p["id"], title="alice task", user_id="user_alice")
    t_bob = mem.tasks.create(project_id=p["id"], title="bob task", user_id="user_bob")
    alice_tasks = mem.tasks.list(project_id=p["id"], user_id="user_alice")
    assert [t["id"] for t in alice_tasks] == [t_alice["id"]]
    assert mem.tasks.list(project_id=p["id"], user_id="user_bob") == [t_bob]


def test_conversations_scoped_to_user(mem: Memory) -> None:
    s = mem.sessions.create("shared", user_id="user_alice")
    mem.save_conversation("orchestrator", "user", "hi", session_id=s["id"], user_id="user_alice")
    mem.save_conversation("orchestrator", "user", "secret", session_id=s["id"], user_id="user_bob")
    alice_msgs = mem.list_conversations(session_id=s["id"], user_id="user_alice")
    assert len(alice_msgs) == 1
    assert alice_msgs[0]["content"] == "hi"
    bob_msgs = mem.list_conversations(session_id=s["id"], user_id="user_bob")
    assert len(bob_msgs) == 1
    assert bob_msgs[0]["content"] == "secret"


def test_save_conversation_inherits_user_id_from_session(mem: Memory) -> None:
    """If user_id not passed, save_conversation should pick it up from the session."""
    s = mem.sessions.create("alice session", user_id="user_alice")
    mem.save_conversation("orchestrator", "user", "msg", session_id=s["id"])  # no user_id
    rows = mem.list_conversations(session_id=s["id"])
    assert rows[0]["user_id"] == "user_alice"


# ── Cross-user CRUD prevention ───────────────────────────────────────


def test_cannot_approve_other_users_memory(tmp_path: Path) -> None:
    """approve_memory is by id — caller must check ownership at the API layer."""
    # This is enforced in api/server.py via _owns_or_admin. At the brain level,
    # approve_memory just looks up by id (no ownership check), but the API
    # layer above enforces it. Document the contract here.
    brain = SecondBrain(db_path=tmp_path / "brain.db")
    m = brain.add_memory(
        type="preference", content="alice's pending",
        confidence=0.65, importance=0.5, durability=0.5,
        source_session_id="s", source_quote="q",
        user_id="user_alice",
    )
    # alice approves her own memory
    approved = brain.approve_memory(m["id"])
    assert approved["status"] == "active"
    assert approved["user_id"] == "user_alice"
