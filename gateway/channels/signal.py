"""Signal channel via signal-cli HTTP daemon."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from gateway.channels.base import BaseChannelAdapter, chunk_text
from gateway.types import ChannelKind, InboundMessage

if TYPE_CHECKING:
    from gateway.gateway import NexusGateway

logger = logging.getLogger(__name__)


class SignalChannel(BaseChannelAdapter):
    name = ChannelKind.SIGNAL.value

    def __init__(self, gateway: NexusGateway, api_url: str, account: str):
        super().__init__(gateway)
        self.api_url = api_url.rstrip("/")
        self.account = account
        self._client = httpx.AsyncClient(timeout=30.0)
        self._poll_task = None

    async def start(self) -> None:
        import asyncio
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Signal channel polling %s", self.api_url)

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
        await self._client.aclose()

    async def _poll_loop(self) -> None:
        import asyncio
        while True:
            try:
                resp = await self._client.get(f"{self.api_url}/v1/receive/{self.account}")
                if resp.status_code == 200:
                    for envelope in resp.json():
                        await self._handle_envelope(envelope)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Signal poll: %s", exc)
            await asyncio.sleep(2)

    async def _handle_envelope(self, envelope: dict) -> None:
        data = envelope.get("envelope", envelope)
        source = data.get("sourceNumber") or data.get("source", "")
        msg = data.get("dataMessage", {})
        text = msg.get("message", "").strip()
        if not text or not self.is_user_allowed(source):
            return
        inbound = InboundMessage(
            channel=ChannelKind.SIGNAL,
            session_id=source,
            text=text,
            user_id=source,
            metadata={"signal_source": source},
        )
        response = await self.gateway.handle(inbound)
        out = response.text
        if response.requires_approval:
            out += "\n\nReply YES to approve or NO to cancel."
        await self.send(source, out)

    async def send(self, session_id: str, text: str, *, requires_approval: bool = False, approval_id: str = "") -> None:
        for chunk in chunk_text(text, limit=2000):
            await self._client.post(
                f"{self.api_url}/v2/send",
                json={"message": chunk, "number": self.account, "recipients": [session_id]},
            )
