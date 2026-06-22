"""Message bus factory — local asyncio or Redis Streams."""

from __future__ import annotations

import logging

from core.bus import MessageBus

logger = logging.getLogger(__name__)


async def create_bus(backend: str = "local", redis_url: str = "redis://localhost:6379") -> MessageBus:
    if backend == "redis":
        from core.redis_bus import RedisMessageBus
        redis_bus = RedisMessageBus(redis_url)
        await redis_bus.connect()
        return redis_bus
    return MessageBus()


def set_global_bus(msg_bus: MessageBus) -> None:
    import core.bus as bus_module
    bus_module.bus = msg_bus
