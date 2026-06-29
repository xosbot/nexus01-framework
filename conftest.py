"""Root conftest: ensure the project root is on sys.path so test modules can
`from core import ...`, `from tools import ...`, `from integrations import ...`
without requiring `PYTHONPATH=.` in the shell.

Also installs defensive defaults so a fresh clone can run `pytest tests/`
without exporting anything first. Critically, we do NOT set NEXUS_API_KEY —
the auth middleware is intentionally permissive when no key is configured,
which is the correct default for the test suite.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

# Repo root = parent of this conftest.py
_ROOT = pathlib.Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Force the in-memory bus so tests never reach for a live Redis.
os.environ.setdefault("NEXUS_BUS_BACKEND", "inmemory")

# Make sure API key / readonly key are unset (the auth middleware is
# permissive when both are None — which is what the test suite relies on).
os.environ.pop("NEXUS_API_KEY", None)
os.environ.pop("NEXUS_READONLY_KEY", None)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear the global in-memory rate limiter between tests.

    Without this, the limiter (30 req / 60s per IP) accumulates across the
    whole test run and eventually starts returning 429 in the last few tests
    that use the FastAPI TestClient (which always uses the same client IP).
    """
    try:
        from api.auth import _rate_limiter
        _rate_limiter._requests.clear()
    except Exception:
        pass
    try:
        from api.auth import ws_auth
        ws_auth._ws_rate_limiter._requests.clear()
    except Exception:
        pass
    yield
    # Also clear after, so back-to-back runs in the same process start fresh
    try:
        from api.auth import _rate_limiter
        _rate_limiter._requests.clear()
    except Exception:
        pass
