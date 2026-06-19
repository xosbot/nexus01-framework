"""Multi-provider LLM router — Ollama-first with cloud fallback and cost tracking."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, TYPE_CHECKING

import httpx
import yaml

if TYPE_CHECKING:
    from core.cost_tracker import CostTracker

logger = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).parent / "llm_config.yaml"
CHEAP, STANDARD, PREMIUM = "cheap", "standard", "premium"
_TIERS = (CHEAP, STANDARD, PREMIUM)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider_used: str = ""
    tier_used: str = ""
    model_used: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def text(self) -> str:
        return self.content or ""


class CircuitBreaker:
    def __init__(self, threshold: int = 3, reset_after: float = 60.0):
        self.threshold = threshold
        self.reset_after = reset_after
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._failures >= self.threshold:
            if self._opened_at and (time.monotonic() - self._opened_at) > self.reset_after:
                self._failures = 0
                self._opened_at = None
                return False
            return True
        return False

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.threshold and not self._opened_at:
            self._opened_at = time.monotonic()

    def record_success(self):
        self._failures = 0
        self._opened_at = None


class LLMProvider:
    def __init__(self, cfg: dict):
        self.name = cfg.get("name", cfg["provider"])
        self.provider = cfg["provider"]
        self.model = cfg["model"]
        self.api_key = cfg.get("api_key", "")
        self.timeout = cfg.get("timeout_seconds", 30)
        self.max_tokens = cfg.get("max_tokens", 2048)
        self.temperature = cfg.get("temperature", 0.3)
        self.tier = cfg.get("tier", STANDARD)
        self.cost_per_1m = cfg.get("cost_per_1m_tokens", 0.0)
        self.supports_streaming = cfg.get("supports_streaming", True)
        self.supports_tool_calling = cfg.get("supports_tool_calling", True)
        raw_url = cfg.get("base_url") or self._default_base_url()
        self.base_url = raw_url.rstrip("/") if raw_url else ""
        self._breaker = CircuitBreaker()

    def _default_base_url(self) -> str:
        return {
            "groq": "https://api.groq.com/openai/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
        }.get(self.provider, "")

    def is_available(self) -> bool:
        if self.provider == "ollama":
            return bool(self.base_url)
        return bool(self.api_key and self.base_url) and not self._breaker.is_open

    def _headers(self) -> dict:
        if self.provider == "anthropic":
            return {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        if self.provider == "ollama":
            return await self._ollama_complete(messages, **kwargs)
        if self.provider == "anthropic":
            return await self._anthropic_complete(messages, **kwargs)
        return await self._openai_compatible_complete(messages, **kwargs)

    async def complete_with_tools(self, messages: list[dict], tools: list[dict], **kwargs) -> LLMResponse:
        if self.provider in ("ollama",) or not self.supports_tool_calling:
            return await self._simulated_tools(messages, tools, **kwargs)
        if self.provider == "anthropic":
            return await self._anthropic_complete(messages, tools=tools, **kwargs)
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "tools": tools,
            "tool_choice": "auto",
        }
        return await self._post_openai(payload)

    async def _openai_compatible_complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
        }
        return await self._post_openai(payload)

    async def _post_openai(self, payload: dict) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(3):
                try:
                    resp = await client.post(url, json=payload, headers=self._headers())
                    resp.raise_for_status()
                    self._breaker.record_success()
                    return self._parse_openai(resp.json())
                except Exception as exc:
                    if attempt == 2:
                        self._breaker.record_failure()
                        raise exc
                    await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"{self.name} failed")

    def _parse_openai(self, data: dict) -> LLMResponse:
        choice = data["choices"][0]
        message = choice["message"]
        usage = data.get("usage", {})
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=tc["function"].get("arguments", "{}"))
            for tc in (message.get("tool_calls") or [])
        ]
        return LLMResponse(
            content=message.get("content"),
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else choice.get("finish_reason", "stop"),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            provider_used=self.name,
            model_used=self.model,
        )

    async def _anthropic_complete(self, messages: list[dict], tools: list[dict] | None = None, **kwargs) -> LLMResponse:
        system = ""
        msgs = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            elif m["role"] == "tool":
                msgs.append({"role": "user", "content": f"Tool result ({m.get('tool_call_id')}): {m.get('content')}"})
            else:
                msgs.append({"role": m["role"], "content": m["content"]})
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "messages": msgs,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "input_schema": t["function"]["parameters"],
                }
                for t in tools
            ]
        url = f"{self.base_url}/v1/messages"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            self._breaker.record_success()
            data = resp.json()
            usage = data.get("usage", {})
            content_blocks = data.get("content", [])
            text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            tool_calls = []
            for b in content_blocks:
                if b.get("type") == "tool_use":
                    tool_calls.append(ToolCall(
                        id=b.get("id", ""),
                        name=b.get("name", ""),
                        arguments=json.dumps(b.get("input", {})),
                    ))
            return LLMResponse(
                content=text or None,
                tool_calls=tool_calls,
                finish_reason="tool_calls" if tool_calls else "stop",
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                provider_used=self.name,
                model_used=self.model,
            )

    async def _simulated_tools(self, messages: list[dict], tools: list[dict], **kwargs) -> LLMResponse:
        tool_desc = "\n".join(f"- {t['function']['name']}: {t['function']['description']}" for t in tools)
        prefix = f"Available tools:\n{tool_desc}\n\nTo call a tool respond:\nTOOL_CALL: name\nARGS: {{json}}\n\n"
        msgs = list(messages)
        if msgs and msgs[0]["role"] == "system":
            msgs[0] = {"role": "system", "content": prefix + msgs[0]["content"]}
        else:
            msgs.insert(0, {"role": "system", "content": prefix})
        resp = await self.complete(msgs, **kwargs)
        m = re.search(r"TOOL_CALL:\s*(\w+)\s*\nARGS:\s*(\{.*?\})", resp.text, re.DOTALL)
        if m:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="sim_0", name=m.group(1), arguments=m.group(2))],
                finish_reason="tool_calls",
                provider_used=resp.provider_used,
                model_used=resp.model_used,
            )
        return resp

    async def _ollama_complete(self, messages: list[dict], **kwargs) -> LLMResponse:
        base = self.base_url.replace("/v1", "")
        payload = {"model": self.model, "messages": messages, "stream": False}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{base}/api/chat", json=payload)
            resp.raise_for_status()
            self._breaker.record_success()
            content = resp.json()["message"]["content"]
            return LLMResponse(content=content, provider_used=self.name, model_used=self.model)

    async def stream(self, messages: list[dict], **kwargs) -> AsyncGenerator[str, None]:
        if self.provider == "ollama":
            base = self.base_url.replace("/v1", "")
            payload = {"model": self.model, "messages": messages, "stream": True}
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", f"{base}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line:
                            data = json.loads(line)
                            if "message" in data:
                                chunk = data["message"].get("content", "")
                                if chunk:
                                    yield chunk
            return
        payload = {"model": self.model, "messages": messages, "stream": True, "max_tokens": self.max_tokens}
        url = f"{self.base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=self.timeout * 2) as client:
            async with client.stream("POST", url, json=payload, headers=self._headers()) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                            text = chunk["choices"][0].get("delta", {}).get("content")
                            if text:
                                yield text
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            parts = m.group(1).split(":-", 1)
            return os.getenv(parts[0], parts[1] if len(parts) > 1 else "")
        return re.sub(r"\$\{([^}]+)\}", repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def classify_tier(prompt: str, cfg: dict) -> str:
    words = len(prompt.split())
    lower = prompt.lower()
    if any(kw in lower for kw in cfg.get("premium_keywords", [])):
        return PREMIUM
    if any(kw in lower for kw in cfg.get("standard_keywords", [])):
        return STANDARD
    if words <= cfg.get("cheap_max_words", 30):
        return CHEAP
    if words <= cfg.get("standard_max_words", 120):
        return STANDARD
    return PREMIUM


class LLMRouter:
    def __init__(self, config_path: str | Path = _CONFIG_PATH, cost_tracker: CostTracker | None = None):
        raw = yaml.safe_load(Path(config_path).read_text())
        cfg = _expand_env(raw)
        self._routing = cfg.get("routing", {})
        self._system_prompt = cfg.get("system_prompt", "You are NEXUS-01.")
        self._default_tier = cfg.get("agent_loop", {}).get("default_tier", STANDARD)
        self._cost_tracker = cost_tracker
        self._tier_providers: dict[str, list[LLMProvider]] = {t: [] for t in _TIERS}
        self._provider_map: dict[str, LLMProvider] = {}
        for p_cfg in cfg.get("providers", []):
            try:
                p = LLMProvider(p_cfg)
                self._provider_map[p.name] = p
            except Exception as exc:
                logger.warning("Skipping provider %s: %s", p_cfg.get("name"), exc)
        for tier, names in cfg.get("tier_order", {}).items():
            for name in names:
                if name in self._provider_map:
                    self._tier_providers[tier].append(self._provider_map[name])
        self._total_tokens = 0
        self._total_cost = 0.0

    async def chat(self, messages: list[dict], tier: str | None = None, session_id: str = "", agent: str = "") -> str:
        resp = await self.complete_messages(messages, tier=tier, session_id=session_id, agent=agent)
        return resp.text

    async def complete_messages(
        self, messages: list[dict], tier: str | None = None, session_id: str = "", agent: str = ""
    ) -> LLMResponse:
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": self._system_prompt}, *messages]
        prompt = messages[-1].get("content", "")
        resolved = tier or classify_tier(prompt, self._routing) or self._default_tier
        resp = await self._dispatch(messages, resolved)
        self._record_usage(resp, session_id, agent)
        return resp

    async def complete_with_tools(
        self, messages: list[dict], tools: list[dict], tier: str | None = None,
        session_id: str = "", agent: str = "",
    ) -> LLMResponse:
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": self._system_prompt}, *messages]
        resolved = tier or self._default_tier
        tier_order = {CHEAP: 0, STANDARD: 1, PREMIUM: 2}
        for t in _TIERS:
            if tier_order[t] < tier_order.get(resolved, 1):
                continue
            for provider in self._tier_providers.get(t, []):
                if not provider.is_available():
                    continue
                try:
                    resp = await provider.complete_with_tools(messages, tools)
                    resp.tier_used = t
                    self._record_usage(resp, session_id, agent)
                    return resp
                except Exception as exc:
                    logger.warning("%s tool-call failed: %s", provider.name, exc)
        raise RuntimeError("All providers failed for tool calling")

    async def stream(self, messages: list[dict], tier: str | None = None) -> AsyncGenerator[str, None]:
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": self._system_prompt}, *messages]
        prompt = messages[-1].get("content", "")
        resolved = tier or classify_tier(prompt, self._routing) or self._default_tier
        tier_order = {CHEAP: 0, STANDARD: 1, PREMIUM: 2}
        for t in _TIERS:
            if tier_order[t] < tier_order.get(resolved, 1):
                continue
            for provider in self._tier_providers.get(t, []):
                if not provider.is_available():
                    continue
                try:
                    async for token in provider.stream(messages):
                        yield token
                    return
                except Exception as exc:
                    logger.warning("%s stream failed: %s", provider.name, exc)
        yield await self.chat(messages, tier=resolved)

    def _record_usage(self, resp: LLMResponse, session_id: str, agent: str) -> None:
        tokens = resp.prompt_tokens + resp.completion_tokens
        self._total_tokens += tokens
        provider = self._provider_map.get(resp.provider_used)
        cost = 0.0
        if provider and tokens:
            cost = tokens / 1_000_000 * provider.cost_per_1m
        self._total_cost += cost
        if self._cost_tracker and provider:
            from core.cost_tracker import UsageRecord
            self._cost_tracker.record(UsageRecord(
                provider=provider.provider,
                model=resp.model_used or provider.model,
                tier=resp.tier_used,
                prompt_tokens=resp.prompt_tokens,
                completion_tokens=resp.completion_tokens,
                cost_usd=cost,
                session_id=session_id,
                agent=agent,
            ))

    async def _dispatch(self, messages: list[dict], tier: str) -> LLMResponse:
        tier_order = {CHEAP: 0, STANDARD: 1, PREMIUM: 2}
        last_error: Exception | None = None
        for t in _TIERS:
            if tier_order[t] < tier_order.get(tier, 1):
                continue
            for provider in self._tier_providers.get(t, []):
                if not provider.is_available():
                    continue
                try:
                    resp = await provider.complete(messages)
                    resp.tier_used = t
                    resp.model_used = resp.model_used or provider.model
                    logger.info("LLM via %s (tier=%s)", provider.name, t)
                    return resp
                except Exception as exc:
                    logger.warning("%s failed: %s", provider.name, exc)
                    last_error = exc
        raise RuntimeError(f"All LLM providers failed. Last: {last_error}")

    def provider_status(self) -> list[dict]:
        seen, out = set(), []
        for tier in _TIERS:
            for p in self._tier_providers.get(tier, []):
                if p.name in seen:
                    continue
                seen.add(p.name)
                out.append({
                    "name": p.name,
                    "provider": p.provider,
                    "model": p.model,
                    "tier": p.tier,
                    "available": p.is_available(),
                    "cost_per_1m": p.cost_per_1m,
                    "tool_calling": p.supports_tool_calling,
                })
        return out

    def stats(self) -> dict:
        summary = self._cost_tracker.summary() if self._cost_tracker else {}
        return {
            "total_tokens": self._total_tokens,
            "estimated_cost_usd": round(self._total_cost, 4),
            "ledger": summary,
        }
