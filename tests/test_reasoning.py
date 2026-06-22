"""Tests for the Reasoning Engine."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from core.reasoning import (
    ReasoningEngine,
    ReasoningDepth,
    ReasoningResult,
)


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.complete = AsyncMock(return_value="Mocked response")
    return llm


@pytest.fixture
def engine(mock_llm):
    return ReasoningEngine(llm=mock_llm, max_depth=5)


class TestDepthClassification:
    def test_simple_query(self, engine):
        assert engine._classify_depth("hello") == ReasoningDepth.SIMPLE

    def test_short_greeting(self, engine):
        assert engine._classify_depth("hi there") == ReasoningDepth.SIMPLE

    def test_complex_query(self, engine):
        assert engine._classify_depth(
            "comprehensive analysis of system design trade-offs and optimization"
        ) == ReasoningDepth.COMPLEX

    def test_long_query(self, engine):
        words = "analyze " * 40
        assert engine._classify_depth(words) == ReasoningDepth.COMPLEX

    def test_standard_query(self, engine):
        assert engine._classify_depth(
            "tell me about the different components of this system and their interactions"
        ) == ReasoningDepth.STANDARD


class TestConfidenceExtraction:
    def test_extract_high_confidence(self, engine):
        text = "Confidence: 0.9\nCritique: Looks good overall."
        assert engine._extract_confidence(text) == 0.9

    def test_extract_low_confidence(self, engine):
        text = "Confidence: 0.3\nCritique: Needs major work."
        assert engine._extract_confidence(text) == 0.3

    def test_extract_no_confidence(self, engine):
        text = "No confidence rating provided."
        assert engine._extract_confidence(text) == 0.5

    def test_extract_out_of_range(self, engine):
        text = "Confidence: 1.5\nThis is above 1.0"
        assert engine._extract_confidence(text) == 1.0

    def test_extract_decimal_edge_cases(self, engine):
        assert engine._extract_confidence("Confidence: 0.85") == 0.85
        assert engine._extract_confidence("Confidence: 0.") == 0.0
        assert engine._extract_confidence("Confidence: .5") == 0.5


@pytest.mark.asyncio
class TestReasoningEngine:
    async def test_reason_returns_result(self, engine, mock_llm):
        result = await engine.reason("What is 2+2?", session_id="test")
        assert isinstance(result, ReasoningResult)
        assert isinstance(result.final_answer, str)
        assert len(result.steps) > 0
        assert mock_llm.complete.called

    async def test_reason_depth_simple(self, engine, mock_llm):
        mock_llm.complete.return_value = "Answer"
        result = await engine.reason("hello", session_id="test")
        assert result.depth == ReasoningDepth.SIMPLE
        assert result.iterations_used == 1

    async def test_reason_stops_early_on_high_confidence(self, engine, mock_llm):
        mock_llm.complete.side_effect = [
            "thought",
            "Confidence: 0.9\nCritique: Good",
            "refined",
            "final",
        ]
        result = await engine.reason("what time is it", session_id="test")
        assert result.iterations_used <= 3