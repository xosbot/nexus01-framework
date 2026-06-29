"""
Tool registry — registers, discovers, and executes agent tools.
Adapted from XClaw/core/tool_registry.py for NEXUS-01.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT = 60


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: str


class ToolRegistry:
    def __init__(self, tool_timeout: int = DEFAULT_TOOL_TIMEOUT) -> None:
        self._tools: dict[str, dict] = {}
        self._tool_timeout = tool_timeout

    def register(
        self,
        fn: Callable,
        name: str | None = None,
        description: str | None = None,
        parameters: dict | None = None,
    ) -> None:
        tool_name = name or fn.__name__
        self._tools[tool_name] = {
            "fn": fn,
            "description": description or (inspect.getdoc(fn) or f"Tool: {tool_name}"),
            "parameters": parameters or _infer_parameters(fn),
        }

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def as_openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": info["description"],
                    "parameters": info["parameters"],
                },
            }
            for name, info in self._tools.items()
        ]

    async def call(self, name: str, arguments: str = "{}", tool_call_id: str = "") -> ToolResult:
        if name not in self._tools:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=f"Error: tool '{name}' not found. Available: {self.tool_names()}",
            )
        try:
            args = json.loads(arguments) if arguments else {}
            fn = self._tools[name]["fn"]

            async def _execute():
                if asyncio.iscoroutinefunction(fn):
                    return await fn(**args)
                return await asyncio.get_event_loop().run_in_executor(None, lambda: fn(**args))

            result = await asyncio.wait_for(_execute(), timeout=self._tool_timeout)
            return ToolResult(tool_call_id=tool_call_id, name=name, content=str(result)[:4000])
        except asyncio.TimeoutError:
            logger.warning("[tools] %s timed out after %ds", name, self._tool_timeout)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=name,
                content=f"Error: tool '{name}' timed out after {self._tool_timeout}s",
            )
        except Exception as exc:
            logger.error("[tools] %s failed: %s", name, exc)
            return ToolResult(tool_call_id=tool_call_id, name=name, content=f"Error executing {name}: {exc}")

    async def stream_invoke(
        self, name: str, arguments: str, tool_call_id: str,
    ) -> AsyncGenerator[dict, None]:
        """Async generator that yields progress events for a single tool call.

        Events:
          {type: "tool_started", id, name, args}
          {type: "tool_finished", id, name, content, ok, duration_ms}
          {type: "tool_blocked", id, name, approval_id, description}  (cold-mode)

        If the tool function returns a dict with a "needs_approval" key, the
        generator emits tool_blocked instead of tool_finished. This lets cold-mode
        gated tools signal the agent loop that an approval is required.
        """
        import time
        start = time.monotonic()
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            yield {"type": "tool_finished", "id": tool_call_id, "name": name,
                   "content": f"Error: invalid JSON arguments: {arguments!r}",
                   "ok": False, "duration_ms": 0}
            return

        yield {"type": "tool_started", "id": tool_call_id, "name": name, "args": args}

        if name not in self._tools:
            yield {"type": "tool_finished", "id": tool_call_id, "name": name,
                   "content": f"Error: tool '{name}' not found. Available: {self.tool_names()}",
                   "ok": False, "duration_ms": int((time.monotonic() - start) * 1000)}
            return

        fn = self._tools[name]["fn"]

        async def _execute():
            if asyncio.iscoroutinefunction(fn):
                return await fn(**args)
            return await asyncio.get_event_loop().run_in_executor(None, lambda: fn(**args))

        try:
            result = await asyncio.wait_for(_execute(), timeout=self._tool_timeout)
        except asyncio.TimeoutError:
            yield {"type": "tool_finished", "id": tool_call_id, "name": name,
                   "content": f"Error: tool '{name}' timed out after {self._tool_timeout}s",
                   "ok": False, "duration_ms": int((time.monotonic() - start) * 1000)}
            return
        except Exception as exc:
            logger.error("[tools] %s failed: %s", name, exc)
            yield {"type": "tool_finished", "id": tool_call_id, "name": name,
                   "content": f"Error executing {name}: {exc}",
                   "ok": False, "duration_ms": int((time.monotonic() - start) * 1000)}
            return

        duration_ms = int((time.monotonic() - start) * 1000)

        # Tools that need approval return a dict with needs_approval=True
        if isinstance(result, dict) and result.get("needs_approval"):
            yield {"type": "tool_blocked", "id": tool_call_id, "name": name,
                   "approval_id": result.get("approval_id", ""),
                   "description": result.get("description", f"Tool '{name}' needs approval"),
                   "duration_ms": duration_ms}
            return

        content = str(result)[:4000] if result is not None else ""
        yield {"type": "tool_finished", "id": tool_call_id, "name": name,
               "content": content, "ok": True, "duration_ms": duration_ms}

    async def call_many(self, tool_calls: list) -> list[ToolResult]:
        return list(await asyncio.gather(*(self.call(tc.name, tc.arguments, tc.id) for tc in tool_calls)))


def _infer_parameters(fn: Callable) -> dict:
    sig = inspect.signature(fn)
    props: dict[str, dict] = {}
    required: list[str] = []
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "session_id"):
            continue
        annotation = param.annotation
        if annotation in (int,):
            json_type = "integer"
        elif annotation in (float,):
            json_type = "number"
        elif annotation in (bool,):
            json_type = "boolean"
        elif annotation in (list, list[str]):
            json_type = "array"
        else:
            json_type = "string"
        props[param_name] = {"type": json_type}
        if param.default == inspect.Parameter.empty:
            required.append(param_name)
    return {"type": "object", "properties": props, "required": required}
