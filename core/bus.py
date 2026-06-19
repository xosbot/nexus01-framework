import asyncio
import uuid
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
        self._pending: dict[str, asyncio.Future[Message]] = {}

    def _ensure_queue(self, name: str):
        if name not in self._queues:
            self._queues[name] = asyncio.Queue()

    async def publish(self, message: Message):
        self._ensure_queue(message.recipient)
        await self._queues[message.recipient].put(message)
        if message.type in ("response", "error") and self._correlation_id(message):
            self.handle_reply(message)
            return
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

    def _correlation_id(self, message: Message) -> str:
        return message.payload.get("_correlation_id", "")

    def resolve(self, correlation_id: str, response: Message) -> None:
        future = self._pending.get(correlation_id)
        if future and not future.done():
            future.set_result(response)

    def handle_reply(self, message: Message) -> None:
        correlation_id = self._correlation_id(message)
        if correlation_id:
            self.resolve(correlation_id, message)

    async def request(self, message: Message, timeout: float = 120.0) -> Message:
        correlation_id = uuid.uuid4().hex
        message.payload["_correlation_id"] = correlation_id
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Message] = loop.create_future()
        self._pending[correlation_id] = future
        try:
            await self.publish(message)
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"No response for {message.recipient} within {timeout}s")
        finally:
            self._pending.pop(correlation_id, None)

bus = MessageBus()
