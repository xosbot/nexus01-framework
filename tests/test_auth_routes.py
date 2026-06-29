"""Integration tests for /api/auth/* routes — register, login, me, API keys."""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.server import create_api_app
from core.jwt_auth import verify_token
from core.memory import Memory


def _build_nexus_with_real_memory() -> SimpleNamespace:
    """A real Memory instance (so users + api_keys work), but mocked LLM/gateway."""
    tmp = Path(tempfile.mkdtemp())
    memory = Memory(db_path=tmp / "auth_test.db")
    llm = MagicMock()
    llm.provider_status.return_value = []
    llm.stats.return_value = {}
    rag = MagicMock()
    rag.stats.return_value = {}
    gateway = MagicMock()
    gateway.approvals.list_pending.return_value = []
    return SimpleNamespace(
        gateway=gateway, memory=memory, llm=llm, rag=rag, channels=[],
        brain=None, copilot=None, integrations=None, proactive=None, social_media=None,
    )


@pytest.fixture
def client():
    nexus = _build_nexus_with_real_memory()
    app = create_api_app(nexus)
    return TestClient(app)


# ── Register ──────────────────────────────────────────────────────────


def test_register_creates_user_and_returns_jwt(client):
    r = client.post("/api/auth/register", json={
        "email": "alice@example.com", "name": "Alice", "password": "secret-123",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == "admin"  # first user becomes admin
    assert body["token_type"] == "Bearer"
    # JWT verifies
    claims = verify_token(body["token"])
    assert claims is not None
    assert claims["sub"] == body["user"]["id"]


def test_register_second_user_is_not_admin(client):
    client.post("/api/auth/register", json={
        "email": "first@example.com", "name": "First", "password": "secret-1",
    })
    r = client.post("/api/auth/register", json={
        "email": "second@example.com", "name": "Second", "password": "secret-2",
    })
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "user"


def test_register_duplicate_email_400(client):
    body = {"email": "dup@example.com", "name": "Dup", "password": "secret-9"}
    client.post("/api/auth/register", json=body)
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 400
    assert "already registered" in r.json()["detail"]


def test_register_weak_password_422(client):
    r = client.post("/api/auth/register", json={
        "email": "x@example.com", "name": "X", "password": "short",
    })
    assert r.status_code == 422


def test_register_invalid_email_400(client):
    r = client.post("/api/auth/register", json={
        "email": "not-an-email", "name": "X", "password": "secret-123",
    })
    assert r.status_code == 400


# ── Login ─────────────────────────────────────────────────────────────


def test_login_returns_jwt_for_existing_user(client):
    client.post("/api/auth/register", json={
        "email": "alice@example.com", "name": "Alice", "password": "secret-123",
    })
    r = client.post("/api/auth/login", json={
        "email": "alice@example.com", "password": "secret-123",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "alice@example.com"
    claims = verify_token(body["token"])
    assert claims["sub"] == body["user"]["id"]


def test_login_wrong_password_401(client):
    client.post("/api/auth/register", json={
        "email": "alice@example.com", "name": "Alice", "password": "secret-123",
    })
    r = client.post("/api/auth/login", json={
        "email": "alice@example.com", "password": "WRONG",
    })
    assert r.status_code == 401


def test_login_unknown_user_401(client):
    r = client.post("/api/auth/login", json={
        "email": "nobody@nowhere.com", "password": "anything",
    })
    assert r.status_code == 401


# ── Me ────────────────────────────────────────────────────────────────


def test_me_returns_current_user_with_jwt(client):
    reg = client.post("/api/auth/register", json={
        "email": "alice@example.com", "name": "Alice", "password": "secret-123",
    })
    token = reg.json()["token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"


def test_me_401_without_auth(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_401_with_invalid_token(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_me_401_with_expired_token(client, monkeypatch, tmp_path):
    # Use a tiny expiry and let it lapse
    from core import jwt_auth
    secret_file = tmp_path / "jwt_secret"
    secret_file.write_text("test-secret-" + "x" * 40)
    monkeypatch.setenv("NEXUS_JWT_SECRET_FILE", str(secret_file))
    jwt_auth.reset_secret_cache()
    from core.jwt_auth import issue_token
    expired = issue_token("user_abc", expires_in=-10)
    jwt_auth.reset_secret_cache()
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


# ── API keys ──────────────────────────────────────────────────────────


def _register_and_get_token(client, email="alice@example.com") -> str:
    r = client.post("/api/auth/register", json={
        "email": email, "name": "Alice", "password": "secret-123",
    })
    return r.json()["token"]


def test_create_key_returns_raw_key_once(client):
    token = _register_and_get_token(client)
    r = client.post(
        "/api/auth/keys", json={"name": "laptop", "scope": "user"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["raw_key"].startswith("nxk_")
    assert body["scope"] == "user"
    assert body["name"] == "laptop"
    assert "Save this key now" in body["message"]


def test_create_key_works_for_self_with_api_key(client):
    """An authenticated user can use their JWT or their API key to create more keys."""
    token = _register_and_get_token(client)
    r1 = client.post(
        "/api/auth/keys", json={"name": "first"},
        headers={"Authorization": f"Bearer {token}"},
    )
    raw_key = r1.json()["raw_key"]
    # Now use that API key to create another
    r2 = client.post(
        "/api/auth/keys", json={"name": "second"},
        headers={"X-API-Key": raw_key},
    )
    assert r2.status_code == 200


def test_create_admin_key_requires_admin_role(client):
    # First real user is admin
    admin_token = _register_and_get_token(client, "admin@example.com")
    # Second user is regular 'user' role
    client.post("/api/auth/register", json={
        "email": "user@example.com", "name": "U", "password": "secret-123",
    })
    login = client.post("/api/auth/login", json={
        "email": "user@example.com", "password": "secret-123",
    })
    user_token = login.json()["token"]
    # user can't make admin key
    r = client.post(
        "/api/auth/keys", json={"scope": "admin"},
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert r.status_code == 403
    # admin can
    r2 = client.post(
        "/api/auth/keys", json={"scope": "admin"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r2.status_code == 200


def test_list_keys_returns_user_owned_only(client):
    # Two users
    t1 = _register_and_get_token(client, "alice@example.com")
    t2 = _register_and_get_token(client, "bob@example.com")
    client.post("/api/auth/keys", json={"name": "a-key"},
                headers={"Authorization": f"Bearer {t1}"})
    client.post("/api/auth/keys", json={"name": "b1"},
                headers={"Authorization": f"Bearer {t2}"})
    client.post("/api/auth/keys", json={"name": "b2"},
                headers={"Authorization": f"Bearer {t2}"})

    r1 = client.get("/api/auth/keys", headers={"Authorization": f"Bearer {t1}"})
    r2 = client.get("/api/auth/keys", headers={"Authorization": f"Bearer {t2}"})
    assert len(r1.json()["keys"]) == 1
    assert len(r2.json()["keys"]) == 2


def test_revoke_own_key(client):
    token = _register_and_get_token(client)
    r = client.post("/api/auth/keys", json={"name": "doomed"},
                    headers={"Authorization": f"Bearer {token}"})
    keys = client.get("/api/auth/keys", headers={"Authorization": f"Bearer {token}"}).json()["keys"]
    key_id = keys[0]["id"]
    r = client.delete(f"/api/auth/keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    # And it's gone
    keys_after = client.get("/api/auth/keys", headers={"Authorization": f"Bearer {token}"}).json()["keys"]
    assert keys_after == []


def test_revoke_other_users_key_404(client):
    t1 = _register_and_get_token(client, "alice@example.com")
    t2 = _register_and_get_token(client, "bob@example.com")
    client.post("/api/auth/keys", json={"name": "a"},
                headers={"Authorization": f"Bearer {t1}"})
    alice_keys = client.get("/api/auth/keys", headers={"Authorization": f"Bearer {t1}"}).json()["keys"]
    alice_key_id = alice_keys[0]["id"]
    # Bob tries to revoke Alice's key by guessing the short ID
    r = client.delete(f"/api/auth/keys/{alice_key_id}", headers={"Authorization": f"Bearer {t2}"})
    assert r.status_code == 404


# ── Auth precedence ──────────────────────────────────────────────────


def test_jwt_takes_precedence_over_api_key(client):
    """When both are present, JWT wins (used for identity, not just role)."""
    alice_t = _register_and_get_token(client, "alice@example.com")
    bob_t = _register_and_get_token(client, "bob@example.com")
    # Bob's key
    bob_key = client.post("/api/auth/keys", json={"name": "bob"},
                          headers={"Authorization": f"Bearer {bob_t}"}).json()["raw_key"]
    # Alice uses Bob's key + her own JWT — JWT wins, so the call is as Alice
    r = client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {alice_t}",
        "X-API-Key": bob_key,
    })
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"


def test_nxk_key_resolves_to_owner(client):
    """An X-API-Key: nxk_... should authenticate as the key's owner."""
    token = _register_and_get_token(client)
    raw = client.post("/api/auth/keys", json={"name": "personal"},
                      headers={"Authorization": f"Bearer {token}"}).json()["raw_key"]
    r = client.get("/api/auth/me", headers={"X-API-Key": raw})
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"


def test_invalid_nxk_key_401(client):
    _register_and_get_token(client)
    r = client.get("/api/auth/me", headers={"X-API-Key": "nxk_fake_garbage"})
    assert r.status_code == 401
