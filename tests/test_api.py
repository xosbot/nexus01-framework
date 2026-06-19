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
