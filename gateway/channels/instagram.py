from __future__ import annotations

import hashlib
import hmac
import logging
from typing import TYPE_CHECKING

import httpx

from gateway.channels.base import BaseChannelAdapter, chunk_text
from gateway.types import ChannelKind, InboundMessage

if TYPE_CHECKING:
    from gateway.gateway import NexusGateway

logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v21.0"


class InstagramChannel(BaseChannelAdapter):
    """Meta Instagram Messaging API — webhook inbound, Graph API outbound."""

    name = ChannelKind.INSTAGRAM.value

    def __init__(
        self,
        gateway: NexusGateway,
        token: str,
        page_id: str,
        app_secret: str = "",
    ):
        super().__init__(gateway)
        self.token = token
        self.page_id = page_id
        self.app_secret = app_secret
        self._client = httpx.AsyncClient(timeout=30.0)

    async def start(self) -> None:
        logger.info("Instagram channel ready (webhook mode on /webhooks/instagram)")

    async def stop(self) -> None:
        await self._client.aclose()

    def verify_signature(self, body: bytes, signature: str) -> bool:
        if not self.app_secret:
            return True
        expected = hmac.new(
            self.app_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    async def handle_webhook(self, body: dict, raw_body: bytes = b"", signature: str = "") -> None:
        if signature and not self.verify_signature(raw_body, signature):
            logger.warning("Instagram webhook signature verification failed")
            return

        for entry in body.get("entry", []):
            messaging = entry.get("messaging", [])
            for event in messaging:
                sender = event.get("sender", {}).get("id", "")
                message = event.get("message", {})
                if message.get("type") != "text":
                    continue
                text = message.get("text", "").strip()
                mid = message.get("mid", "")
                if not text or not self.is_user_allowed(sender):
                    if not self.is_user_allowed(sender):
                        await self.send(sender, "⛔ You are not authorized.")
                    continue

                inbound = InboundMessage(
                    channel=ChannelKind.INSTAGRAM,
                    session_id=sender,
                    text=text,
                    user_id=sender,
                    metadata={"instagram_message_id": mid},
                )
                response = await self.gateway.handle(inbound)
                if response.requires_approval:
                    text_out = (
                        f"{response.text}\n\n"
                        "Reply *YES* to approve or *NO* to cancel."
                    )
                else:
                    text_out = response.text
                await self.send(sender, text_out)

    async def send(self, session_id: str, text: str, *, requires_approval: bool = False, approval_id: str = "") -> None:
        url = f"{GRAPH_API}/{self.page_id}/messages"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        for chunk in chunk_text(text, limit=2000):
            payload = {
                "recipient": {"id": session_id},
                "message": {"text": chunk},
            }
            resp = await self._client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error("Instagram send failed: %s %s", resp.status_code, resp.text)
