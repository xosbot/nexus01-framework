"""Tests for core/jwt_auth.py."""
from __future__ import annotations

import time

import jwt
import pytest

from core import jwt_auth
from core.jwt_auth import DEFAULT_EXPIRY_SECONDS, issue_token, token_from_bearer, verify_token


@pytest.fixture(autouse=True)
def _reset_secret(monkeypatch, tmp_path):
    """Each test gets a fresh, deterministic secret so they're independent."""
    secret_file = tmp_path / "jwt_secret"
    secret_file.write_text("test-secret-" + "x" * 40)
    monkeypatch.setenv("NEXUS_JWT_SECRET", "")
    monkeypatch.setenv("NEXUS_JWT_SECRET_FILE", str(secret_file))
    jwt_auth.reset_secret_cache()
    yield
    jwt_auth.reset_secret_cache()


# ── issue_token ───────────────────────────────────────────────────────


def test_issue_token_returns_string():
    t = issue_token("user_abc", scope="user")
    assert isinstance(t, str)
    assert len(t) > 50  # JWTs are long


def test_issue_token_contains_expected_claims():
    t = issue_token("user_abc", scope="admin")
    claims = jwt.decode(t, "test-secret-" + "x" * 40, algorithms=["HS256"])
    assert claims["sub"] == "user_abc"
    assert claims["scope"] == "admin"
    assert "iat" in claims
    assert "exp" in claims
    assert claims["exp"] > claims["iat"]


def test_issue_token_default_expiry_is_seven_days():
    t = issue_token("u")
    claims = jwt.decode(t, "test-secret-" + "x" * 40, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == DEFAULT_EXPIRY_SECONDS


def test_issue_token_custom_expiry():
    t = issue_token("u", expires_in=60)
    claims = jwt.decode(t, "test-secret-" + "x" * 40, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 60


def test_issue_token_rejects_empty_user_id():
    with pytest.raises(ValueError):
        issue_token("")


# ── verify_token ──────────────────────────────────────────────────────


def test_verify_token_accepts_valid():
    t = issue_token("user_abc", scope="user")
    claims = verify_token(t)
    assert claims is not None
    assert claims["sub"] == "user_abc"
    assert claims["scope"] == "user"


def test_verify_token_rejects_expired():
    t = issue_token("u", expires_in=-1)  # already expired
    assert verify_token(t) is None


def test_verify_token_rejects_tampered():
    t = issue_token("u")
    # Tamper: flip a char in the payload section
    parts = t.split(".")
    tampered = parts[0] + "." + parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B") + "." + parts[2]
    assert verify_token(tampered) is None


def test_verify_token_rejects_wrong_secret(monkeypatch):
    t = issue_token("u")
    monkeypatch.setenv("NEXUS_JWT_SECRET", "different-secret-" + "y" * 40)
    jwt_auth.reset_secret_cache()
    assert verify_token(t) is None


def test_verify_token_rejects_empty():
    assert verify_token("") is None
    assert verify_token(None) is None  # type: ignore[arg-type]


def test_verify_token_rejects_garbage():
    assert verify_token("not-a-jwt") is None
    assert verify_token("a.b.c") is None


def test_verify_token_rejects_missing_sub():
    """A JWT without `sub` is invalid for our purposes (no user identity)."""
    # Forge a token signed with the right secret but no sub claim
    forged = jwt.encode(
        {"scope": "user", "iat": int(time.time()), "exp": int(time.time()) + 60},
        "test-secret-" + "x" * 40,
        algorithm="HS256",
    )
    assert verify_token(forged) is None


# ── token_from_bearer ─────────────────────────────────────────────────


def test_bearer_extracts_token():
    assert token_from_bearer("Bearer abc.def.ghi") == "abc.def.ghi"


def test_bearer_strips_whitespace():
    assert token_from_bearer("Bearer   abc   ") == "abc"


def test_bearer_rejects_other_schemes():
    assert token_from_bearer("Basic dXNlcjpwYXNz") is None
    assert token_from_bearer("abc.def.ghi") is None


def test_bearer_handles_empty():
    assert token_from_bearer("") is None
    assert token_from_bearer("Bearer ") is None
    assert token_from_bearer("Bearer") is None
