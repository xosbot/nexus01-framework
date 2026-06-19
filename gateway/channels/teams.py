"""Microsoft Teams Bot Framework channel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from gateway.channels.base import BaseChannelAdapter, chunk_text
from gateway.types import ChannelKind, InboundMessage

if TYPE_CHECKING:
    from gateway.gateway import NexusGateway

logger = logging.getLogger(__name__)


class TeamsChannel(BaseChannelAdapter):
    name = ChannelKind.TEAMS.value

    def __init__(self, gateway: NexusGateway, app_id: str, app_password: str):
        super().__init__(gateway)
        self.app_id = app_id
        self.app_password = app_password
        self._client = httpx.AsyncClient(timeout=30.0)
        self._token: str | None = None

    async def start(self) -> None:
        logger.info("Teams channel ready (webhook mode on /webhooks/teams)")

    async def stop(self) -> None:
        await self._client.aclose()

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        resp = await self._client.post(
            "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.app_id,
                "client_secret": self.app_password,
                "scope": "https://api.botframework.com/.default",
            },
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    async def handle_webhook(self, body: dict) -> dict:
        if body.get("type") != "message":
            return {}
        text = body.get("text", "").strip()
        user_id = body.get("from", {}).get("id", "")
        conversation_id = body.get("conversation", {}).get("id", "")
        if not text or not self.is_user_allowed(user_id):
            return {}
        inbound = InboundMessage(
            channel=ChannelKind.TEAMS,
            session_id=conversation_id,
            text=text,
            user_id=user_id,
            metadata={"teams_activity": body},
        )
        response = await self.gateway.handle(inbound)
        reply = response.text
        if response.requires_approval:
            reply += "\n\nReply **yes** to approve or **no** to cancel."
        await self._reply(body.get("serviceUrl", ""), conversation_id, body.get("id", ""), reply)
        return {}

    async def _reply(self, service_url: str, conversation_id: str, reply_to_id: str, text: str) -> None:
        token = await self._get_token()
        url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        for chunk in chunk_text(text, limit=4000):
            await self._client.post(url, headers=headers, json={"type": "message", "text": chunk, "replyToId": reply_to_id})

    async def send(self, session_id: str, text: str, *, requires_approval: bool = False, approval_id: str = "") -> None:
        pass
