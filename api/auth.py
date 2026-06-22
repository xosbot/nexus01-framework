"""API authentication and rate limiting middleware."""

from __future__ import annotations

import os
import time
import logging
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

API_KEY = os.getenv("NEXUS_API_KEY", "")
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30


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

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in self.EXEMPT_PATHS or path.startswith("/assets"):
            return await call_next(request)

        if API_KEY:
            auth_header = request.headers.get("Authorization", "")
            api_key_header = request.headers.get("X-API-Key", "")

            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            elif api_key_header:
                token = api_key_header
            else:
                token = ""

            if token != API_KEY:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key"},
                )

        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.is_allowed(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )

        return await call_next(request)


class WSAuthMiddleware:
    def __init__(self):
        self._ws_rate_limiter = RateLimiter(max_requests=20, window=60)

    def authenticate(self, token: str | None) -> bool:
        if not API_KEY:
            return True
        return token == API_KEY

    def is_rate_limited(self, client_id: str) -> bool:
        return not self._ws_rate_limiter.is_allowed(client_id)


ws_auth = WSAuthMiddleware()
