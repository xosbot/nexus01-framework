"""Tests for core/chat_tools.py and core/tool_registry.py:stream_invoke.

All external HTTP and Docker calls are mocked. Sandbox failures are injected
via a stub DockerSandbox.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


from core import chat_tools
from core.chat_tools import _DuckDuckGoParser, _TextExtractor
from core.cold_mode import ColdMode
from core.sandbox import SandboxResult
from core.tool_registry import ToolRegistry


# ── ToolRegistry.stream_invoke ─────────────────────────────────────────────


async def test_stream_invoke_emits_started_and_finished() -> None:
    reg = ToolRegistry()

    async def my_tool(x: int) -> str:
        return f"got {x}"

    reg.register(my_tool, name="my_tool", parameters={"type": "object", "properties": {"x": {"type": "integer"}}})
    events = []
    async for e in reg.stream_invoke("my_tool", '{"x": 42}', "tc1"):
        events.append(e)
    types = [e["type"] for e in events]
    assert types == ["tool_started", "tool_finished"]
    assert events[0]["args"] == {"x": 42}
    assert events[1]["content"] == "got 42"
    assert events[1]["ok"] is True
    assert events[1]["duration_ms"] >= 0


async def test_stream_invoke_handles_unknown_tool() -> None:
    reg = ToolRegistry()
    events = []
    async for e in reg.stream_invoke("nonexistent", "{}", "tc1"):
        events.append(e)
    assert events[-1]["type"] == "tool_finished"
    assert events[-1]["ok"] is False
    assert "not found" in events[-1]["content"]


async def test_stream_invoke_handles_invalid_json_args() -> None:
    reg = ToolRegistry()

    async def my_tool() -> str:
        return "ok"

    reg.register(my_tool)
    events = []
    async for e in reg.stream_invoke("my_tool", "{not json", "tc1"):
        events.append(e)
    assert events[-1]["type"] == "tool_finished"
    assert events[-1]["ok"] is False
    assert "invalid JSON" in events[-1]["content"]


async def test_stream_invoke_handles_tool_exception() -> None:
    reg = ToolRegistry()

    async def bad_tool() -> str:
        raise RuntimeError("boom")

    reg.register(bad_tool)
    events = []
    async for e in reg.stream_invoke("bad_tool", "{}", "tc1"):
        events.append(e)
    assert events[-1]["ok"] is False
    assert "boom" in events[-1]["content"]


async def test_stream_invoke_emits_blocked_for_needs_approval() -> None:
    reg = ToolRegistry()

    async def gated_tool() -> dict:
        return {"needs_approval": True, "approval_id": "apr_abc", "description": "do dangerous thing"}

    reg.register(gated_tool)
    events = []
    async for e in reg.stream_invoke("gated_tool", "{}", "tc1"):
        events.append(e)
    types = [e["type"] for e in events]
    assert "tool_blocked" in types
    blocked = next(e for e in events if e["type"] == "tool_blocked")
    assert blocked["approval_id"] == "apr_abc"
    assert blocked["description"] == "do dangerous thing"


async def test_stream_invoke_handles_sync_tool() -> None:
    reg = ToolRegistry()

    def sync_tool(x: str) -> str:
        return f"sync-{x}"

    reg.register(sync_tool)
    events = []
    async for e in reg.stream_invoke("sync_tool", '{"x": "hi"}', "tc1"):
        events.append(e)
    assert events[-1]["content"] == "sync-hi"


# ── _TextExtractor / _DuckDuckGoParser ────────────────────────────────────


def test_text_extractor_strips_html() -> None:
    html = "<html><body><h1>Title</h1><p>Hello world</p><script>alert(1)</script><p>Bye</p></body></html>"
    p = _TextExtractor()
    p.feed(html)
    assert "Title" in p.text
    assert "Hello world" in p.text
    assert "Bye" in p.text
    assert "alert" not in p.text


def test_duckduckgo_parser_parses_results() -> None:
    html = """
    <a class="result__a" href="https://example.com">Example Title</a>
    <a class="result__snippet" href="https://example.com">A snippet here</a>
    """
    p = _DuckDuckGoParser()
    p.feed(html)
    assert len(p.results) == 1
    assert p.results[0]["title"] == "Example Title"
    assert p.results[0]["url"] == "https://example.com"
    assert "snippet" in p.results[0]["snippet"].lower()


# ── web_search ─────────────────────────────────────────────────────────────


async def test_web_search_success() -> None:
    fake_html = '<a class="result__a" href="https://a.com">A</a><a class="result__snippet" href="https://a.com">S</a>'
    mock_resp = MagicMock()
    mock_resp.text = fake_html
    mock_resp.raise_for_status = MagicMock()
    with patch("core.chat_tools.httpx.AsyncClient") as MockClient:
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(return_value=mock_resp)
        MockClient.return_value = client
        out = await chat_tools.web_search("query", n=3)
    data = json.loads(out)
    assert "results" in data
    assert data["query"] == "query"


async def test_web_search_empty_query() -> None:
    out = await chat_tools.web_search("")
    data = json.loads(out)
    assert "error" in data


async def test_web_search_http_error_returns_error_json() -> None:
    with patch("core.chat_tools.httpx.AsyncClient") as MockClient:
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(side_effect=Exception("network down"))
        MockClient.return_value = client
        out = await chat_tools.web_search("query")
    data = json.loads(out)
    assert "error" in data


# ── fetch_url ──────────────────────────────────────────────────────────────


async def test_fetch_url_strips_html() -> None:
    html = "<html><body><h1>Hi</h1><p>Content here</p></body></html>"
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.raise_for_status = MagicMock()
    with patch("core.chat_tools.httpx.AsyncClient") as MockClient:
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(return_value=mock_resp)
        MockClient.return_value = client
        out = await chat_tools.fetch_url("https://example.com")
    data = json.loads(out)
    assert "Hi" in data["text"]
    assert "Content here" in data["text"]


async def test_fetch_url_rejects_bad_scheme() -> None:
    out = await chat_tools.fetch_url("file:///etc/passwd")
    data = json.loads(out)
    assert "error" in data


async def test_fetch_url_handles_plain_text() -> None:
    mock_resp = MagicMock()
    mock_resp.text = "Just plain text content"
    mock_resp.headers = {"content-type": "text/plain"}
    mock_resp.raise_for_status = MagicMock()
    with patch("core.chat_tools.httpx.AsyncClient") as MockClient:
        client = AsyncMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(return_value=mock_resp)
        MockClient.return_value = client
        out = await chat_tools.fetch_url("https://example.com/data.txt")
    data = json.loads(out)
    assert "Just plain text" in data["text"]


# ── list_dir / read_file scope ─────────────────────────────────────────────


async def test_list_dir_blocks_unsafe_path(tmp_path: Path) -> None:
    out = await chat_tools.list_dir("/etc")
    data = json.loads(out)
    assert "error" in data


async def test_list_dir_in_data_scope(tmp_path: Path) -> None:
    # Create a file in the actual ./data dir
    Path("./data/test_chat_tools_list").mkdir(parents=True, exist_ok=True)
    (Path("./data/test_chat_tools_list") / "hello.txt").write_text("hi")
    try:
        out = await chat_tools.list_dir("./data/test_chat_tools_list")
        data = json.loads(out)
        assert "entries" in data
        names = [e["name"] for e in data["entries"]]
        assert "hello.txt" in names
    finally:
        (Path("./data/test_chat_tools_list") / "hello.txt").unlink()
        Path("./data/test_chat_tools_list").rmdir()


async def test_read_file_in_data_scope(tmp_path: Path) -> None:
    target = Path("./data/test_chat_tools_read.txt")
    target.write_text("hello world")
    try:
        out = await chat_tools.read_file(str(target))
        data = json.loads(out)
        assert "hello world" in data["text"]
    finally:
        target.unlink()


async def test_read_file_blocks_unsafe_path() -> None:
    out = await chat_tools.read_file("/etc/passwd")
    data = json.loads(out)
    assert "error" in data


# ── rag_query ──────────────────────────────────────────────────────────────


async def test_rag_query_returns_results() -> None:
    fake_rag = MagicMock()
    fake_rag.search = MagicMock(return_value=[
        {"content": "doc1 content", "metadata": {"source": "f.txt"}},
        {"content": "doc2 content", "metadata": {"source": "f2.txt"}},
    ])
    out = await chat_tools.rag_query("test", n=2, rag=fake_rag)
    data = json.loads(out)
    assert len(data["results"]) == 2
    assert data["results"][0]["content"] == "doc1 content"


async def test_rag_query_no_rag_returns_error() -> None:
    out = await chat_tools.rag_query("test")
    data = json.loads(out)
    assert "error" in data


# ── memory_store ───────────────────────────────────────────────────────────


async def test_memory_store_persists(tmp_path: Path) -> None:
    from core.second_brain import SecondBrain
    brain = SecondBrain(db_path=tmp_path / "memory.db")
    out = await chat_tools.memory_store("user likes x", type="preference", brain=brain)
    data = json.loads(out)
    assert "memory_id" in data
    assert data["status"] in {"active", "pending"}


async def test_memory_store_no_brain_returns_error() -> None:
    out = await chat_tools.memory_store("test", brain=None)
    data = json.loads(out)
    assert "error" in data


# ── exec (cold-mode gated) ─────────────────────────────────────────────────


class _StubSandbox:
    def __init__(self, result: SandboxResult) -> None:
        self._result = result
        self.calls: list[str] = []

    async def run_command(self, cmd: str) -> SandboxResult:
        self.calls.append(cmd)
        return self._result


async def test_exec_cold_mode_disabled_allows_run() -> None:
    """When cold_mode is disabled, exec runs without approval."""
    cm = ColdMode(enabled=False)
    sandbox = _StubSandbox(SandboxResult(stdout="hello", exit_code=0, duration_ms=10))
    out = await chat_tools.exec(cmd="ls", permission="READ", cold_mode=cm, sandbox=sandbox)  # type: ignore[arg-type]
    data = json.loads(out)
    assert data["stdout"] == "hello"
    assert sandbox.calls == ["ls"]


async def test_exec_cold_mode_enabled_with_fallback_blocks() -> None:
    """With cold_mode on and a privileged command, exec requires approval."""
    cm = ColdMode(enabled=True)
    sandbox = _StubSandbox(SandboxResult(stdout="should not run", exit_code=0))
    # permission="READ" makes reversible=True; cold mode still requires fallback for run_command
    result = await chat_tools.exec(cmd="rm -rf /tmp/foo", permission="READ", cold_mode=cm, sandbox=sandbox)  # type: ignore[arg-type]
    assert isinstance(result, dict)
    assert result["needs_approval"] is True
    assert result["approval_id"].startswith("apr_")
    assert "Execute" in result["description"]
    # Pending state stored
    pending = chat_tools.get_pending_execution(result["approval_id"])
    assert pending is not None
    assert pending["cmd"] == "rm -rf /tmp/foo"
    assert sandbox.calls == []  # not actually run
    # Cleanup
    chat_tools.pop_pending_execution(result["approval_id"])


async def test_exec_empty_command_returns_error() -> None:
    cm = ColdMode(enabled=True)
    sandbox = _StubSandbox(SandboxResult())
    out = await chat_tools.exec(cmd="", cold_mode=cm, sandbox=sandbox)  # type: ignore[arg-type]
    data = json.loads(out)
    assert "error" in data


async def test_exec_pending_state_lifecycle() -> None:
    cm = ColdMode(enabled=True)
    sandbox = _StubSandbox(SandboxResult(stdout="x", exit_code=0))
    result = await chat_tools.exec(cmd="echo x", permission="READ", cold_mode=cm, sandbox=sandbox)  # type: ignore[arg-type]
    assert isinstance(result, dict)
    aid = result["approval_id"]
    assert chat_tools.get_pending_execution(aid) is not None
    popped = chat_tools.pop_pending_execution(aid)
    assert popped is not None
    assert popped["cmd"] == "echo x"
    assert chat_tools.get_pending_execution(aid) is None
