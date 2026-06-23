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


class WhatsAppChannel(BaseChannelAdapter):
    """Meta WhatsApp Business Cloud API — webhook inbound, Graph API outbound."""

    name = ChannelKind.WHATSAPP.value

    def __init__(
        self,
        gateway: NexusGateway,
        token: str,
        phone_number_id: str,
        verify_token: str,
        app_secret: str = "",
    ):
        super().__init__(gateway)
        self.token = token
        self.phone_number_id = phone_number_id
        self.verify_token = verify_token
        self.app_secret = app_secret
        self._client = httpx.AsyncClient(timeout=30.0)

    async def start(self) -> None:
        logger.info("WhatsApp channel ready (webhook mode on /webhooks/whatsapp)")

    async def stop(self) -> None:
        await self._client.aclose()

    def verify_signature(self, body: bytes, signature: str) -> bool:
        if not self.app_secret:
            return True
        expected = hmac.new(
            self.app_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    async def verify_webhook(self, mode: str, token: str, challenge: str) -> str | None:
        if mode == "subscribe" and token == self.verify_token:
            return challenge
        return None

    async def handle_webhook(self, body: dict, raw_body: bytes = b"", signature: str = "") -> None:
        if signature and not self.verify_signature(raw_body, signature):
            logger.warning("WhatsApp webhook signature verification failed")
            return
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    if message.get("type") != "text":
                        continue
                    from_id = message.get("from", "")
                    text = message.get("text", {}).get("body", "").strip()
                    if not text or not self.is_user_allowed(from_id):
                        if not self.is_user_allowed(from_id):
                            await self.send(from_id, "⛔ You are not authorized.")
                        continue

                    inbound = InboundMessage(
                        channel=ChannelKind.WHATSAPP,
                        session_id=from_id,
                        text=text,
                        user_id=from_id,
                        metadata={"whatsapp_message_id": message.get("id", "")},
                    )
                    response = await self.gateway.handle(inbound)
                    if response.requires_approval:
                        text_out = (
                            f"{response.text}\n\n"
                            "Reply *YES* to approve or *NO* to cancel."
                        )
                    else:
                        text_out = response.text
                    await self.send(from_id, text_out)

    async def send(self, session_id: str, text: str, *, requires_approval: bool = False, approval_id: str = "") -> None:
        url = f"{GRAPH_API}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        for chunk in chunk_text(text, limit=4096):
            payload = {
                "messaging_product": "whatsapp",
                "to": session_id,
                "type": "text",
                "text": {"body": chunk},
            }
            resp = await self._client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error("WhatsApp send failed: %s %s", resp.status_code, resp.text)
