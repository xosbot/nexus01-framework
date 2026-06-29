"""Tests for /api/chat/stream with Phase 1 enabled (agent loop + memory).

Constructs a minimal NexusApp in-process with mocked LLM/router/tools to verify
the SSE event flow. Does NOT exercise real LLM calls.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from api.server import create_api_app
from core.agent_loop import AgentLoop
from core.llm_router import LLMResponse, ToolCall
from core.memory_extractor import MemoryExtractor
from core.memory_recall import MemoryRecall
from core.second_brain import SecondBrain
from core.tool_registry import ToolRegistry


class FakeMemory:
    """Minimal stand-in for core.memory.Memory that doesn't touch the real DB."""

    class _Sessions:
        def __init__(self):
            self._store: dict[str, dict] = {}
            self._counter = 0

        def create(self, title: str = "", project_id: str | None = None, channel: str = "web") -> dict:
            self._counter += 1
            sid = f"sess_{self._counter}"
            self._store[sid] = {"id": sid, "title": title, "project_id": project_id, "channel": channel}
            return self._store[sid]

        def touch(self, sid: str) -> None:
            pass

    def __init__(self) -> None:
        self.sessions = FakeMemory._Sessions()
        self._conversations: list[dict] = []

    def get_context(self, agent: str, last_n: int = 10, session_id: str | None = None) -> list[dict[str, str]]:
        return []

    def save_conversation(self, agent: str, role: str, content: str, session_id: str | None = None) -> None:
        self._conversations.append({"agent": agent, "role": role, "content": content, "session_id": session_id})


class FakeGateway:
    def __init__(self):
        self._channels: dict[str, Any] = {}

    async def handle(self, inbound):
        return MagicMock(text="ok", success=True)

    def get_channel(self, name: str):
        return self._channels.get(name)

    def register_channel(self, channel: Any) -> None:
        self._channels[channel.name if hasattr(channel, "name") else str(channel)] = channel

    def handle_webhook(self, *args, **kwargs):
        return MagicMock(text="webhook ok", success=True)


class FakeLLM:
    """Mock NexusLLM — only stream() and complete() are called by the test."""

    def __init__(self) -> None:
        self._router = MagicMock()
        self._router.complete_with_tools = AsyncMock()
        self._router.complete_messages = AsyncMock()
        self.complete_calls: list[Any] = []
        self.stream_calls: list[Any] = []

    @property
    def router(self) -> MagicMock:
        return self._router

    async def stream(self, messages, **kwargs):
        self.stream_calls.append(messages)
        # Yield a simple text response in chunks
        for word in "hello there".split():
            yield word + " "

    async def complete(self, messages, **kwargs) -> str:
        self.complete_calls.append(messages)
        return "extracted facts"

    async def close(self) -> None:
        pass


@pytest.fixture
def nexus_app_factory(tmp_path: Path):
    """Factory that builds a minimal NexusApp with Phase 1 enabled."""
    created: list[Any] = []

    def factory(*, llm_response_factory=None, rag_hits=None, brain_with=None, tools=None):
        from dataclasses import dataclass

        memory = FakeMemory()
        llm = FakeLLM()
        if llm_response_factory:
            llm._router.complete_with_tools = AsyncMock(side_effect=llm_response_factory)
            llm._router.complete_messages = AsyncMock(side_effect=llm_response_factory)
        rag = MagicMock()
        rag.search = MagicMock(return_value=rag_hits or [])
        rag.stats = MagicMock(return_value={})
        gateway = FakeGateway()

        # Phase 1 components
        second_brain = SecondBrain(db_path=tmp_path / f"memory_{len(created)}.db")
        if brain_with:
            for kw in brain_with:
                second_brain.add_memory(**kw)
        recall = MemoryRecall(second_brain)
        extractor = MemoryExtractor(llm, second_brain)
        chat_tools_reg = tools or ToolRegistry()
        agent_loop = AgentLoop(llm._router, chat_tools_reg, memory)  # type: ignore[arg-type]

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

        app = App(
            llm=llm, memory=memory, rag=rag, gateway=gateway,
            channels=[], bus=MagicMock(), cost_tracker=MagicMock(),
            second_brain=second_brain, recall=recall, extractor=extractor,
            chat_tools=chat_tools_reg, chat_agent_loop=agent_loop,
            cold_mode=MagicMock(),
        )
        created.append(app)
        return app

    return factory


def _parse_sse(response_text: str) -> list[dict]:
    """Parse SSE `data: {json}\\n\\n` lines into dicts."""
    events = []
    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return events


# ── Without Phase 1 tools (legacy direct LLM path) ───────────────────────


