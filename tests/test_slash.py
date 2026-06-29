"""Tests for core/slash.py — including new Phase 1 memory + tools commands."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core import slash
from core.second_brain import SecondBrain


# ── /help / /clear / legacy /memory (legacy search) ──────────────────────


async def test_help_lists_commands() -> None:
    result = await slash.cmd_help([], "s1", {})
    assert result.ok
    assert "/help" in result.text
    assert "/memory" in result.text
    assert "/remember" in result.text
    assert "/tools" in result.text
    assert "/who" in result.text


async def test_dispatch_help() -> None:
    result = await slash.dispatch("/help", "s1", {})
    assert result is not None
    assert result.ok


async def test_dispatch_unknown_command() -> None:
    result = await slash.dispatch("/nonexistent", "s1", {})
    assert result is not None
    assert not result.ok
    assert "Unknown command" in result.text


async def test_dispatch_non_slash_returns_none() -> None:
    result = await slash.dispatch("just a message", "s1", {})
    assert result is None


async def test_clear() -> None:
    result = await slash.cmd_clear([], "s1", {})
    assert result.ok
    assert result.side_effect == "new_session"


# ── /memory subcommands (second brain) ────────────────────────────────────


@pytest.fixture
def brain_ctx(tmp_path: Path) -> tuple[dict, SecondBrain]:
    brain = SecondBrain(db_path=tmp_path / "memory.db")
    nexus = MagicMock()
    nexus.second_brain = brain
    return {"nexus_app": nexus}, brain


async def test_memory_no_args_shows_summary(brain_ctx) -> None:
    ctx, brain = brain_ctx
    brain.add_memory(type="preference", content="a", confidence=0.9, importance=0.5, durability=0.5)
    result = await slash.dispatch("/memory", "s1", ctx)
    assert result.ok
    assert "active:" in result.text
    assert "pending:" in result.text
    assert "preference" in result.text


async def test_memory_no_brain_shows_disabled() -> None:
    result = await slash.dispatch("/memory", "s1", {})
    assert result.ok
    assert "not enabled" in result.text


async def test_memory_list(brain_ctx) -> None:
    ctx, brain = brain_ctx
    brain.add_memory(type="preference", content="a", confidence=0.9, importance=0.5, durability=0.5)
    brain.add_memory(type="identity", content="b", confidence=0.9, importance=0.5, durability=0.5)
    result = await slash.dispatch("/memory list", "s1", ctx)
    assert result.ok
    assert "2" in result.text
    result_pref = await slash.dispatch("/memory list preference", "s1", ctx)
    assert result_pref.ok
    assert "1" in result_pref.text


async def test_memory_show(brain_ctx) -> None:
    ctx, brain = brain_ctx
    m = brain.add_memory(type="preference", content="show me", confidence=0.9,
                        importance=0.5, durability=0.5, source_quote="the quote")
    result = await slash.dispatch(f"/memory show {m['id']}", "s1", ctx)
    assert result.ok
    assert "show me" in result.text
    assert "the quote" in result.text
    assert "preference" in result.text


async def test_memory_show_missing(brain_ctx) -> None:
    ctx, brain = brain_ctx
    result = await slash.dispatch("/memory show mem_missing", "s1", ctx)
    assert not result.ok
    assert "not found" in result.text


async def test_memory_show_no_id(brain_ctx) -> None:
    ctx, brain = brain_ctx
    result = await slash.dispatch("/memory show", "s1", ctx)
    assert not result.ok


async def test_memory_forget(brain_ctx) -> None:
    ctx, brain = brain_ctx
    m = brain.add_memory(type="preference", content="forget me", confidence=0.9,
                        importance=0.5, durability=0.5)
    result = await slash.dispatch(f"/memory forget {m['id']}", "s1", ctx)
    assert result.ok
    assert "Forgot" in result.text
    assert brain.get(m["id"]) is None


async def test_memory_forget_missing(brain_ctx) -> None:
    ctx, brain = brain_ctx
    result = await slash.dispatch("/memory forget mem_nope", "s1", ctx)
    assert not result.ok


async def test_memory_pause_resume(brain_ctx) -> None:
    ctx, brain = brain_ctx
    assert not slash.is_paused("s1")
    r1 = await slash.dispatch("/memory pause", "s1", ctx)
    assert r1.ok
    assert r1.side_effect == "memory_paused"
    assert slash.is_paused("s1")
    r2 = await slash.dispatch("/memory resume", "s1", ctx)
    assert r2.ok
    assert r2.side_effect == "memory_resumed"
    assert not slash.is_paused("s1")


async def test_memory_audit(brain_ctx) -> None:
    ctx, brain = brain_ctx
    brain.add_memory(type="preference", content="audit me", confidence=0.9,
                    importance=0.5, durability=0.5)
    result = await slash.dispatch("/memory audit 5", "s1", ctx)
    assert result.ok
    assert "add" in result.text


# ── /remember, /forget, /tools, /who ──────────────────────────────────────


async def test_remember_stores_memory(brain_ctx) -> None:
    ctx, brain = brain_ctx
    result = await slash.dispatch("/remember I love dark mode", "s1", ctx)
    assert result.ok
    assert "Stored" in result.text
    rows = brain.list_memories(status="active")
    assert any("dark mode" in r["content"] for r in rows)


async def test_remember_empty_text(brain_ctx) -> None:
    ctx, brain = brain_ctx
    result = await slash.dispatch("/remember", "s1", ctx)
    assert not result.ok


async def test_remember_no_brain() -> None:
    result = await slash.dispatch("/remember something", "s1", {})
    assert not result.ok
    assert "not enabled" in result.text


async def test_forget_alias(brain_ctx) -> None:
    ctx, brain = brain_ctx
    m = brain.add_memory(type="preference", content="alias test", confidence=0.9,
                        importance=0.5, durability=0.5)
    result = await slash.dispatch(f"/forget {m['id']}", "s1", ctx)
    assert result.ok
    assert brain.get(m["id"]) is None


async def test_tools_lists_registered() -> None:
    nexus = MagicMock()
    tools = MagicMock()
    tools.tool_names = MagicMock(return_value=["web_search", "exec", "rag_query"])
    tools.as_openai_tools = MagicMock(return_value=[
        {"function": {"name": "web_search", "description": "Search the web"}},
        {"function": {"name": "exec", "description": "Run commands"}},
        {"function": {"name": "rag_query", "description": "Query RAG"}},
    ])
    nexus.chat_tools = tools
    result = await slash.dispatch("/tools", "s1", {"nexus_app": nexus})
    assert result.ok
    assert "web_search" in result.text
    assert "exec" in result.text


async def test_tools_no_phase1() -> None:
    nexus = MagicMock()
    nexus.chat_tools = None
    result = await slash.dispatch("/tools", "s1", {"nexus_app": nexus})
    assert result.ok
    assert "not enabled" in result.text


async def test_who_shows_core_blocks(brain_ctx) -> None:
    ctx, brain = brain_ctx
    brain.set_core_block("user", "I am a developer")
    brain.set_core_block("persona", "Friendly assistant")
    result = await slash.dispatch("/who", "s1", ctx)
    assert result.ok
    assert "developer" in result.text
    assert "Friendly" in result.text


async def test_who_empty(brain_ctx) -> None:
    ctx, brain = brain_ctx
    result = await slash.dispatch("/who", "s1", ctx)
    assert result.ok


async def test_who_no_brain() -> None:
    result = await slash.dispatch("/who", "s1", {})
    assert not result.ok
