import httpx
import asyncio
from typing import AsyncGenerator

class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=60.0)

    async def complete(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        payload = {"model": model or self.model, "messages": messages, "stream": False}
        for attempt in range(3):
            try:
                resp = await self._client.post("/api/chat", json=payload)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            except (httpx.HTTPError, KeyError):
                if attempt == 2:
                    raise
                await asyncio.sleep(1 * (attempt + 1))
        return ""

    async def stream(self, messages: list[dict[str, str]], model: str | None = None) -> AsyncGenerator[str, None]:
        payload = {"model": model or self.model, "messages": messages, "stream": True}
        async with self._client.stream("POST", "/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    import json
                    data = json.loads(line)
                    if "message" in data:
                        yield data["message"].get("content", "")

    async def close(self):
        await self._client.aclose()
