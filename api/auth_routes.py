"""HTTP routes for user auth: register, login, me, API key lifecycle.

Mounted at /api/auth/* by api/server.py. The /login and /register routes
are exempt from AuthMiddleware (see api/auth.py:EXEMPT_PREFIXES).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.jwt_auth import DEFAULT_EXPIRY_SECONDS, issue_token

logger = logging.getLogger(__name__)


# ── Request/response models ───────────────────────────────────────────


class RegisterRequest(BaseModel):
    # Plain str — validation is in core.users.validate_email (no new dep needed)
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=1024)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class CreateKeyRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    scope: str = Field(default="user")
    expires_at: str | None = None  # ISO 8601, optional


# ── Router factory ────────────────────────────────────────────────────


def build_auth_router(memory: Any) -> APIRouter:
    """Return an APIRouter with all /api/auth/* routes bound to `memory`."""
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    # ── Register ──────────────────────────────────────────────────────

    @router.post("/register")
    async def register(body: RegisterRequest) -> dict:
        """Create a new user. Returns the user dict + a JWT for the new user.

        Anyone can register. The first user to register is promoted to admin
        automatically (so a fresh deployment has an admin without manual DB
        edits). Subsequent users are 'user' role.
        """
        users = getattr(memory, "users", None)
        if users is None:
            raise HTTPException(503, "user accounts are not enabled on this deployment")
        # First real (non-legacy) user becomes admin
        from core.users import LEGACY_USER_ID
        real_users = [u for u in users.list() if u["id"] != LEGACY_USER_ID]
        role = "admin" if not real_users else "user"
        try:
            user = users.create(
                body.email, body.name, password=body.password, role=role,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        token = issue_token(user["id"], scope=user["role"])
        return {
            "user": user,
            "token": token,
            "token_type": "Bearer",
            "expires_in": DEFAULT_EXPIRY_SECONDS,
        }

    # ── Login ─────────────────────────────────────────────────────────

    @router.post("/login")
    async def login(body: LoginRequest) -> dict:
        """Authenticate by email + password. Returns user + JWT."""
        users = getattr(memory, "users", None)
        if users is None:
            raise HTTPException(503, "user accounts are not enabled on this deployment")
        user = users.authenticate(body.email, body.password)
        if user is None:
            raise HTTPException(401, "Invalid email or password")
        token = issue_token(user["id"], scope=user["role"])
        return {
            "user": user,
            "token": token,
            "token_type": "Bearer",
            "expires_in": DEFAULT_EXPIRY_SECONDS,
        }

    # ── Me (current user) ─────────────────────────────────────────────

    @router.get("/me")
    async def me(request: Request) -> dict:
        """Return the authenticated user's profile. 401 if not logged in."""
        ctx = getattr(request.state, "auth", None)
        if ctx is None or ctx.source == "legacy":
            raise HTTPException(401, "Not authenticated")
        users = getattr(memory, "users", None)
        if users is None:
            raise HTTPException(503, "user accounts not enabled")
        user = users.get(ctx.user_id)
        if user is None:
            raise HTTPException(404, "User not found")
        return user

    # ── API key lifecycle ─────────────────────────────────────────────

    @router.get("/keys")
    async def list_keys(request: Request) -> dict:
        ctx = getattr(request.state, "auth", None)
        if ctx is None or ctx.source == "legacy":
            raise HTTPException(401, "Not authenticated")
        keys = memory.api_keys.list_for_user(ctx.user_id)
        return {"keys": keys}

    @router.post("/keys")
    async def create_key(body: CreateKeyRequest, request: Request) -> dict:
        ctx = getattr(request.state, "auth", None)
        if ctx is None or ctx.source == "legacy":
            raise HTTPException(401, "Not authenticated")
        # Only admins can mint admin-scoped keys for themselves; users get user-scoped.
        scope = body.scope
        if scope == "admin" and ctx.role != "admin":
            raise HTTPException(403, "Only admins can create admin-scoped keys")
        try:
            rec = memory.api_keys.create(
                ctx.user_id, scope=scope, name=body.name, expires_at=body.expires_at,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        # Strip the key_hash from the response (raw_key is the only thing the
        # user needs; hash is for storage)
        return {
            "raw_key": rec["raw_key"],
            "scope": rec["scope"],
            "name": rec["name"],
            "created_at": rec["created_at"],
            "expires_at": rec["expires_at"],
            "message": "Save this key now — it will not be shown again.",
        }

    @router.delete("/keys/{key_id}")
    async def revoke_key(key_id: str, request: Request) -> dict:
        """Revoke one of your own keys by short ID."""
        ctx = getattr(request.state, "auth", None)
        if ctx is None or ctx.source == "legacy":
            raise HTTPException(401, "Not authenticated")
        # The UI sees short IDs (first 12 chars of the hash). Look up the
        # user's keys and find the matching one.
        my_keys = memory.api_keys.list_for_user(ctx.user_id)
        match = next((k for k in my_keys if k["id"] == key_id), None)
        if match is None:
            raise HTTPException(404, "Key not found")
        # Resolve the full hash from the DB (the public view strips it)
        row = memory._conn.execute(
            "SELECT key_hash FROM api_keys WHERE user_id = ? AND substr(key_hash,1,12) = ?",
            (ctx.user_id, key_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Key not found")
        memory.api_keys.revoke(row["key_hash"], user_id=ctx.user_id)
        return {"deleted": True}

    return router
