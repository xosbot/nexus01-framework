from __future__ import annotations

import logging

from aiohttp import web

logger = logging.getLogger(__name__)


class WebhookServer:
    """Shared HTTP server for WhatsApp and Slack webhooks."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self._app = web.Application()
        self._runner: web.AppRunner | None = None
        self._whatsapp = None
        self._slack = None

        self._app.router.add_get("/health", self._health)
        self._app.router.add_get("/webhooks/whatsapp", self._whatsapp_verify)
        self._app.router.add_post("/webhooks/whatsapp", self._whatsapp_receive)
        self._app.router.add_post("/webhooks/slack", self._slack_receive)

    def attach_whatsapp(self, channel) -> None:
        self._whatsapp = channel

    def attach_slack(self, channel) -> None:
        self._slack = channel

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "nexus-gateway"})

    async def _whatsapp_verify(self, request: web.Request) -> web.Response:
        if not self._whatsapp:
            return web.Response(status=404, text="WhatsApp not configured")
        mode = request.query.get("hub.mode", "")
        token = request.query.get("hub.verify_token", "")
        challenge = request.query.get("hub.challenge", "")
        result = await self._whatsapp.verify_webhook(mode, token, challenge)
        if result:
            return web.Response(text=result)
        return web.Response(status=403, text="Forbidden")

    async def _whatsapp_receive(self, request: web.Request) -> web.Response:
        if not self._whatsapp:
            return web.Response(status=404)
        body = await request.json()
        await self._whatsapp.handle_webhook(body)
        return web.Response(text="OK")

    async def _slack_receive(self, request: web.Request) -> web.Response:
        if not self._slack:
            return web.Response(status=404)
        raw = await request.read()
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        if not self._slack.verify_signature(timestamp, raw, signature):
            return web.Response(status=401, text="Invalid signature")
        body = await request.json()
        challenge = await self._slack.handle_webhook(body)
        if challenge:
            return web.json_response(challenge)
        return web.Response(text="")

    async def start(self) -> None:
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("Webhook server listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
