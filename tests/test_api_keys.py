"""Tests for core/api_keys.py — key generation, lookup, revocation, masking."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.api_keys import (
    ApiKeyStore,
    KEY_PREFIX,
    generate_key,
    hash_key,
    mask_key,
    validate_scope,
)
from core.memory import Memory
from core.users import LEGACY_USER_ID


@pytest.fixture
def mem(tmp_path: Path) -> Memory:
    return Memory(db_path=tmp_path / "keys_test.db")


@pytest.fixture
def user(mem: Memory) -> dict:
    return mem.users.create("owner@example.com", "Owner", password="p")


# ── Generation / hashing ─────────────────────────────────────────────


def test_generate_key_format():
    raw, h = generate_key()
    assert raw.startswith(KEY_PREFIX)
    assert len(raw) > 40  # prefix + url-safe 32 bytes ≈ 50 chars
    assert len(h) == 64   # sha256 hex
    assert h == hash_key(raw)


def test_generate_key_is_random():
    """Two calls should produce different keys (256 bits of entropy)."""
    a, _ = generate_key()
    b, _ = generate_key()
    assert a != b


def test_hash_key_stable():
    raw = "nxk_test_abc"
    assert hash_key(raw) == hash_key(raw)
    assert hash_key(raw) != hash_key("nxk_test_xyz")


def test_mask_key_short_safe():
    assert mask_key("nxk_abcdefghijklmnop") == "nxk_abc...mnop"
    assert mask_key("short") == "***"
    assert mask_key("") == "***"


def test_validate_scope_accepts_valid():
    for s in ("admin", "user", "readonly"):
        assert validate_scope(s) == s


def test_validate_scope_rejects_invalid():
    with pytest.raises(ValueError):
        validate_scope("superuser")


# ── Create + lookup ──────────────────────────────────────────────────


def test_create_returns_raw_key_once(mem: Memory, user: dict) -> None:
    rec = mem.api_keys.create(user["id"], scope="user", name="laptop")
    assert rec["raw_key"].startswith(KEY_PREFIX)
    assert rec["key_hash"]
    assert rec["user_id"] == user["id"]
    assert rec["scope"] == "user"
    assert rec["name"] == "laptop"


def test_lookup_finds_created_key(mem: Memory, user: dict) -> None:
    rec = mem.api_keys.create(user["id"], scope="user")
    found = mem.api_keys.lookup(rec["raw_key"])
    assert found is not None
    assert found["key_hash"] == rec["key_hash"]
    assert found["user_id"] == user["id"]
    assert found["scope"] == "user"


def test_lookup_bumps_last_used(mem: Memory, user: dict) -> None:
    rec = mem.api_keys.create(user["id"], scope="user")
    assert rec["last_used"] is None
    found = mem.api_keys.lookup(rec["raw_key"])
    assert found is not None
    assert found["last_used"] is not None


def test_lookup_returns_none_for_unknown(mem: Memory) -> None:
    """Random valid-format key with no match should return None."""
    bogus, _ = generate_key()
    assert mem.api_keys.lookup(bogus) is None


def test_lookup_returns_none_for_malformed(mem: Memory) -> None:
    """A key that doesn't start with our prefix shouldn't be a hit."""
    assert mem.api_keys.lookup("not-an-nxk-key") is None
    assert mem.api_keys.lookup("") is None
    assert mem.api_keys.lookup(None) is None  # type: ignore[arg-type]


def test_lookup_skips_expired_keys(mem: Memory, user: dict) -> None:
    rec = mem.api_keys.create(user["id"], scope="user", expires_at="2000-01-01T00:00:00")
    assert mem.api_keys.lookup(rec["raw_key"]) is None


def test_create_rejects_invalid_scope(mem: Memory, user: dict) -> None:
    with pytest.raises(ValueError):
        mem.api_keys.create(user["id"], scope="superuser")


# ── List + revoke ────────────────────────────────────────────────────


def test_list_for_user(mem: Memory, user: dict) -> None:
    mem.api_keys.create(user["id"], scope="user", name="k1")
    mem.api_keys.create(user["id"], scope="admin", name="k2")
    mem.api_keys.create("user_other", scope="user", name="other")

    listed = mem.api_keys.list_for_user(user["id"])
    assert len(listed) == 2
    names = {k["name"] for k in listed}
    assert names == {"k1", "k2"}
    # Public view must NOT contain raw_key or key_hash
    for k in listed:
        assert "raw_key" not in k
        assert "key_hash" not in k
        assert "id" in k  # short ID for UI


def test_revoke_specific_key(mem: Memory, user: dict) -> None:
    a = mem.api_keys.create(user["id"], scope="user", name="a")
    b = mem.api_keys.create(user["id"], scope="user", name="b")

    assert mem.api_keys.revoke(a["key_hash"], user_id=user["id"]) is True
    assert mem.api_keys.lookup(a["raw_key"]) is None
    # b still works
    assert mem.api_keys.lookup(b["raw_key"]) is not None


def test_revoke_other_users_key_blocked(mem: Memory, user: dict) -> None:
    """A user cannot revoke another user's key (caller's user_id must match)."""
    a = mem.api_keys.create(user["id"], scope="user")
    # Pretend to be a different user — revoke should be a no-op
    assert mem.api_keys.revoke(a["key_hash"], user_id="user_attacker") is False
    # Key still valid
    assert mem.api_keys.lookup(a["raw_key"]) is not None


def test_revoke_all_for_user(mem: Memory, user: dict) -> None:
    mem.api_keys.create(user["id"], scope="user")
    mem.api_keys.create(user["id"], scope="user")
    deleted = mem.api_keys.revoke_all_for_user(user["id"])
    assert deleted == 2
    assert mem.api_keys.list_for_user(user["id"]) == []


# ── Cross-user isolation ─────────────────────────────────────────────


def test_keys_isolated_between_users(mem: Memory, user: dict) -> None:
    """User A's key must not be visible / revokable by user B."""
    alice = mem.users.create("alice@example.com", "A", password="p")
    bob = mem.users.create("bob@example.com", "B", password="p")
    alice_key = mem.api_keys.create(alice["id"], scope="user")
    # Bob cannot see Alice's key
    assert mem.api_keys.list_for_user(bob["id"]) == []
    # Bob cannot revoke Alice's key
    assert mem.api_keys.revoke(alice_key["key_hash"], user_id=bob["id"]) is False
    # Alice's key still works
    assert mem.api_keys.lookup(alice_key["raw_key"]) is not None


def test_legacy_user_can_have_keys(mem: Memory) -> None:
    """The legacy user (system) can have a key for back-compat scripts."""
    rec = mem.api_keys.create(LEGACY_USER_ID, scope="admin", name="legacy-script")
    assert mem.api_keys.lookup(rec["raw_key"]) is not None
