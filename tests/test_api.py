"""Tests for api/server.py.

The `client` fixture builds a minimal mocked NexusApp so the API routes are
exercised without spinning up Ollama, Redis, ChromaDB, or a real SQLite file.
Each test gets a fresh in-memory data dir (via the conftest.py default).

If you need a full integration test (real LLM, real DB), use the headless
browser E2E in tests/test_browser.py — not this module.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.auth import AuthMiddleware
from api.server import create_api_app


def _build_mock_nexus() -> SimpleNamespace:
    """Return a NexusApp-shaped object with stubs for everything the API reads.

    The real `core.app.create_app` instantiates Ollama, ChromaDB, SQLite, and
    Redis — far too heavy for a unit test of the HTTP layer. This mock keeps
    the API contract tested without the infrastructure cost.
    """
    # Memory stub: needs .stats(), .projects.create(), .sessions.create()
    memory = MagicMock(name="memory")
    memory.stats.return_value = {
        "sessions": 0,
        "conversations": 0,
        "knowledge": 0,
        "by_agent": {},
    }

    def _fake_create_project(name: str, description: str = "") -> dict:
        return {"id": "proj-1", "name": name, "description": description}

    def _fake_create_session(title: str, project_id: str | None = None, channel: str = "web") -> dict:
        return {"id": "sess-1", "title": title, "project_id": project_id, "channel": channel}

    # The API accesses memory.projects.create / memory.sessions.create
    memory.projects = MagicMock()
    memory.projects.create.side_effect = _fake_create_project
    memory.sessions = MagicMock()
    memory.sessions.create.side_effect = _fake_create_session

    # LLM stub: needs .provider_status(), .stats()
    llm = MagicMock(name="llm")
    llm.provider_status.return_value = [{"name": "ollama", "available": True}]
    llm.stats.return_value = {"total_tokens": 0, "total_cost": 0.0}

    # RAG stub
    rag = MagicMock(name="rag")
    rag.stats.return_value = {"documents": 0, "chunks": 0}

    # Gateway stub
    gateway = MagicMock(name="gateway")

    # Channels: empty list is fine for these tests
    nexus = SimpleNamespace(
        gateway=gateway,
        memory=memory,
        llm=llm,
        rag=rag,
        channels=[],
        brain=None,
        copilot=None,
        integrations=None,
        proactive=None,
        social_media=None,
    )
    return nexus


@pytest.fixture
def client():
    nexus = _build_mock_nexus()
    app = create_api_app(nexus)
    # The /health endpoint is exempt from auth, so no API key needed
    return TestClient(app)


@pytest.fixture
def authed_client():
    """Same as `client` but sends a valid API key on every request."""
    nexus = _build_mock_nexus()
    app = create_api_app(nexus)
    return TestClient(app, headers={"X-API-Key": "test-api-key-not-secret"})


def test_auth_rejects_unauthenticated_when_only_readonly_key_set():
    """Regression: auth must not fail open when only NEXUS_READONLY_KEY is set."""
    import api.auth as auth_mod

    original_api_key = auth_mod.API_KEY
    original_readonly_key = auth_mod.READONLY_KEY
    try:
        auth_mod.API_KEY = None
        auth_mod.READONLY_KEY = auth_mod._parse_key("read:readonlytest123")

        assert auth_mod.API_KEY is None
        assert auth_mod.READONLY_KEY is not None

        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route

        async def dummy_endpoint(request):
            return JSONResponse({"ok": True})

        test_app = Starlette(
            routes=[Route("/test", dummy_endpoint)],
            middleware=[__import__("starlette.middleware", fromlist=["Middleware"]).Middleware(AuthMiddleware)],
        )

        test_client = TestClient(test_app, raise_server_exceptions=False)

        r = test_client.get("/test")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    finally:
        auth_mod.API_KEY = original_api_key
        auth_mod.READONLY_KEY = original_readonly_key


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"


def test_system_status(authed_client):
    r = authed_client.get("/api/system/status")
    assert r.status_code == 200
    data = r.json()
    assert "agents" in data
    assert "memory" in data
    assert "channels" in data
    assert "bus_backend" in data


def test_create_project(authed_client):
    r = authed_client.post("/api/projects", json={"name": "Test Project", "description": "demo"})
    assert r.status_code == 200
    assert r.json()["name"] == "Test Project"


def test_create_session(authed_client):
    r = authed_client.post("/api/sessions", json={"title": "Test Session"})
    assert r.status_code == 200
    assert r.json()["title"] == "Test Session"
