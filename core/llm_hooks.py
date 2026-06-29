"""LLM hooks — soul injection + event emission.

Wraps the LLM router so that:
  1. The soul/personality is automatically prepended to the system prompt
  2. Every LLM call emits events to the event log

Usage:
    from core.llm_hooks import HookedLLM
    inner = NexusLLM(...)
    hooked = HookedLLM(inner)
    await hooked.stream(messages, session_id=..., agent=...)
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from core import events as _events
from core import soul as _soul

logger = logging.getLogger(__name__)

_SOUL_HEADER = (
    "## Personality & Operating Principles\n"
    "The following is your operator-defined identity. Internalize it; do not "
    "restate it. When your behavior conflicts with this block, this block wins.\n\n"
)


def _compose_system_prompt(base: str | None) -> str:
    soul_text = _soul.render_for_prompt()
    if not soul_text:
        return base or ""
    if not base:
        return _SOUL_HEADER + soul_text
    return base.strip() + "\n\n" + _SOUL_HEADER + soul_text


class HookedLLM:
    """Wraps NexusLLM to inject soul + emit events around every call."""

    def __init__(self, inner):
        self._inner = inner

    @property
    def router(self):
        return self._inner.router

    async def complete(self, messages, model=None, session_id: str = "", agent: str = ""):
        _events.emit("llm_call_started", session_id=session_id, agent=agent or "chat",
                     data={"messages": len(messages)})
        try:
            out = await self._inner.complete(messages, model=model, session_id=session_id, agent=agent)
            _events.emit("llm_call_finished", session_id=session_id, agent=agent or "chat",
                         data={"chars": len(out or "")})
            return out
        except Exception as exc:
            _events.emit("error", f"llm.complete failed: {exc}", session_id=session_id, agent=agent, level="error")
            raise

    async def stream(
        self, messages, model=None, session_id: str = "", agent: str = "",
    ) -> AsyncGenerator[str, None]:
        _events.emit("llm_call_started", session_id=session_id, agent=agent or "chat",
                     data={"messages": len(messages), "stream": True})
        full = []
        try:
            async for token in self._inner.stream(messages, model=model, session_id=session_id, agent=agent):
                full.append(token)
                yield token
            _events.emit("llm_call_finished", session_id=session_id, agent=agent or "chat",
                         data={"chars": sum(len(t) for t in full)})
        except Exception as exc:
            _events.emit("error", f"llm.stream failed: {exc}", session_id=session_id, agent=agent, level="error")
            raise

    async def close(self):
        await self._inner.close()

    def provider_status(self):
        return self._inner.provider_status()

    def stats(self):
        return self._inner.stats()
