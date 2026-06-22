"""Redis Streams message bus — durable swap-in for asyncio.Queue bus."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

from core.bus import Message, MessageBus, Priority

logger = logging.getLogger(__name__)
STREAM_PREFIX = "nexus:inbox:"


def _serialize(msg: Message) -> dict:
    return {
        "sender": msg.sender,
        "recipient": msg.recipient,
        "type": msg.type,
        "payload": msg.payload,
        "timestamp": msg.timestamp.isoformat(),
        "priority": int(msg.priority),
    }


def _deserialize(data: dict) -> Message:
    return Message(
        sender=data["sender"],
        recipient=data["recipient"],
        type=data["type"],
        payload=data.get("payload", {}),
        timestamp=datetime.fromisoformat(data["timestamp"]),
        priority=Priority(data.get("priority", Priority.NORMAL)),
    )


class RedisMessageBus(MessageBus):
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        super().__init__()
        self._redis_url = redis_url
        self._redis = None
        self._listener_task: asyncio.Task | None = None
        self._running = False

    async def connect(self) -> None:
        import os
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            self._running = True
            if os.getenv("NEXUS_REDIS_CONSUMER", "").lower() == "true":
                self._listener_task = asyncio.create_task(self._listen())
            logger.info("Redis bus connected: %s", self._redis_url)
        except Exception as exc:
            logger.error("Redis bus connection failed: %s", exc)
            raise

    async def publish(self, message: Message) -> None:
        if self._redis:
            stream = f"{STREAM_PREFIX}{message.recipient}"
            await self._redis.xadd(stream, {"data": json.dumps(_serialize(message))}, maxlen=10000)
        if message.type in ("response", "error") and self._correlation_id(message):
            self.handle_reply(message)
            return
        for cb in self._subscribers.get(message.recipient, []):
            asyncio.create_task(cb(message))

    async def _listen(self) -> None:
        streams: dict[str, str] = {}
        while self._running:
            try:
                for name in list(self._subscribers.keys()):
                    key = f"{STREAM_PREFIX}{name}"
                    if key not in streams:
                        streams[key] = "$"
                        try:
                            await self._redis.xgroup_create(key, "nexus-workers", id="0", mkstream=True)
                        except Exception:
                            pass
                if not streams:
                    await asyncio.sleep(0.5)
                    continue
                results = await self._redis.xreadgroup(
                    "nexus-workers", f"worker-{uuid.uuid4().hex[:6]}",
                    streams, count=10, block=1000,
                )
                for stream_name, entries in results or []:
                    recipient = stream_name.replace(STREAM_PREFIX, "")
                    for entry_id, fields in entries:
                        data = json.loads(fields["data"])
                        msg = _deserialize(data)
                        if msg.type in ("response", "error") and self._correlation_id(msg):
                            self.handle_reply(msg)
                        else:
                            for cb in self._subscribers.get(recipient, []):
                                asyncio.create_task(cb(msg))
                        await self._redis.xack(stream_name, "nexus-workers", entry_id)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Redis listener: %s", exc)
                await asyncio.sleep(1)

    async def disconnect(self) -> None:
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._redis:
            await self._redis.aclose()
