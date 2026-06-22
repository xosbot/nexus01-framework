"""IVA Reasoning Engine — Mythos-inspired recurrent-depth reasoning loops."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ReasoningDepth(Enum):
    SIMPLE = 1
    STANDARD = 3
    COMPLEX = 5


class ReasoningPhase(Enum):
    PRELUDE = "prelude"
    THINK = "think"
    REFLECT = "reflect"
    REFINE = "refine"
    ACT = "act"
    CODA = "coda"


@dataclass
class ReasoningStep:
    phase: ReasoningPhase
    content: str
    confidence: float = 0.0
    iteration: int = 0


@dataclass
class ReasoningResult:
    final_answer: str
    steps: list[ReasoningStep] = field(default_factory=list)
    depth: ReasoningDepth = ReasoningDepth.SIMPLE
    iterations_used: int = 0
    total_tokens: int = 0


_SIMPLE_PATTERNS = [
    "hello", "hi", "hey", "status", "what time", "who are you",
    "help", "thanks", "bye", "ok", "yes", "no",
]

_COMPLEX_PATTERNS = [
    "architect", "design", "plan", "compare", "evaluate",
    "comprehensive", "step by step", "multi", "complex",
    "analyze and", "research and", "trade-offs", "pros and cons",
    "deep analysis", "refactor", "optimize",
]

_CONFIDENCE_RE = re.compile(r"confidence[:\s]+(0?\.\d+|1\.0+|[\d](?:\.\d+)?)", re.IGNORECASE)


class ReasoningEngine:
    def __init__(self, llm: object, max_depth: int = 5) -> None:
        self.llm = llm
        self.max_depth = max_depth

    async def reason(
        self, query: str, context: str = "", session_id: str = "",
    ) -> ReasoningResult:
        depth = self._classify_depth(query)
        logger.debug(f"Reasoning depth: {depth.name} for query: {query[:80]}")

        plan = await self._prelude(query, context, session_id)
        steps: list[ReasoningStep] = [
            ReasoningStep(phase=ReasoningPhase.PRELUDE, content=plan),
        ]

        current_answer = ""
        iterations_used = 0

        for i in range(depth.value):
            thought = await self._think(query, context, current_answer, plan, i, session_id)
            steps.append(ReasoningStep(phase=ReasoningPhase.THINK, content=thought, iteration=i))
            iterations_used += 1

            reflection = await self._reflect(query, thought, i, session_id)
            confidence = self._extract_confidence(reflection)
            steps.append(ReasoningStep(
                phase=ReasoningPhase.REFLECT, content=reflection,
                confidence=confidence, iteration=i,
            ))

            if confidence >= 0.85 and i >= 1:
                current_answer = thought
                logger.debug(f"Halted at iteration {i} with confidence {confidence:.2f}")
                break

            current_answer = await self._refine(query, thought, reflection, i, session_id)
            steps.append(ReasoningStep(
                phase=ReasoningPhase.REFINE, content=current_answer, iteration=i,
            ))

        final = await self._coda(query, current_answer, session_id)
        steps.append(ReasoningStep(phase=ReasoningPhase.CODA, content=final))

        return ReasoningResult(
            final_answer=final,
            steps=steps,
            depth=depth,
            iterations_used=iterations_used,
        )

    def _classify_depth(self, query: str) -> ReasoningDepth:
        words = query.split()
        lower = query.lower()

        if any(p in lower for p in _SIMPLE_PATTERNS) and len(words) < 10:
            return ReasoningDepth.SIMPLE

        if len(words) > 30 or any(p in lower for p in _COMPLEX_PATTERNS):
            return ReasoningDepth.COMPLEX

        return ReasoningDepth.STANDARD

    async def _prelude(self, query: str, context: str, session_id: str) -> str:
        ctx_hint = f"\nContext: {context[:500]}" if context else ""
        messages = [
            {"role": "system", "content": "You are a planning assistant. Output a brief numbered plan (3-5 steps max)."},
            {"role": "user", "content": f"Create a plan to answer this query: {query}{ctx_hint}"},
        ]
        return await self._safe_complete(messages, session_id, fallback="1. Analyze query\n2. Generate response\n3. Verify")

    async def _think(
        self, query: str, context: str, prev_answer: str,
        plan: str, iteration: int, session_id: str,
    ) -> str:
        prev = f"\nPrevious answer (iteration {iteration - 1}):\n{prev_answer[:1000]}" if prev_answer else ""
        messages = [
            {"role": "system", "content": (
                "You are a reasoning assistant. Think step by step. "
                "State assumptions explicitly. Surface tradeoffs. "
                "Be concise and direct."
            )},
            {"role": "user", "content": (
                f"Query: {query}\n"
                f"Plan:\n{plan[:500]}\n"
                f"Context: {context[:500] if context else 'None'}"
                f"{prev}\n\n"
                f"Iteration {iteration + 1}: Provide your best answer."
            )},
        ]
        return await self._safe_complete(messages, session_id, fallback=prev_answer or "Unable to generate response.")

    async def _reflect(self, query: str, thought: str, iteration: int, session_id: str) -> str:
        messages = [
            {"role": "system", "content": (
                "You are a critical reviewer. Evaluate the answer below. "
                "Rate confidence 0.0-1.0. List what's missing or wrong. "
                "Format: 'Confidence: X.X\\nCritique: ...'"
            )},
            {"role": "user", "content": (
                f"Query: {query}\n"
                f"Answer (iteration {iteration + 1}):\n{thought[:1500]}\n\n"
                f"Evaluate this answer."
            )},
        ]
        return await self._safe_complete(messages, session_id, fallback="Confidence: 0.5\nCritique: Unable to evaluate.")

    async def _refine(
        self, query: str, thought: str, reflection: str,
        iteration: int, session_id: str,
    ) -> str:
        messages = [
            {"role": "system", "content": (
                "You are a refinement assistant. Improve the answer based on the critique. "
                "Keep what works. Fix what's wrong. Add what's missing. Be surgical."
            )},
            {"role": "user", "content": (
                f"Query: {query}\n"
                f"Current answer:\n{thought[:1000]}\n\n"
                f"Critique:\n{reflection[:500]}\n\n"
                f"Produce an improved answer."
            )},
        ]
        return await self._safe_complete(messages, session_id, fallback=thought)

    async def _coda(self, query: str, answer: str, session_id: str) -> str:
        if not answer:
            return "I was unable to generate a response. Please try rephrasing your query."
        messages = [
            {"role": "system", "content": (
                "You are a formatting assistant. Polish the answer for clarity and readability. "
                "Do not change the substance. Fix formatting, grammar, and structure only."
            )},
            {"role": "user", "content": f"Query: {query}\n\nPolish this answer:\n{answer[:2000]}"},
        ]
        return await self._safe_complete(messages, session_id, fallback=answer)

    def _extract_confidence(self, reflection: str) -> float:
        match = _CONFIDENCE_RE.search(reflection)
        if match:
            try:
                val = float(match.group(1))
                return max(0.0, min(1.0, val))
            except ValueError:
                pass
        return 0.5

    async def _safe_complete(
        self, messages: list[dict[str, str]], session_id: str, fallback: str,
    ) -> str:
        try:
            result = await self.llm.complete(messages, session_id=session_id, agent="reasoning")
            logger.debug(f"LLM response ({len(result)} chars)")
            return result
        except Exception as exc:
            logger.warning(f"LLM call failed: {exc}, using fallback")
            return fallback
