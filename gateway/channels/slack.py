from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import TYPE_CHECKING

import httpx

from gateway.channels.base import BaseChannelAdapter, chunk_text
from gateway.types import ChannelKind, InboundMessage

if TYPE_CHECKING:
    from gateway.gateway import NexusGateway

logger = logging.getLogger(__name__)


class SlackChannel(BaseChannelAdapter):
    """Slack Events API — webhook inbound, chat.postMessage outbound."""

    name = ChannelKind.SLACK.value

    def __init__(self, gateway: NexusGateway, bot_token: str, signing_secret: str):
        super().__init__(gateway)
        self.bot_token = bot_token
        self.signing_secret = signing_secret
        self._client = httpx.AsyncClient(timeout=30.0)
        self._processed_events: dict[str, float] = {}

    async def start(self) -> None:
        logger.info("Slack channel ready (webhook mode on /webhooks/slack)")

    async def stop(self) -> None:
        await self._client.aclose()

    def verify_signature(self, timestamp: str, body: bytes, signature: str) -> bool:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
        base = f"v0:{timestamp}:{body.decode()}"
        digest = hmac.new(self.signing_secret.encode(), base.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"v0={digest}", signature)

    async def handle_webhook(self, body: dict) -> dict | None:
        if body.get("type") == "url_verification":
            return {"challenge": body.get("challenge")}

        event = body.get("event", {})
        if event.get("type") != "message" or event.get("subtype"):
            return None

        event_id = body.get("event_id", "")
        if event_id:
            now = time.time()
            self._processed_events = {k: v for k, v in self._processed_events.items() if now - v < 300}
            if event_id in self._processed_events:
                return None
            self._processed_events[event_id] = now

        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        text = event.get("text", "").strip()
        if not text or event.get("bot_id"):
            return None
        if not self.is_user_allowed(user_id):
            await self.send(channel_id, "⛔ You are not authorized.")
            return None

        inbound = InboundMessage(
            channel=ChannelKind.SLACK,
            session_id=channel_id,
            text=text,
            user_id=user_id,
            metadata={"slack_thread_ts": event.get("thread_ts", event.get("ts", ""))},
        )
        response = await self.gateway.handle(inbound)
        if response.requires_approval:
            text_out = f"{response.text}\n\nReply *yes* to approve or *no* to cancel."
        else:
            text_out = response.text
        await self.send(channel_id, text_out)
        return None

    async def send(self, session_id: str, text: str, *, requires_approval: bool = False, approval_id: str = "") -> None:
        url = "https://slack.com/api/chat.postMessage"
        headers = {"Authorization": f"Bearer {self.bot_token}", "Content-Type": "application/json"}
        for chunk in chunk_text(text, limit=3900):
            payload = {"channel": session_id, "text": chunk}
            resp = await self._client.post(url, json=payload, headers=headers)
            data = resp.json()
            if not data.get("ok"):
                logger.error("Slack send failed: %s", data.get("error"))
