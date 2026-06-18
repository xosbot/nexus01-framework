import asyncio
from enum import Enum
from typing import Any, Callable, Coroutine
from core.bus import Message, MessageBus, bus
from core.llm import OllamaClient
from core.memory import Memory
from config import config

class AgentStatus(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    ERROR = "error"

class BaseAgent:
    def __init__(self, name: str, llm: OllamaClient, memory: Memory):
        self.name = name
        self.llm = llm
        self.memory = memory
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
            if response and self._bus:
                await self._bus.publish(Message(
                    sender=self.name,
                    recipient=message.sender,
                    type="response",
                    payload={"data": response}
                ))
        except Exception as e:
            self.status = AgentStatus.ERROR
            if self._bus:
                await self._bus.publish(Message(
                    sender=self.name,
                    recipient=message.sender,
                    type="error",
                    payload={"error": str(e)}
                ))
        finally:
            self.status = AgentStatus.IDLE

    async def think(self, prompt: str) -> str:
        context = self.memory.get_context(self.name)
        messages = [{"role": m["role"], "content": m["content"]} for m in context]
        messages.append({"role": "user", "content": prompt})
        return await self.llm.complete(messages)

    async def act(self, tool_name: str, **kwargs) -> Any:
        if tool_name not in self.tools:
            raise ValueError(f"Tool '{tool_name}' not available")
        self.status = AgentStatus.ACTING
        try:
            result = await self.tools[tool_name](**kwargs) if asyncio.iscoroutinefunction(self.tools[tool_name]) else self.tools[tool_name](**kwargs)
            return result
        finally:
            self.status = AgentStatus.IDLE

    async def on_message(self, message: Message) -> Any:
        raise NotImplementedError
