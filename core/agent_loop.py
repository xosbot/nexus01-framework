"""ReAct agent loop — reason + act with parallel tool execution, resilience."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from core.llm_router import STANDARD, classify_tier
from core.resilience import CircuitBreaker, with_retry

if TYPE_CHECKING:
    from core.llm_router import LLMRouter
    from core.memory import Memory
    from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)
_MAX_ITERATIONS = 15
_MAX_TOOL_CHARS = 3000
_STREAM_MAX_ITERATIONS = 5  # tighter cap for the streaming variant used in chat


class AgentLoop:
    def __init__(
        self,
        router: LLMRouter,
        tools: ToolRegistry,
        memory: Memory,
        max_iterations: int = _MAX_ITERATIONS,
    ):
        self._router = router
        self._tools = tools
        self._memory = memory
        self._max_iter = max_iterations
        self._llm_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0, name="llm")

    async def run(
        self, intent: str, session_id: str = "", agent: str = "orchestrator",
        user_id: str = "user_legacy",
    ) -> str:
        routing_cfg = getattr(self._router, "_routing", {})
        tier = classify_tier(intent, routing_cfg)
        if tier == "cheap":
            tier = STANDARD

        history = self._memory.get_context(agent, last_n=6, session_id=session_id or None)
        messages: list[dict] = []
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": intent})

        tools_schema = self._tools.as_openai_tools()
        iteration = 0
        last_error = ""

        while iteration < self._max_iter:
            iteration += 1
            try:
                if not self._llm_breaker.can_execute():
                    return f"LLM circuit open (too many failures). Try again later. Last error: {last_error}"

                async def _llm_call():
                    if tools_schema:
                        return await self._router.complete_with_tools(
                            messages, tools=tools_schema, tier=tier, session_id=session_id, agent=agent,
                        )
                    return await self._router.complete_messages(
                        messages, tier=tier, session_id=session_id, agent=agent,
                    )

                response = await with_retry(_llm_call, max_attempts=2, base_delay=1.0)
                self._llm_breaker.record_success()

            except Exception as exc:
                self._llm_breaker.record_failure()
                last_error = str(exc)
                return f"LLM failed at iteration {iteration}: {exc}"

            if not response.has_tool_calls:
                return response.text or "(no response)"

            messages.append({
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c in response.tool_calls
                ],
            })

            results = await self._tools.call_many(response.tool_calls)
            for tr in results:
                content = tr.content[:_MAX_TOOL_CHARS]
                messages.append({"role": "tool", "tool_call_id": tr.tool_call_id, "content": content})

        messages.append({
            "role": "user",
            "content": "Provide your final complete answer. Do not call more tools.",
        })
        try:
            return await self._router.chat(messages, tier=tier, session_id=session_id, agent=agent)
        except Exception as exc:
            return f"Max iterations reached. Error: {exc}"

    async def stream(
        self,
        messages: list[dict],
        *,
        session_id: str = "",
        agent: str = "chat_stream",
        user_id: str = "user_legacy",
        max_iterations: int = _STREAM_MAX_ITERATIONS,
    ) -> AsyncGenerator[dict, None]:
        """Streaming agent loop — yields progress events for /api/chat/stream.

        Yields:
          {type: "agent_iteration", n: int}
          {type: "tool_started", id, name, args}
          {type: "tool_finished", id, name, content, ok, duration_ms}
          {type: "approval_requested", approval_id, description}
          {type: "chunk", content: str}        (final answer, non-streamed)
          {type: "done", content, iterations}
          {type: "error", error}

        v1 uses non-streaming complete_with_tools (one chunk per LLM turn).
        Real per-token streaming for intermediate turns is a Phase 2 optimization.
        """
        tools_schema = self._tools.as_openai_tools() if self._tools else []
        iteration = 0
        last_error = ""
        # Always have a system message
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": "You are NEXUS-01."}, *messages]

        while iteration < max_iterations:
            iteration += 1
            yield {"type": "agent_iteration", "n": iteration, "max": max_iterations}

            # LLM call
            if not self._llm_breaker.can_execute():
                yield {"type": "error", "error": f"LLM circuit open. Last error: {last_error}"}
                return

            async def _llm_call():
                if tools_schema:
                    return await self._router.complete_with_tools(
                        messages, tools=tools_schema,
                        session_id=session_id, agent=agent, user_id=user_id,
                    )
                return await self._router.complete_messages(
                    messages, session_id=session_id, agent=agent, user_id=user_id,
                )

            try:
                response = await with_retry(_llm_call, max_attempts=2, base_delay=1.0)
                self._llm_breaker.record_success()
            except Exception as exc:
                self._llm_breaker.record_failure()
                last_error = str(exc)
                yield {"type": "error", "error": f"LLM failed at iteration {iteration}: {exc}"}
                return

            # No tool calls → emit text and done
            if not response.has_tool_calls:
                full_text = response.text or ""
                if full_text:
                    # v1: emit a single chunk with the full text. Phase 2 can stream tokens.
                    yield {"type": "chunk", "content": full_text}
                yield {"type": "done", "content": full_text, "iterations": iteration}
                return

            # Tool calls → append assistant message, then invoke tools
            messages.append({
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                    for c in response.tool_calls
                ],
            })

            blocked = False
            for tc in response.tool_calls:
                async for event in self._tools.stream_invoke(tc.name, tc.arguments, tc.id):
                    yield event
                    if event["type"] == "tool_blocked":
                        # Translate to approval_requested for the SSE consumer
                        yield {
                            "type": "approval_requested",
                            "approval_id": event.get("approval_id", ""),
                            "description": event.get("description", ""),
                            "tool": tc.name,
                        }
                        blocked = True
                    elif event["type"] == "tool_finished" and event.get("ok"):
                        content = (event.get("content") or "")[:_MAX_TOOL_CHARS]
                        messages.append({
                            "role": "tool", "tool_call_id": event["id"], "content": content,
                        })
                    elif event["type"] == "tool_finished" and not event.get("ok"):
                        # Error result — feed back to LLM as tool response
                        messages.append({
                            "role": "tool", "tool_call_id": event["id"],
                            "content": f"Error: {event.get('content', '')}",
                        })

            if blocked:
                # Stop iterating; user must approve before the next turn
                yield {"type": "error", "error": "Tool call requires approval"}
                return

        yield {"type": "error", "error": f"Max iterations ({max_iterations}) reached"}