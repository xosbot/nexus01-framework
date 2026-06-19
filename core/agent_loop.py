"""ReAct agent loop — reason + act with parallel tool execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from core.llm_router import STANDARD, classify_tier

if TYPE_CHECKING:
    from core.llm_router import LLMRouter
    from core.memory import Memory
    from core.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)
_MAX_ITERATIONS = 15
_MAX_TOOL_CHARS = 3000


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

    async def run(self, intent: str, session_id: str = "", agent: str = "orchestrator") -> str:
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

        while iteration < self._max_iter:
            iteration += 1
            try:
                if tools_schema:
                    response = await self._router.complete_with_tools(
                        messages, tools=tools_schema, tier=tier,
                        session_id=session_id, agent=agent,
                    )
                else:
                    response = await self._router.complete_messages(
                        messages, tier=tier, session_id=session_id, agent=agent,
                    )
            except Exception as exc:
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
