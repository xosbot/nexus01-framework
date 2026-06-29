"""Tests for core/agent_loop.py:stream()."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent_loop import AgentLoop
from core.llm_router import LLMResponse, ToolCall
from core.tool_registry import ToolRegistry


class FakeMemory:
    def get_context(self, *args: Any, **kwargs: Any) -> list[dict[str, str]]:
        return []


def _response(text: str = "", tool_calls: list[ToolCall] | None = None) -> LLMResponse:
    return LLMResponse(content=text, tool_calls=tool_calls or [], finish_reason="stop")


def _tool_call(name: str, args: str, tc_id: str = "tc1") -> ToolCall:
    return ToolCall(id=tc_id, name=name, arguments=args)


@pytest.fixture
def router() -> MagicMock:
    r = MagicMock()
    r.complete_with_tools = AsyncMock()
    r.complete_messages = AsyncMock()
    return r


@pytest.fixture
def tools() -> ToolRegistry:
    reg = ToolRegistry()
    return reg


# ── No tool use ───────────────────────────────────────────────────────────


async def test_stream_no_tool_use_emits_chunk_and_done(router: MagicMock, tools: ToolRegistry) -> None:
    router.complete_with_tools = AsyncMock(return_value=_response("Hello there"))
    router.complete_messages = AsyncMock(return_value=_response("Hello there"))
    loop = AgentLoop(router, tools, FakeMemory())  # type: ignore[arg-type]
    events = []
    async for e in loop.stream([{"role": "user", "content": "hi"}]):
        events.append(e)
    types = [e["type"] for e in events]
    assert "agent_iteration" in types
    assert "chunk" in types
    assert "done" in types
    assert any(e["type"] == "done" and e["iterations"] == 1 for e in events)
    chunk = next(e for e in events if e["type"] == "chunk")
    assert chunk["content"] == "Hello there"


async def test_stream_empty_response_no_chunk(router: MagicMock, tools: ToolRegistry) -> None:
    router.complete_with_tools = AsyncMock(return_value=_response(""))
    router.complete_messages = AsyncMock(return_value=_response(""))
    loop = AgentLoop(router, tools, FakeMemory())  # type: ignore[arg-type]
    events = []
    async for e in loop.stream([{"role": "user", "content": "hi"}]):
        events.append(e)
    chunks = [e for e in events if e["type"] == "chunk"]
    assert chunks == []  # empty response → no chunk
    done = next(e for e in events if e["type"] == "done")
    assert done["content"] == ""


# ── Single tool call ──────────────────────────────────────────────────────


async def test_stream_one_tool_call_then_done(router: MagicMock, tools: ToolRegistry) -> None:
    async def my_tool(q: str) -> str:
        return f"result for {q}"

    tools.register(my_tool, name="my_tool",
                   parameters={"type": "object", "properties": {"q": {"type": "string"}}})

    router.complete_with_tools = AsyncMock(side_effect=[
        _response("", tool_calls=[_tool_call("my_tool", '{"q":"hello"}')]),
        _response("Final answer after tool"),
    ])
    loop = AgentLoop(router, tools, FakeMemory())  # type: ignore[arg-type]
    events = []
    async for e in loop.stream([{"role": "user", "content": "do it"}]):
        events.append(e)
    types = [e["type"] for e in events]
    assert types.count("agent_iteration") == 2
    assert "tool_started" in types
    assert "tool_finished" in types
    done = next(e for e in events if e["type"] == "done")
    assert done["content"] == "Final answer after tool"
    assert done["iterations"] == 2
    finished = next(e for e in events if e["type"] == "tool_finished")
    assert finished["ok"] is True
    assert "result for hello" in finished["content"]


# ── Multiple parallel tool calls ──────────────────────────────────────────


async def test_stream_parallel_tool_calls(router: MagicMock, tools: ToolRegistry) -> None:
    async def t1() -> str: return "a"
    async def t2() -> str: return "b"
    tools.register(t1, name="t1")
    tools.register(t2, name="t2")
    router.complete_with_tools = AsyncMock(side_effect=[
        _response("", tool_calls=[_tool_call("t1", "{}", "tc1"),
                                   _tool_call("t2", "{}", "tc2")]),
        _response("done"),
    ])
    loop = AgentLoop(router, tools, FakeMemory())  # type: ignore[arg-type]
    events = []
    async for e in loop.stream([{"role": "user", "content": "x"}]):
        events.append(e)
    started = [e for e in events if e["type"] == "tool_started"]
    finished = [e for e in events if e["type"] == "tool_finished"]
    assert len(started) == 2
    assert len(finished) == 2


# ── Max iterations ────────────────────────────────────────────────────────


async def test_stream_max_iterations_emits_error(router: MagicMock, tools: ToolRegistry) -> None:
    async def loop_tool() -> str: return "loop"
    tools.register(loop_tool, name="loop_tool")
    # Always returns a tool call — never converges
    router.complete_with_tools = AsyncMock(return_value=_response(
        "", tool_calls=[_tool_call("loop_tool", "{}", "tc1")],
    ))
    loop = AgentLoop(router, tools, FakeMemory(), max_iterations=3)  # type: ignore[arg-type]
    events = []
    async for e in loop.stream([{"role": "user", "content": "x"}], max_iterations=3):
        events.append(e)
    errors = [e for e in events if e["type"] == "error"]
    assert any("Max iterations" in e["error"] for e in errors)


# ── Cold-mode approval ────────────────────────────────────────────────────


async def test_stream_cold_mode_blocked_emits_approval_requested(router: MagicMock, tools: ToolRegistry) -> None:
    async def gated() -> dict:
        return {"needs_approval": True, "approval_id": "apr_xyz", "description": "needs ok"}

    tools.register(gated, name="gated")
    router.complete_with_tools = AsyncMock(return_value=_response(
        "", tool_calls=[_tool_call("gated", "{}", "tc1")],
    ))
    loop = AgentLoop(router, tools, FakeMemory())  # type: ignore[arg-type]
    events = []
    async for e in loop.stream([{"role": "user", "content": "x"}]):
        events.append(e)
    types = [e["type"] for e in events]
    assert "tool_blocked" in types
    assert "approval_requested" in types
    appr = next(e for e in events if e["type"] == "approval_requested")
    assert appr["approval_id"] == "apr_xyz"
    assert appr["tool"] == "gated"
    # Loop stops — error event
    assert any(e["type"] == "error" for e in events)


# ── Tool error ────────────────────────────────────────────────────────────


async def test_stream_tool_error_feeds_back_to_llm(router: MagicMock, tools: ToolRegistry) -> None:
    async def bad() -> str:
        raise RuntimeError("kaboom")

    tools.register(bad, name="bad")
    router.complete_with_tools = AsyncMock(side_effect=[
        _response("", tool_calls=[_tool_call("bad", "{}", "tc1")]),
        _response("Handled the error"),
    ])
    loop = AgentLoop(router, tools, FakeMemory())  # type: ignore[arg-type]
    events = []
    async for e in loop.stream([{"role": "user", "content": "x"}]):
        events.append(e)
    finished = next(e for e in events if e["type"] == "tool_finished")
    assert finished["ok"] is False
    assert "kaboom" in finished["content"]
    # Second LLM call was made
    assert router.complete_with_tools.await_count == 2


# ── LLM error ─────────────────────────────────────────────────────────────


async def test_stream_llm_error_emits_error_event(router: MagicMock, tools: ToolRegistry) -> None:
    router.complete_messages = AsyncMock(side_effect=RuntimeError("LLM down"))
    loop = AgentLoop(router, tools, FakeMemory())  # type: ignore[arg-type]
    events = []
    async for e in loop.stream([{"role": "user", "content": "x"}]):
        events.append(e)
    errors = [e for e in events if e["type"] == "error"]
    assert errors
    assert "LLM down" in errors[0]["error"]


# ── No tools registered ──────────────────────────────────────────────────


async def test_stream_no_tools_uses_complete_messages(router: MagicMock, tools: ToolRegistry) -> None:
    router.complete_messages = AsyncMock(return_value=_response("Plain answer"))
    loop = AgentLoop(router, tools, FakeMemory())  # type: ignore[arg-type]
    events = []
    async for e in loop.stream([{"role": "user", "content": "x"}]):
        events.append(e)
    router.complete_messages.assert_awaited()
    done = next(e for e in events if e["type"] == "done")
    assert done["content"] == "Plain answer"


# ── System message injection ──────────────────────────────────────────────


async def test_stream_injects_system_message_if_missing(router: MagicMock, tools: ToolRegistry) -> None:
    router.complete_messages = AsyncMock(return_value=_response("ok"))
    loop = AgentLoop(router, tools, FakeMemory())  # type: ignore[arg-type]
    async for _ in loop.stream([{"role": "user", "content": "x"}]):
        pass
    # Verify the system message was prepended
    call_args = router.complete_messages.await_args
    msgs = call_args.kwargs.get("messages") or call_args.args[0]
    assert msgs[0]["role"] == "system"
