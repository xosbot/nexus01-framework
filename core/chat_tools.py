"""Chat tools — tools the LLM can invoke from /api/chat/stream.

Tools registered here are exposed to the LLM via ToolRegistry.as_openai_tools().
Each tool is a small, well-typed function that returns either:
  - a string (normal result)
  - a dict with {"needs_approval": True, "approval_id": ..., "description": ...}
    (cold-mode gated; stream_invoke converts this to a tool_blocked event)

The pending-approval state for `exec` is held in `_PENDING_EXECUTIONS` so that
when the user POSTs to /api/chat/approve, we can look up the original cmd and
permission and re-run with the elevated permission.

Tool list (buildplan §1.4):
  - web_search(query, n=5)       no cold-mode
  - fetch_url(url)               no cold-mode
  - exec(cmd, permission="READ") ALWAYS cold-mode gated
  - rag_query(query, n=5)        no cold-mode
  - memory_store(content, type)  no cold-mode (high-confidence write)
  - list_dir(path)               no cold-mode, scoped
  - read_file(path)              no cold-mode, scoped
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from core.cold_mode import ColdMode
from core.sandbox import DockerSandbox, SandboxConfig, SandboxResult

logger = logging.getLogger(__name__)

DEFAULT_WEB_TIMEOUT = 15
DEFAULT_FETCH_TIMEOUT = 20
DEFAULT_WEB_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Nexus01/1.0"
SAFE_SCOPES = ("./data", "./web")
MAX_OUTPUT_CHARS = 6000


# approval_id → {"cmd": str, "permission": str, "session_id": str, "ts": float}
_PENDING_EXECUTIONS: dict[str, dict[str, Any]] = {}


def get_pending_execution(approval_id: str) -> dict | None:
    """Look up a pending exec by approval_id. Used by the /api/chat/approve path."""
    return _PENDING_EXECUTIONS.get(approval_id)


def pop_pending_execution(approval_id: str) -> dict | None:
    """Look up and remove a pending exec."""
    return _PENDING_EXECUTIONS.pop(approval_id, None)


# ── HTTP helpers ──────────────────────────────────────────────────────────


class _TextExtractor(HTMLParser):
    """Strips HTML to plain text. Collects text content, drops scripts/styles."""

    _SKIP_TAGS = frozenset({"script", "style", "noscript", "iframe", "svg"})

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._chunks.append(text + " ")

    @property
    def text(self) -> str:
        raw = "".join(self._chunks)
        # Collapse runs of whitespace
        return "\n".join(" ".join(line.split()) for line in raw.splitlines() if line.strip())


class _DuckDuckGoParser(HTMLParser):
    """Parses DuckDuckGo HTML search results."""

    def __init__(self) -> None:
        super().__init__()
        self._results: list[dict[str, str]] = []
        self._in_result = False
        self._in_title = False
        self._in_snippet = False
        self._current_url = ""
        self._current_title = ""
        self._current_snippet = ""
        self._snippet_buf: list[str] = []
        self._title_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrd = dict(attrs)
        cls = (attrd.get("class") or "").lower()
        href = attrd.get("href") or ""
        if tag == "a" and "result__a" in cls:
            self._in_result = True
            self._current_url = unquote(href)
            self._in_title = True
            self._title_buf = []
        elif tag == "a" and "result__snippet" in cls:
            self._in_snippet = True
            self._snippet_buf = []
        elif tag == "div" and "result__snippet" in cls:
            self._in_snippet = True
            self._snippet_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
            self._current_title = "".join(self._title_buf).strip()
        elif tag in ("div", "a") and self._in_snippet:
            self._in_snippet = False
            self._current_snippet = "".join(self._snippet_buf).strip()
            if self._current_url and self._current_title:
                self._results.append({
                    "title": self._current_title,
                    "url": self._current_url,
                    "snippet": self._current_snippet,
                })
                self._in_result = False
                self._current_url = ""
                self._current_title = ""
                self._current_snippet = ""

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_buf.append(data)
        elif self._in_snippet:
            self._snippet_buf.append(data)

    @property
    def results(self) -> list[dict[str, str]]:
        return self._results


# ── Tools ─────────────────────────────────────────────────────────────────


async def web_search(query: str, n: int = 5) -> str:
    """Search the web via DuckDuckGo HTML. Returns a JSON list of results."""
    if not query or not query.strip():
        return json.dumps({"error": "empty query"})
    n = max(1, min(10, n))
    url = "https://html.duckduckgo.com/html/"
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_WEB_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_WEB_USER_AGENT},
        ) as client:
            resp = await client.post(url, data={"q": query.strip()})
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("[web_search] failed: %s", exc)
        return json.dumps({"error": f"search failed: {exc}", "results": []})

    parser = _DuckDuckGoParser()
    try:
        parser.feed(resp.text)
    except Exception as exc:
        logger.warning("[web_search] parse failed: %s", exc)
        return json.dumps({"error": f"parse failed: {exc}", "results": []})

    return json.dumps({"query": query, "results": parser.results[:n]})


async def fetch_url(url: str, max_chars: int = 5000) -> str:
    """Fetch a URL and return its text content (HTML stripped)."""
    if not url or not url.strip():
        return json.dumps({"error": "empty url"})
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return json.dumps({"error": f"unsupported scheme: {parsed.scheme}"})
    try:
        async with httpx.AsyncClient(
            timeout=DEFAULT_FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_WEB_USER_AGENT},
        ) as client:
            resp = await client.get(url.strip())
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            body = resp.text
    except Exception as exc:
        logger.warning("[fetch_url] failed for %s: %s", url, exc)
        return json.dumps({"error": f"fetch failed: {exc}", "url": url})

    if "html" in content_type.lower():
        extractor = _TextExtractor()
        try:
            extractor.feed(body)
            text = extractor.text
        except Exception as exc:
            text = body
            logger.debug("[fetch_url] HTML parse error: %s", exc)
    else:
        text = body

    return json.dumps({
        "url": url,
        "content_type": content_type,
        "text": text[:max_chars],
        "truncated": len(text) > max_chars,
    })


def _is_safe_path(path: str) -> tuple[bool, str]:
    """Restrict file ops to SAFE_SCOPES (./data, ./web). Returns (ok, resolved)."""
    if not path:
        return False, ""
    try:
        resolved = str(Path(path).expanduser().resolve())
    except Exception:
        return False, ""
    for scope in SAFE_SCOPES:
        try:
            scope_resolved = str(Path(scope).resolve())
            if resolved == scope_resolved or resolved.startswith(scope_resolved + "/"):
                return True, resolved
        except Exception:
            continue
    return False, resolved


async def list_dir(path: str) -> str:
    """List directory entries. Scoped to ./data and ./web."""
    ok, resolved = _is_safe_path(path)
    if not ok:
        return json.dumps({"error": f"path not in safe scope: {path}", "allowed": list(SAFE_SCOPES)})
    p = Path(resolved)
    if not p.exists():
        return json.dumps({"error": f"path does not exist: {path}"})
    if not p.is_dir():
        return json.dumps({"error": f"not a directory: {path}"})
    entries = []
    for child in sorted(p.iterdir()):
        try:
            entries.append({
                "name": child.name,
                "is_dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else 0,
            })
        except OSError:
            continue
    return json.dumps({"path": resolved, "entries": entries[:200]})


async def read_file(path: str, max_chars: int = 8000) -> str:
    """Read a text file. Scoped to ./data and ./web."""
    ok, resolved = _is_safe_path(path)
    if not ok:
        return json.dumps({"error": f"path not in safe scope: {path}", "allowed": list(SAFE_SCOPES)})
    p = Path(resolved)
    if not p.exists():
        return json.dumps({"error": f"file does not exist: {path}"})
    if not p.is_file():
        return json.dumps({"error": f"not a file: {path}"})
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return json.dumps({"error": f"read failed: {exc}"})
    return json.dumps({"path": resolved, "text": text[:max_chars], "truncated": len(text) > max_chars})


async def rag_query(query: str, n: int = 5, rag: Any = None) -> str:
    """Search the local RAG knowledge base. rag arg injected at registration."""
    if not query or not query.strip():
        return json.dumps({"error": "empty query"})
    if rag is None:
        return json.dumps({"error": "RAG not configured", "results": []})
    n = max(1, min(20, n))
    try:
        hits = rag.search(query.strip(), n=n) or []
    except Exception as exc:
        logger.warning("[rag_query] failed: %s", exc)
        return json.dumps({"error": f"rag query failed: {exc}", "results": []})
    out = []
    for h in hits[:n]:
        meta = h.get("metadata") or {}
        out.append({
            "content": (h.get("content") or "")[:600],
            "source": meta.get("source", ""),
            "url": meta.get("url", ""),
            "title": meta.get("title", ""),
            "distance": h.get("distance"),
        })
    return json.dumps({"query": query, "results": out})


async def memory_store(
    content: str, type: str = "identity",
    importance: float = 0.7, durability: float = 0.7,
    brain: Any = None, session_id: str = "",
) -> str:
    """Store a high-confidence memory. brain arg injected at registration."""
    if brain is None:
        return json.dumps({"error": "memory not configured"})
    try:
        m = brain.add_memory(
            type=type, content=content, confidence=0.95,
            importance=importance, durability=durability,
            source_session_id=session_id,
            source_quote=content[:200],
        )
    except Exception as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"memory_id": m.get("id", ""), "status": m.get("status", "unknown")})


async def exec(
    cmd: str, permission: str = "READ", session_id: str = "",
    cold_mode: ColdMode | None = None, sandbox: DockerSandbox | None = None,
) -> Any:
    """Run a shell command in a Docker sandbox. ALWAYS cold-mode gated.

    Returns:
      str  — normal result (stdout/stderr/exit code)
      dict — {"needs_approval": True, "approval_id": ..., "description": ...} if blocked
    """
    if not cmd or not cmd.strip():
        return json.dumps({"error": "empty command"})
    cm = cold_mode or ColdMode(enabled=True)
    if sandbox is None:
        sandbox = DockerSandbox(SandboxConfig(timeout_seconds=30))

    context = ColdMode.build_context(
        action="run_command",
        permission=permission,
        confidence=0.95,
        reversible=permission == "READ",
    )
    context["session_id"] = session_id
    context["cmd_preview"] = cmd[:200]

    if cm.should_block(context):
        approval_id = "apr_" + uuid.uuid4().hex[:12]
        reasons = cm.get_failure_reasons(context)
        _PENDING_EXECUTIONS[approval_id] = {
            "cmd": cmd, "permission": permission, "session_id": session_id,
            "ts": time.time(),
        }
        return {
            "needs_approval": True,
            "approval_id": approval_id,
            "description": "Execute: " + cmd[:200],
            "reasons": reasons,
        }

    # Allowed — run in sandbox
    result: SandboxResult = await sandbox.run_command(cmd)
    return json.dumps(result.to_dict())[:MAX_OUTPUT_CHARS]
