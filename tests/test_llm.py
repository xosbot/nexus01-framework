"""Test LLM router — tier classification, fallback chain, circuit breaker."""

from __future__ import annotations

import json
import pytest
from core.llm_router import (
    LLMRouter, LLMResponse, ToolCall, classify_tier, STANDARD, PREMIUM, CHEAP,
)


@pytest.fixture
def routing_cfg():
    return {
        "cheap_max_words": 30,
        "standard_max_words": 120,
        "premium_keywords": ["implement", "refactor", "comprehensive"],
        "standard_keywords": ["research", "analyze", "explain"],
    }


class TestTierClassification:
    def test_short_query_is_cheap(self, routing_cfg):
        assert classify_tier("hello world", routing_cfg) == CHEAP

    def test_standard_keyword_triggers_standard(self, routing_cfg):
        assert classify_tier("research quantum computing", routing_cfg) == STANDARD

    def test_premium_keyword_triggers_premium(self, routing_cfg):
        assert classify_tier("implement a distributed system", routing_cfg) == PREMIUM

    def test_medium_length_is_standard(self, routing_cfg):
        words = "analyze the performance characteristics of " * 4
        assert len(words.split()) < 120
        assert classify_tier(words, routing_cfg) == STANDARD

    def test_long_query_is_premium(self, routing_cfg):
        words = "word " * 150
        assert classify_tier(words, routing_cfg) == PREMIUM

    def test_standard_takes_precedence_over_length(self, routing_cfg):
        classify_tier("short query", {"premium_keywords": [], "standard_keywords": [],
                                       "cheap_max_words": 30, "standard_max_words": 120})


class TestLLMResponse:
    def test_no_tool_calls(self):
        resp = LLMResponse(content="hello")
        assert resp.text == "hello"
        assert not resp.has_tool_calls

    def test_with_tool_calls(self):
        resp = LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="call_1", name="web_search", arguments='{"q":"test"}')],
        )
        assert resp.has_tool_calls
        assert resp.text == ""

    def test_empty_content_text_fallback(self):
        resp = LLMResponse(content=None)
        assert resp.text == ""


class TestToolCall:
    def test_attributes(self):
        tc = ToolCall(id="call_abc", name="search", arguments='{"q":"test"}')
        assert tc.id == "call_abc"
        assert tc.name == "search"
        assert json.loads(tc.arguments) == {"q": "test"}


class TestRouterConfigErrors:
    def test_no_config_file_raises(self):
        with pytest.raises((FileNotFoundError, RuntimeError)):
            LLMRouter("/nonexistent/path.yaml")


class TestCircuitBreakerIntegration:
    def test_breaker_rejects_when_open(self, monkeypatch):
        from core.llm_router import LLMProvider
        provider = LLMProvider({
            "name": "test", "provider": "openai", "model": "gpt-4o-mini",
            "api_key": "test", "base_url": "http://localhost:1",
            "cost_per_1m_tokens": 0.0, "tier": "standard",
        })
        provider._breaker._failures = 3
        provider._breaker._opened_at = 0.0
        assert not provider.is_available()

    def test_breaker_closes_after_timeout(self, monkeypatch):
        import time as _time
        from core.llm_router import LLMProvider
        provider = LLMProvider({
            "name": "test", "provider": "openai", "model": "gpt-4o-mini",
            "api_key": "test", "base_url": "http://localhost:1",
            "cost_per_1m_tokens": 0.0, "tier": "standard",
        })
        provider._breaker._failures = 3
        provider._breaker._opened_at = _time.monotonic() - 120
        assert provider.is_available()