def test_legacy_path_streams_chunks_and_done(nexus_app_factory) -> None:
    """Build a minimal app WITHOUT chat_agent_loop to hit the legacy direct-LLM path."""
    from dataclasses import dataclass
    memory = FakeMemory()
    llm = FakeLLM()
    rag = MagicMock()
    rag.search = MagicMock(return_value=[])
    rag.stats = MagicMock(return_value={})
    gateway = FakeGateway()

    @dataclass
    class App:
        llm: Any
        memory: Any
        rag: Any
        gateway: Any
        channels: list
        bus: Any
        cost_tracker: Any

    legacy_app = App(
        llm=llm, memory=memory, rag=rag, gateway=gateway, channels=[],
        bus=MagicMock(), cost_tracker=MagicMock(),
    )

    api = create_api_app(legacy_app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")
    try:
        async def run():
            return await client.post("/api/chat/stream", json={"message": "hi", "session_id": None})
        resp = asyncio.run(run())
    finally:
        asyncio.run(client.aclose())
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    # Legacy path: just chunk + done (no memory_recall, no agent_iteration)
    assert "chunk" in types
    assert "done" in types
    assert "agent_iteration" not in types
    assert "memory_recall" not in types


# ── With Phase 1: memory_recall event ─────────────────────────────────────


def test_phase1_emits_memory_recall_event(nexus_app_factory) -> None:
    """When memories exist for the query, the SSE stream emits memory_recall first."""
    app = nexus_app_factory(
        llm_response_factory=lambda *a, **kw: LLMResponse(content="hi"),
        brain_with=[{"type": "project", "content": "NEXUS-01 is a framework",
                     "confidence": 0.9, "importance": 0.9, "durability": 0.9,
                     "source_session_id": "s", "source_quote": "q"}],
    )
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")

    async def run():
        return await client.post("/api/chat/stream", json={"message": "NEXUS-01", "session_id": None})
    resp = asyncio.run(run())
    asyncio.run(client.aclose())
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    recall_events = [e for e in events if e["type"] == "memory_recall"]
    assert len(recall_events) == 1
    assert "NEXUS-01" in recall_events[0]["memories"][0]["content"]


# ── With Phase 1: no memories → no memory_recall event ────────────────────


def test_phase1_no_memories_no_memory_recall_event(nexus_app_factory) -> None:
    app = nexus_app_factory(
        llm_response_factory=lambda *a, **kw: LLMResponse(content="hi"),
        brain_with=[],
    )
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")

    async def run():
        return await client.post("/api/chat/stream", json={"message": "anything", "session_id": None})
    resp = asyncio.run(run())
    asyncio.run(client.aclose())
    events = _parse_sse(resp.text)
    assert not any(e["type"] == "memory_recall" for e in events)


# ── With Phase 1: tool call → tool_started/finished events ────────────────


def test_phase1_emits_tool_events(nexus_app_factory) -> None:
    """When LLM requests a tool, the stream emits tool_started/finished."""

    tools = ToolRegistry()

    async def echo_tool(text: str) -> str:
        return f"echo: {text}"

    tools.register(echo_tool, name="echo_tool",
                   parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]})

    call_log: list[Any] = []

    def llm_factory(*args, **kwargs):
        call_log.append(args)
        if len(call_log) == 1:
            return LLMResponse(content="", tool_calls=[ToolCall(id="tc1", name="echo_tool", arguments='{"text":"hi"}')])
        return LLMResponse(content="done after tool")

    app = nexus_app_factory(llm_response_factory=llm_factory, tools=tools)
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")

    async def run():
        return await client.post("/api/chat/stream", json={"message": "use tool", "session_id": None})
    resp = asyncio.run(run())
    asyncio.run(client.aclose())
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert "tool_started" in types
    assert "tool_finished" in types
    finished = next(e for e in events if e["type"] == "tool_finished")
    assert finished["ok"] is True
    assert "echo: hi" in finished["content"]


# ── Slash command still works ─────────────────────────────────────────────


def test_slash_command_returns_command_event(nexus_app_factory) -> None:
    app = nexus_app_factory()
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")

    async def run():
        return await client.post("/api/chat/stream", json={"message": "/help", "session_id": None})
    resp = asyncio.run(run())
    asyncio.run(client.aclose())
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert "command" in types
    assert "done" in types


# ── Tool approval endpoint ────────────────────────────────────────────────


def test_approve_denied_returns_denied(nexus_app_factory) -> None:
    from core import chat_tools
    app = nexus_app_factory()
    # Pre-populate a pending execution
    chat_tools._PENDING_EXECUTIONS["apr_test"] = {"cmd": "ls", "permission": "READ", "session_id": "s1", "ts": 0}
    api = create_api_app(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")

    async def run():
        return await client.post("/api/chat/approve", json={"approval_id": "apr_test", "approved": False, "session_id": "s1"})
    resp = asyncio.run(run())
    asyncio.run(client.aclose())
    data = resp.json()
    assert data["success"] is False
    assert "apr_test" not in chat_tools._PENDING_EXECUTIONS
