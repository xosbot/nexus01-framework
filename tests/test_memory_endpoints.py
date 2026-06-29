"""Tests for the /api/memory/* endpoints (Phase 1)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from api.server import create_api_app
from core.memory_recall import MemoryRecall
from core.second_brain import SecondBrain


class FakeMemory:
    class _Sessions:
        def create(self, **kwargs): return {"id": "sess_test"}
        def touch(self, sid): pass
    def __init__(self):
        self.sessions = FakeMemory._Sessions()
    def get_context(self, *a, **k): return []
    def save_conversation(self, *a, **k): pass


class FakeLLM:
    def __init__(self):
        self._router = MagicMock()
        self._router.complete_with_tools = MagicMock()
        self._router.complete_messages = MagicMock()
    @property
    def router(self):
        return self._router
    async def stream(self, *a, **k):
        for w in "hi".split():
            yield w
    async def complete(self, *a, **k):
        return ""
    async def close(self):
        pass


class FakeGateway:
    async def handle(self, *a, **k): return MagicMock(text="ok", success=True)
    def get_channel(self, name): return None
    def register_channel(self, ch): pass


@pytest.fixture
def app_with_brain(tmp_path: Path):
    """NexusApp with second_brain populated for testing endpoints."""
    @dataclass
    class App:
        llm: Any
        memory: Any
        rag: Any
        gateway: Any
        channels: list
        bus: Any
        cost_tracker: Any
        second_brain: Any
        recall: Any
        extractor: Any
        chat_tools: Any
        chat_agent_loop: Any
        cold_mode: Any
        memory_extraction_enabled: bool = True

    brain = SecondBrain(db_path=tmp_path / "memory.db")
    llm = FakeLLM()
    app = App(
        llm=llm, memory=FakeMemory(), rag=MagicMock(), gateway=FakeGateway(),
        channels=[], bus=MagicMock(), cost_tracker=MagicMock(),
        second_brain=brain, recall=MemoryRecall(brain), extractor=MagicMock(),
        chat_tools=MagicMock(), chat_agent_loop=None, cold_mode=MagicMock(),
    )
    return app, brain


def _post(client, path, body=None):
    return asyncio.run(client.post(path, json=body or {}))

def _put(client, path, body=None):
    return asyncio.run(client.put(path, json=body or {}))

def _get(client, path):
    return asyncio.run(client.get(path))

def _delete(client, path):
    return asyncio.run(client.delete(path))


def test_get_core_blocks_empty(app_with_brain) -> None:
    app, brain = app_with_brain
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _get(client, "/api/memory/core")
    finally:
        asyncio.run(client.aclose())
    assert resp.status_code == 200
    assert resp.json() == {"blocks": {}, "enabled": True}


def test_set_and_get_core_block(app_with_brain) -> None:
    app, brain = app_with_brain
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _put(client, "/api/memory/core/user", {"value": "I am a dev"})
    finally:
        asyncio.run(client.aclose())
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["block"]["value"] == "I am a dev"

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _get(client, "/api/memory/core")
    finally:
        asyncio.run(client.aclose())
    assert resp.json()["blocks"]["user"] == "I am a dev"


def test_set_core_block_invalid_label(app_with_brain) -> None:
    app, brain = app_with_brain
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _put(client, "/api/memory/core/bogus", {"value": "x"})
    finally:
        asyncio.run(client.aclose())
    assert resp.status_code == 400


def test_list_memories_empty(app_with_brain) -> None:
    app, brain = app_with_brain
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _get(client, "/api/memory/list")
    finally:
        asyncio.run(client.aclose())
    assert resp.json()["memories"] == []


def test_list_memories_filters_by_status(app_with_brain) -> None:
    app, brain = app_with_brain
    brain.add_memory(type="preference", content="active", confidence=0.9,
                    importance=0.5, durability=0.5)
    brain.add_memory(type="preference", content="pending", confidence=0.65,
                    importance=0.5, durability=0.5)
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp_active = _get(client, "/api/memory/list?status=active")
        resp_pending = _get(client, "/api/memory/pending")
    finally:
        asyncio.run(client.aclose())
    assert len(resp_active.json()["memories"]) == 1
    assert resp_active.json()["memories"][0]["content"] == "active"
    assert len(resp_pending.json()["memories"]) == 1
    assert resp_pending.json()["memories"][0]["status"] == "pending"


def test_approve_pending_memory(app_with_brain) -> None:
    app, brain = app_with_brain
    m = brain.add_memory(type="preference", content="approve me", confidence=0.65,
                        importance=0.5, durability=0.5)
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _post(client, f"/api/memory/{m['id']}/approve")
    finally:
        asyncio.run(client.aclose())
    assert resp.status_code == 200
    assert brain.get(m["id"])["status"] == "active"


def test_reject_pending_memory(app_with_brain) -> None:
    app, brain = app_with_brain
    m = brain.add_memory(type="preference", content="reject me", confidence=0.65,
                        importance=0.5, durability=0.5)
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        _post(client, f"/api/memory/{m['id']}/reject")
    finally:
        asyncio.run(client.aclose())
    assert brain.get(m["id"])["status"] == "rejected"


def test_pin_memory(app_with_brain) -> None:
    app, brain = app_with_brain
    m = brain.add_memory(type="preference", content="pin me", confidence=0.9,
                        importance=0.5, durability=0.5)
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        _post(client, f"/api/memory/{m['id']}/pin", {"pinned": True})
    finally:
        asyncio.run(client.aclose())
    assert brain.get(m["id"])["pinned"] == 1


def test_delete_memory(app_with_brain) -> None:
    app, brain = app_with_brain
    m = brain.add_memory(type="preference", content="delete me", confidence=0.9,
                        importance=0.5, durability=0.5)
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _delete(client, f"/api/memory/{m['id']}")
    finally:
        asyncio.run(client.aclose())
    assert resp.status_code == 200
    assert brain.get(m["id"]) is None


def test_delete_nonexistent_returns_404(app_with_brain) -> None:
    app, brain = app_with_brain
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _delete(client, "/api/memory/mem_doesnotexist")
    finally:
        asyncio.run(client.aclose())
    assert resp.status_code == 404


def test_audit_endpoint(app_with_brain) -> None:
    app, brain = app_with_brain
    m = brain.add_memory(type="preference", content="audit", confidence=0.9,
                        importance=0.5, durability=0.5)
    brain.delete_memory(m["id"])
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _get(client, "/api/memory/audit")
    finally:
        asyncio.run(client.aclose())
    data = resp.json()
    ops = {e["op"] for e in data["entries"]}
    assert "add" in ops
    assert "delete" in ops


def test_stats_endpoint(app_with_brain) -> None:
    app, brain = app_with_brain
    brain.add_memory(type="preference", content="x", confidence=0.9, importance=0.5, durability=0.5)
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp = _get(client, "/api/memory/stats")
    finally:
        asyncio.run(client.aclose())
    data = resp.json()
    assert data["enabled"] is True
    assert data["total"] == 1


def test_get_memory_by_id(app_with_brain) -> None:
    app, brain = app_with_brain
    m = brain.add_memory(type="preference", content="get me", confidence=0.9,
                        importance=0.5, durability=0.5)
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        resp_ok = _get(client, f"/api/memory/{m['id']}")
        resp_404 = _get(client, "/api/memory/mem_missing")
    finally:
        asyncio.run(client.aclose())
    assert resp_ok.status_code == 200
    assert resp_ok.json()["content"] == "get me"
    assert resp_404.status_code == 404
