"""Unified LLM client — Ollama-compatible interface backed by LLMRouter."""

from __future__ import annotations

from typing import AsyncGenerator

from core.cost_tracker import CostTracker
from core.llm_router import LLMRouter


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
        return await self._router.chat(messages, session_id=session_id, agent=agent)

    async def stream(self, messages: list[dict[str, str]], model: str | None = None) -> AsyncGenerator[str, None]:
        async for token in self._router.stream(messages):
            yield token

    def provider_status(self) -> list[dict]:
        return self._router.provider_status()

    def stats(self) -> dict:
        return self._router.stats()

    async def close(self):
        pass
