import asyncio
from enum import Enum
from typing import Any, Callable, Coroutine
from core.bus import Message, MessageBus
from core.memory import Memory
from config import config

class AgentStatus(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    ERROR = "error"

class BaseAgent:
    def __init__(self, name: str, llm, memory: Memory, rag=None):
        self.name = name
        self.llm = llm
        self.memory = memory
        self.rag = rag
        self.status = AgentStatus.IDLE
        self.tools: dict[str, Callable] = {}
        self._bus: MessageBus | None = None

    def set_bus(self, msg_bus: MessageBus):
        self._bus = msg_bus
        msg_bus.subscribe(self.name, self._handle_message)

    async def _handle_message(self, message: Message):
        try:
            self.status = AgentStatus.THINKING
            response = await self.on_message(message)
            if response is not None and self._bus:
                correlation_id = message.payload.get("_correlation_id")
                await self._bus.publish(Message(
                    sender=self.name,
                    recipient=message.sender,
                    type="response",
                    payload={"data": response, "_correlation_id": correlation_id},
                ))
        except Exception as e:
            self.status = AgentStatus.ERROR
            if self._bus:
                correlation_id = message.payload.get("_correlation_id")
                await self._bus.publish(Message(
                    sender=self.name,
                    recipient=message.sender,
                    type="error",
                    payload={"error": str(e), "_correlation_id": correlation_id},
                ))
        finally:
            self.status = AgentStatus.IDLE

    async def think(self, prompt: str, session_id: str | None = None, use_rag: bool = True) -> str:
        if use_rag and self.rag and config.rag_enabled:
            context = self.rag.format_context(prompt, n=3)
            if context:
                prompt = f"## Relevant Knowledge\n{context}\n\n## Request\n{prompt}"

        history = self.memory.get_context(self.name, session_id=session_id)
        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": prompt})
        return await self.llm.complete(messages, session_id=session_id or "", agent=self.name)

    async def act(self, tool_name: str, **kwargs) -> Any:
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not available")
        self.status = AgentStatus.ACTING
        try:
            fn = self.tools[tool_name]
            result = await fn(**kwargs) if asyncio.iscoroutinefunction(fn) else fn(**kwargs)
            return result
        finally:
            self.status = AgentStatus.IDLE

    async def on_message(self, message: Message) -> Any:
        raise NotImplementedError
