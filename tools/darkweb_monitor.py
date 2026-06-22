"""Dark web monitoring stub — OnionSearch integration.

Deferred to Phase 4 per PHASE_MAP.md. This module provides:
- Interface for future TorBot / OnionSearch integration
- Placeholder for .onion search engine queries
- Structured output for when the module is activated
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DarkWebResult:
    query: str
    results: list[dict] = field(default_factory=list)
    source: str = "stub"
    errors: list[str] = field(default_factory=list)
    is_stub: bool = True

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "results": self.results,
            "source": self.source,
            "is_stub": self.is_stub,
            "note": "Dark web monitoring requires Tor proxy. Enable in Phase 4.",
        }


async def search_darkweb(query: str) -> DarkWebResult:
    """Search .onion engines — stub implementation.

    To activate, install Tor and OnionSearch:
        apt install tor
        pip install onionsearch

    Then set DARKWEB_ENABLED=true and configure SOCKS proxy.
    """
    import os

    if os.environ.get("DARKWEB_ENABLED", "").lower() != "true":
        return DarkWebResult(
            query=query,
            source="stub",
            errors=["Dark web monitoring disabled. Set DARKWEB_ENABLED=true to enable."],
        )

    try:
        return await _onionsearch_scan(query)
    except Exception as exc:
        return DarkWebResult(query=query, errors=[str(exc)])


async def _onionsearch_scan(query: str) -> DarkWebResult:
    """Run OnionSearch against .onion search engines."""
    result = DarkWebResult(query=query, source="onionsearch", is_stub=False)

    try:
        proc = await __import__("asyncio").create_subprocess_exec(
            "onionsearch", query,
            "--limit", "10",
            stdout=__import__("asyncio").subprocess.PIPE,
            stderr=__import__("asyncio").subprocess.PIPE,
        )
        stdout, _ = await __import__("asyncio").wait_for(proc.communicate(), timeout=60)
        output = stdout.decode(errors="replace")

        for line in output.splitlines():
            line = line.strip()
            if line and line.startswith("http"):
                result.results.append({"url": line, "source": "onionsearch"})

    except FileNotFoundError:
        result.errors.append("onionsearch not installed")
    except Exception as exc:
        result.errors.append(str(exc))

    return result
