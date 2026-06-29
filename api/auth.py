"""API authentication — scoped API keys with admin/read-only tiers + rate limiting.

Phase 2 adds:
    - JWT bearer tokens (Authorization: Bearer <jwt>) → maps to a user_id
    - Per-user API keys (X-API-Key: nxk_...) stored hashed in `api_keys`
    - Legacy env-configured keys (NEXUS_API_KEY / NEXUS_READONLY_KEY)
      continue to work for backwards compat

Auth precedence (when multiple credentials are present):
    1. Authorization: Bearer <jwt>   → user identity from claims
    2. X-API-Key: nxk_...            → user from key's owner
    3. X-API-Key: <env-key>          → role from env (admin or readonly)
    4. None                          → 401 (if any auth is configured)
"""

from __future__ import annotations

import hmac
import os
import time
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.jwt_auth import token_from_bearer, verify_token

logger = logging.getLogger(__name__)

# Key format: simple token or role:token (e.g. "admin:mytoken" or just "mytoken")
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30


@dataclass
class APIKey:
    token: str
    role: str  # "admin" | "read"

    def matches(self, candidate: str) -> bool:
        return hmac.compare_digest(self.token, candidate)


def _parse_key(raw: str) -> APIKey | None:
    if not raw:
        return None
    # Support "role:token" format
    if ":" in raw:
        parts = raw.split(":", 1)
        if parts[0] in ("admin", "read"):
            return APIKey(token=parts[0] + ":" + parts[1], role=parts[0])
    return APIKey(token=raw, role="admin")


API_KEY = _parse_key(os.getenv("NEXUS_API_KEY", ""))
READONLY_KEY = _parse_key(os.getenv("NEXUS_READONLY_KEY", ""))


def resolve_key(candidate: str) -> APIKey | None:
    for k in (API_KEY, READONLY_KEY):
        if k and k.matches(candidate):
            return k
    return None


@dataclass
class AuthContext:
    """What the rest of the API needs to know about the caller."""
    user_id: str          # legacy: "user_legacy" when no user is logged in
    role: str             # "admin" | "user" | "readonly"
    source: str           # "jwt" | "api_key" | "env_key" | "legacy"
    key_scope: str | None = None  # scope of the API key (if used)

    def is_admin(self) -> bool:
        return self.role == "admin"

    def can_write(self) -> bool:
        return self.role in ("admin", "user")


def _resolve_from_jwt(authorization: str) -> AuthContext | None:
    raw = token_from_bearer(authorization)
    if not raw:
        return None
    claims = verify_token(raw)
    if claims is None:
        return None
    return AuthContext(
        user_id=claims["sub"],
        role=claims.get("scope", "user"),
        source="jwt",
    )


def _resolve_from_api_key(token: str, memory: Any | None) -> AuthContext | None:
    """Look up a user-owned nxk_ key. Falls through if not nxk_-prefixed."""
    if not token or not token.startswith("nxk_"):
        return None
    if memory is None or not hasattr(memory, "api_keys"):
        return None
    rec = memory.api_keys.lookup(token)
    if rec is None:
        return None
    user = memory.users.get(rec["user_id"])
    if user is None:
        return None
    return AuthContext(
        user_id=rec["user_id"],
        role=rec.get("scope", "user"),
        source="api_key",
        key_scope=rec.get("scope"),
    )


def _resolve_from_env_key(token: str) -> AuthContext | None:
    k = resolve_key(token)
    if k is None:
        return None
    return AuthContext(
        user_id="user_legacy",  # env keys map to the legacy user
        role=k.role,
        source="env_key",
        key_scope=k.role,
    )


def resolve_auth(request: Request, memory: Any | None = None) -> AuthContext | None:
    """Resolve the caller's identity from a request.

    Returns None if no valid credential is found.
    Tries: JWT → per-user nxk_ key → env-configured key.
    """
    authorization = request.headers.get("Authorization", "")
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization[7:]
    if not token:
        token = request.headers.get("X-API-Key", "")

    # 1) JWT
    ctx = _resolve_from_jwt(authorization)
    if ctx is not None:
        return ctx
    # 2) per-user nxk_ API key
    ctx = _resolve_from_api_key(token, memory)
    if ctx is not None:
        return ctx
    # 3) env-configured legacy key
    ctx = _resolve_from_env_key(token)
    if ctx is not None:
        return ctx
    return None


def has_role(request: Request, required: str = "read") -> bool:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        candidate = auth[7:]
    else:
        candidate = request.headers.get("X-API-Key", "")
    key = resolve_key(candidate)
    if not key:
        return False
    if required == "read":
        return True
    if required == "admin":
        return key.role == "admin"
    return False


class RateLimiter:
    def __init__(self, max_requests: int = RATE_LIMIT_MAX, window: int = RATE_LIMIT_WINDOW):
        self.max_requests = max_requests
        self.window = window
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]
        if len(self._requests[key]) >= self.max_requests:
            return False
        self._requests[key].append(now)
        return True


_rate_limiter = RateLimiter()


class AuthMiddleware(BaseHTTPMiddleware):
    EXEMPT_PATHS = {"/health", "/", "/docs", "/openapi.json", "/redoc"}
    EXEMPT_PREFIXES = ("/assets", "/api/auth/login", "/api/auth/register")
    WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def __init__(self, app, memory: Any | None = None):
        super().__init__(app)
        self._memory = memory  # optional — for per-user nxk_ key lookups

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in self.EXEMPT_PATHS or any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)

        ctx = resolve_auth(request, self._memory)

        # Decide whether this deployment requires auth at all
        any_auth_configured = bool(API_KEY or READONLY_KEY) or (
            self._memory is not None and getattr(self._memory, "users", None) is not None
        )

        if any_auth_configured and ctx is None:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing credentials"})

        # Admin check for write operations on the chat path is permissive
        # (chat writes are agent-driven, not user-driven). Other write paths
        # require admin unless the caller is an authenticated user.
        if ctx is not None and ctx.role == "readonly" and request.method in self.WRITE_METHODS:
            if not path.startswith("/api/chat"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Read-only credentials cannot perform write operations"},
                )

        # Stash the resolved context so endpoints can use it without re-parsing
        request.state.auth = ctx

        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.is_allowed(client_ip):
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

        return await call_next(request)


class WSAuthMiddleware:
    def __init__(self):
        self._ws_rate_limiter = RateLimiter(max_requests=20, window=60)

    def authenticate(self, token: str | None) -> bool:
        if not API_KEY and not READONLY_KEY:
            return True
        # Try JWT first
        if token and token.count(".") == 2:
            if verify_token(token) is not None:
                return True
        # Then legacy env keys
        if resolve_key(token) is not None:
            return True
        return False

    def is_rate_limited(self, client_id: str) -> bool:
        return not self._ws_rate_limiter.is_allowed(client_id)


ws_auth = WSAuthMiddleware()
