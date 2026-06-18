import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Callable, Coroutine

class Priority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

@dataclass
class Message:
    sender: str
    recipient: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    priority: Priority = Priority.NORMAL

class MessageBus:
    def __init__(self):
        self._queues: dict[str, asyncio.Queue[Message]] = {}
        self._subscribers: dict[str, list[Callable[[Message], Coroutine]]] = {}

    def _ensure_queue(self, name: str):
        if name not in self._queues:
            self._queues[name] = asyncio.Queue()

    async def publish(self, message: Message):
        self._ensure_queue(message.recipient)
        await self._queues[message.recipient].put(message)
        for cb in self._subscribers.get(message.recipient, []):
            asyncio.create_task(cb(message))

    def subscribe(self, agent_name: str, callback: Callable[[Message], Coroutine]):
        self._ensure_queue(agent_name)
        self._subscribers.setdefault(agent_name, []).append(callback)

    async def get(self, agent_name: str, timeout: float = 1.0) -> Message | None:
        self._ensure_queue(agent_name)
        try:
            return await asyncio.wait_for(self._queues[agent_name].get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

bus = MessageBus()
