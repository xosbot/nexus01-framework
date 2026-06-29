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
