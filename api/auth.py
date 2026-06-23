"""API authentication — scoped API keys with admin/read-only tiers + rate limiting."""

from __future__ import annotations

import hmac
import os
import time
import logging
from collections import defaultdict
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

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
    WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in self.EXEMPT_PATHS or path.startswith("/assets"):
            return await call_next(request)

        # Extract token
        auth = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-API-Key", "")
        token = ""
        if auth.startswith("Bearer "):
            token = auth[7:]
        elif api_key_header:
            token = api_key_header

        key = resolve_key(token) if token else None

        if (API_KEY or READONLY_KEY) and not key:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

        # Admin check for write operations
        if key and key.role != "admin" and request.method in self.WRITE_METHODS and not path.startswith("/api/chat"):
            return JSONResponse(status_code=403, content={"detail": "Read-only key cannot perform write operations"})

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
        key = resolve_key(token) if token else None
        return key is not None

    def is_rate_limited(self, client_id: str) -> bool:
        return not self._ws_rate_limiter.is_allowed(client_id)


ws_auth = WSAuthMiddleware()
