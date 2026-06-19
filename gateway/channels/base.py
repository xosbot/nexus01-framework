from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gateway.gateway import NexusGateway

logger = logging.getLogger(__name__)


def chunk_text(text: str, limit: int = 4000) -> list[str]:
    text = (text or "").strip() or "Done."
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return [c for c in chunks if c]


class BaseChannelAdapter(abc.ABC):
    name: str = "base"

    def __init__(self, gateway: NexusGateway):
        self.gateway = gateway

    @abc.abstractmethod
    async def start(self) -> None:
        """Start listening for inbound messages."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down."""

    @abc.abstractmethod
    async def send(self, session_id: str, text: str, *, requires_approval: bool = False, approval_id: str = "") -> None:
        """Send outbound text to a session."""

    def is_user_allowed(self, user_id: str) -> bool:
        return self.gateway.is_user_allowed(self.name, user_id)
