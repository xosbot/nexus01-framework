from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from gateway.channels.base import BaseChannelAdapter, chunk_text
from gateway.types import ChannelKind, InboundMessage

if TYPE_CHECKING:
    from gateway.gateway import NexusGateway

logger = logging.getLogger(__name__)


class DiscordChannel(BaseChannelAdapter):
    name = ChannelKind.DISCORD.value

    def __init__(self, gateway: NexusGateway, token: str):
        super().__init__(gateway)
        self.token = token
        self._client = None

    async def start(self) -> None:
        try:
            import discord
        except ImportError as exc:
            raise RuntimeError("discord.py is required. pip install discord.py") from exc

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_ready():
            logger.info("Discord channel connected as %s", client.user)

        @client.event
        async def on_message(message):
            if message.author.bot:
                return
            if not self.is_user_allowed(str(message.author.id)):
                await message.channel.send("⛔ You are not authorized.")
                return

            text = message.content.strip()
            if not text:
                return
            if text.startswith("!"):
                text = text[1:].strip()

            async with message.channel.typing():
                inbound = InboundMessage(
                    channel=ChannelKind.DISCORD,
                    session_id=str(message.channel.id),
                    text=text,
                    user_id=str(message.author.id),
                    metadata={
                        "discord_guild_id": str(message.guild.id) if message.guild else "",
                        "discord_username": str(message.author),
                    },
                )
                response = await self.gateway.handle(inbound)
                if response.requires_approval:
                    await message.reply(
                        f"{response.text}\n\nReply `yes` to approve or `no` to cancel."
                    )
                else:
                    for chunk in chunk_text(response.text, limit=2000):
                        await message.channel.send(chunk)

        await client.start(self.token)

    async def stop(self) -> None:
        if self._client:
            await self._client.close()

    async def send(self, session_id: str, text: str, *, requires_approval: bool = False, approval_id: str = "") -> None:
        if not self._client:
            return
        channel = self._client.get_channel(int(session_id))
        if channel:
            for chunk in chunk_text(text, limit=2000):
                await channel.send(chunk)
