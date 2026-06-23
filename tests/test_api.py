import os
import pytest
from fastapi.testclient import TestClient

from config import Config
from core.app import create_app
from api.server import create_api_app


@pytest.fixture
def client():
    import asyncio
    cfg = Config()
    cfg.enable_web_ui = True
    cfg.telegram_token = ""
    cfg.enabled_channels = []

    async def _setup():
        return await create_app(cfg)

    nexus = asyncio.run(_setup())
    return TestClient(create_api_app(nexus))


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

        from starlette.testclient import TestClient
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.middleware import Middleware

        async def dummy_endpoint(request):
            return JSONResponse({"ok": True})

        app = Starlette(
            routes=[Route("/test", dummy_endpoint)],
            middleware=[Middleware(auth_mod.AuthMiddleware)],
        )

        client = TestClient(app, raise_server_exceptions=False)

        r = client.get("/test")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"
    finally:
        auth_mod.API_KEY = original_api_key
        auth_mod.READONLY_KEY = original_readonly_key


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_system_status(client):
    r = client.get("/api/system/status")
    assert r.status_code == 200
    data = r.json()
    assert "agents" in data
    assert "memory" in data


def test_create_project(client):
    r = client.post("/api/projects", json={"name": "Test Project", "description": "demo"})
    assert r.status_code == 200
    assert r.json()["name"] == "Test Project"


def test_create_session(client):
    r = client.post("/api/sessions", json={"title": "Test Session"})
    assert r.status_code == 200
    assert r.json()["title"] == "Test Session"
