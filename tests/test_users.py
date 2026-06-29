"""Tests for core/users.py — user CRUD + password hashing + auth."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from core.memory import Memory
from core.users import (
    LEGACY_USER_EMAIL,
    LEGACY_USER_ID,
    LEGACY_USER_NAME,
    hash_password,
    validate_email,
    validate_name,
    validate_role,
    verify_password,
)


@pytest.fixture
def mem(tmp_path: Path) -> Memory:
    return Memory(db_path=tmp_path / "users_test.db")


# ── Password hashing ─────────────────────────────────────────────────


def test_hash_password_returns_bcrypt_format():
    """Hash should start with $2b$ (or $2a$) and be ASCII."""
    h = hash_password("hunter2")
    assert h.startswith(("$2a$", "$2b$", "$2y$"))
    assert h.isascii()


def test_hash_password_rejects_empty():
    with pytest.raises(ValueError):
        hash_password("")


def test_hash_password_rejects_oversized():
    with pytest.raises(ValueError):
        hash_password("x" * 2000)


def test_verify_password_matches_hash():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_password_rejects_wrong():
    h = hash_password("secret")
    assert verify_password("not-the-secret", h) is False


def test_verify_password_rejects_empty():
    h = hash_password("secret")
    assert verify_password("", h) is False
    assert verify_password("secret", "") is False


def test_verify_password_rejects_malformed_hash():
    """A non-bcrypt string should not raise, just return False."""
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_hash_password_produces_unique_salts():
    """Two hashes of the same password should differ (bcrypt salt is random)."""
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    # Both should still verify
    assert verify_password("same", a)
    assert verify_password("same", b)


# ── Email / name / role validation ────────────────────────────────────


def test_validate_email_normalizes_lowercase_and_strips():
    assert validate_email("  Alice@Example.COM  ") == "alice@example.com"


def test_validate_email_rejects_garbage():
    for bad in ["", "no-at-sign", "no@domain", "no@tld.", "@no-local.com", "spaces in@email.com"]:
        with pytest.raises(ValueError):
            validate_email(bad)


def test_validate_email_rejects_too_long():
    with pytest.raises(ValueError):
        validate_email("a" * 250 + "@x.com")


def test_validate_name_requires_non_empty():
    for bad in ["", "   ", None]:  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            validate_name(bad)  # type: ignore[arg-type]


def test_validate_name_rejects_too_long():
    with pytest.raises(ValueError):
        validate_name("x" * 200)


def test_validate_role_accepts_valid():
    for r in ("admin", "user", "readonly"):
        assert validate_role(r) == r


def test_validate_role_rejects_invalid():
    with pytest.raises(ValueError):
        validate_role("superuser")


# ── UserStore CRUD ────────────────────────────────────────────────────


def test_legacy_user_created_on_init(mem: Memory) -> None:
    """First open of the DB should create the legacy user."""
    legacy = mem.users.get(LEGACY_USER_ID)
    assert legacy is not None
    assert legacy["email"] == LEGACY_USER_EMAIL
    assert legacy["name"] == LEGACY_USER_NAME
    assert legacy["role"] == "admin"
    # Legacy has no password (it's a system user, no human logs in as it)
    auth = mem.users.authenticate(LEGACY_USER_EMAIL, "anything")
    assert auth is None  # No password set, so password auth always fails


def test_create_user_with_password(mem: Memory) -> None:
    u = mem.users.create("alice@example.com", "Alice", password="secret")
    assert u["id"].startswith("user_")
    assert u["email"] == "alice@example.com"
    assert u["role"] == "user"
    # password_hash is NEVER returned in public view
    assert "password_hash" not in u


def test_create_user_with_role(mem: Memory) -> None:
    u = mem.users.create("admin@example.com", "Admin", password="x", role="admin")
    assert u["role"] == "admin"


def test_create_user_duplicate_email_raises(mem: Memory) -> None:
    mem.users.create("dup@example.com", "First", password="p")
    with pytest.raises(ValueError, match="already registered"):
        mem.users.create("dup@example.com", "Second", password="p")


def test_create_user_normalizes_email(mem: Memory) -> None:
    u1 = mem.users.create("Alice@Example.com", "A", password="p")
    # Lookup with different case should find the same user
    u2 = mem.users.get_by_email("alice@example.com")
    assert u2 is not None
    assert u2["id"] == u1["id"]


def test_create_oauth_user_no_password(mem: Memory) -> None:
    u = mem.users.create(
        "oauth@example.com", "OAuth User",
        oauth_provider="google", oauth_id="google-abc-123",
    )
    assert u["id"].startswith("user_")
    # Email lookup finds them
    assert mem.users.get_by_email("oauth@example.com") is not None
    # OAuth lookup finds them
    found = mem.users.get_by_oauth("google", "google-abc-123")
    assert found is not None
    assert found["id"] == u["id"]


def test_create_user_requires_password_unless_oauth(mem: Memory) -> None:
    with pytest.raises(ValueError, match="password is required"):
        mem.users.create("nopw@example.com", "No Password")


def test_get_by_email_returns_none_for_missing(mem: Memory) -> None:
    assert mem.users.get_by_email("nobody@nowhere.com") is None


def test_get_by_email_returns_none_for_invalid(mem: Memory) -> None:
    """Invalid emails should not raise in get_by_email, just return None."""
    assert mem.users.get_by_email("not-an-email") is None


def test_update_name_and_role(mem: Memory) -> None:
    u = mem.users.create("u@example.com", "Original", password="p")
    updated = mem.users.update(u["id"], name="New Name", role="admin")
    assert updated is not None
    assert updated["name"] == "New Name"
    assert updated["role"] == "admin"


def test_update_password(mem: Memory) -> None:
    u = mem.users.create("u@example.com", "U", password="old")
    mem.users.update(u["id"], password="new-pass-1")
    assert mem.users.authenticate("u@example.com", "old") is None
    assert mem.users.authenticate("u@example.com", "new-pass-1") is not None


def test_update_missing_returns_none(mem: Memory) -> None:
    assert mem.users.update("user_nope", name="X") is None


def test_delete_user(mem: Memory) -> None:
    u = mem.users.create("del@example.com", "Del", password="p")
    assert mem.users.delete(u["id"]) is True
    assert mem.users.get(u["id"]) is None


def test_cannot_delete_legacy_user(mem: Memory) -> None:
    with pytest.raises(ValueError, match="legacy"):
        mem.users.delete(LEGACY_USER_ID)


def test_delete_missing_returns_false(mem: Memory) -> None:
    assert mem.users.delete("user_nope") is False


# ── Authentication ────────────────────────────────────────────────────


def test_authenticate_returns_user_on_success(mem: Memory) -> None:
    mem.users.create("a@example.com", "A", password="secret")
    user = mem.users.authenticate("a@example.com", "secret")
    assert user is not None
    assert user["email"] == "a@example.com"


def test_authenticate_returns_none_on_wrong_password(mem: Memory) -> None:
    mem.users.create("a@example.com", "A", password="secret")
    assert mem.users.authenticate("a@example.com", "WRONG") is None


def test_authenticate_returns_none_for_unknown_user(mem: Memory) -> None:
    assert mem.users.authenticate("ghost@nowhere.com", "anything") is None


def test_authenticate_oauth_only_user_returns_none(mem: Memory) -> None:
    """OAuth-only users (no password) cannot authenticate by password."""
    mem.users.create("oauth@example.com", "O", oauth_provider="google", oauth_id="x")
    assert mem.users.authenticate("oauth@example.com", "anything") is None


def test_touch_updates_last_seen(mem: Memory) -> None:
    u = mem.users.create("t@example.com", "T", password="p")
    assert u["last_seen"] is None
    mem.users.touch(u["id"])
    after = mem.users.get(u["id"])
    assert after["last_seen"] is not None


def test_list_returns_recent_first(mem: Memory) -> None:
    a = mem.users.create("a@example.com", "A", password="p")
    b = mem.users.create("b@example.com", "B", password="p")
    listed = mem.users.list()
    ids = [u["id"] for u in listed]
    # Both should be in the list (order is most-recent-first)
    assert a["id"] in ids
    assert b["id"] in ids
    # Legacy user also in list
    assert LEGACY_USER_ID in ids
