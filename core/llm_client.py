"""Unified LLM client — Ollama-compatible interface backed by LLMRouter."""

from __future__ import annotations

from typing import AsyncGenerator

from core.cost_tracker import CostTracker
from core.llm_router import LLMRouter
from core.soul import render_for_prompt as _render_soul


def _inject_soul(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Prepend IVA's soul/personality to the system prompt if no system msg exists.

    If a system message exists, the soul is appended (operator-defined identity wins).
    """
    soul_text = _render_soul()
    if not soul_text:
        return messages
    soul_block = (
        "## Personality & Operating Principles\n"
        "The following is your operator-defined identity. Internalize it; do not "
        "restate it. When your behavior conflicts with this block, this block wins.\n\n"
        + soul_text
    )
    if not messages:
        return [{"role": "system", "content": soul_block}]
    if messages[0].get("role") == "system":
        new_sys = messages[0].get("content", "").strip()
        new_sys = (new_sys + "\n\n" + soul_block).strip() if new_sys else soul_block
        return [{"role": "system", "content": new_sys}, *messages[1:]]
    return [{"role": "system", "content": soul_block}, *messages]


class NexusLLM:
    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.1",
        cost_tracker: CostTracker | None = None,
    ):
        import os
        os.environ.setdefault("OLLAMA_URL", ollama_url)
        os.environ.setdefault("OLLAMA_MODEL", ollama_model)
        self.model = ollama_model
        self.base_url = ollama_url
        self._router = LLMRouter(cost_tracker=cost_tracker)

    @property
    def router(self) -> LLMRouter:
        return self._router

    async def complete(
        self, messages: list[dict[str, str]], model: str | None = None,
        session_id: str = "", agent: str = "",
    ) -> str:
        injected = _inject_soul(messages)
        return await self._router.chat(injected, session_id=session_id, agent=agent)

    async def stream(
        self, messages: list[dict[str, str]], model: str | None = None,
        session_id: str = "", agent: str = "",
    ) -> AsyncGenerator[str, None]:
        injected = _inject_soul(messages)
        async for token in self._router.stream(injected, session_id=session_id, agent=agent):
            yield token

    def provider_status(self) -> list[dict]:
        return self._router.provider_status()

    def stats(self) -> dict:
        return self._router.stats()

    async def close(self):
        pass
