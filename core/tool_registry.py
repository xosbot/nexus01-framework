"""
Tool registry — registers, discovers, and executes agent tools.
Adapted from XClaw/core/tool_registry.py for NEXUS-01.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: str


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}

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
            if asyncio.iscoroutinefunction(fn):
                result = await fn(**args)
            else:
                result = await asyncio.get_event_loop().run_in_executor(None, lambda: fn(**args))
            return ToolResult(tool_call_id=tool_call_id, name=name, content=str(result)[:4000])
        except Exception as exc:
            logger.error("[tools] %s failed: %s", name, exc)
            return ToolResult(tool_call_id=tool_call_id, name=name, content=f"Error executing {name}: {exc}")

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
