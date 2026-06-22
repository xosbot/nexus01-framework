"""IVA Integration Hub — Connect apps to IVA.

Supports:
- Webhooks (receive events from external apps)
- API Connectors (connect to any REST/GraphQL API)
- MCP Protocol (Model Context Protocol)
- Custom Plugins (extensible plugin system)
"""

from __future__ import annotations

import json
import time
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class IntegrationType(Enum):
    WEBHOOK = "webhook"
    API = "api"
    MCP = "mcp"
    PLUGIN = "plugin"


@dataclass
class Integration:
    id: str
    name: str
    type: IntegrationType
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_event: str | None = None
    event_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "config": {k: v for k, v in self.config.items() if k != "secret"},
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_event": self.last_event,
            "event_count": self.event_count,
        }


@dataclass
class WebhookEvent:
    id: str
    source: str
    event_type: str
    payload: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    processed: bool = False
    result: Any = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "processed": self.processed,
        }


class IntegrationHub:
    """IVA's app integration system."""

    def __init__(self, memory=None, brain=None):
        self.memory = memory
        self.brain = brain
        self.integrations: dict[str, Integration] = {}
        self.webhook_queue: list[WebhookEvent] = []
        self._handlers: dict[str, Callable] = {}
        self._event_handlers: dict[str, list[Callable]] = {}
        self._register_builtin_handlers()

    def _register_builtin_handlers(self) -> None:
        self._handlers = {
            "github": self._handle_github,
            "slack": self._handle_slack,
            "discord": self._handle_discord,
            "jira": self._handle_jira,
            "linear": self._handle_linear,
            "notion": self._handle_notion,
            "zapier": self._handle_zapier,
        }

    def register_integration(self, name: str, integration_type: IntegrationType,
                              config: dict[str, Any]) -> Integration:
        integration = Integration(
            id=f"int_{name}_{int(time.time())}",
            name=name,
            type=integration_type,
            config=config,
        )
        self.integrations[integration.id] = integration
        logger.info(f"Registered integration: {name} ({integration_type.value})")
        return integration

    def unregister_integration(self, integration_id: str) -> bool:
        if integration_id in self.integrations:
            del self.integrations[integration_id]
            return True
        return False

    def get_integration(self, integration_id: str) -> Integration | None:
        return self.integrations.get(integration_id)

    def list_integrations(self) -> list[dict]:
        return [i.to_dict() for i in self.integrations.values()]

    async def process_webhook(self, source: str, event_type: str,
                               payload: dict, headers: dict = None) -> dict:
        integration = self._find_integration(source, IntegrationType.WEBHOOK)
        if not integration:
            return {"error": f"No webhook integration for {source}"}

        if not integration.enabled:
            return {"error": f"Integration {source} is disabled"}

        if integration.config.get("secret"):
            if not self._verify_signature(payload, headers, integration.config["secret"]):
                return {"error": "Invalid signature"}

        event = WebhookEvent(
            id=f"evt_{int(time.time())}",
            source=source,
            event_type=event_type,
            payload=payload,
        )

        self.webhook_queue.append(event)
        integration.last_event = datetime.now(timezone.utc).isoformat()
        integration.event_count += 1

        result = await self._dispatch_event(event)
        event.processed = True
        event.result = result

        if self.brain:
            self.brain.remember(
                f"Webhook event from {source}: {event_type}",
                memory_type="episodic",
                importance=0.4,
                tags=["webhook", source, event_type],
            )

        return {"event_id": event.id, "result": result}

    async def _dispatch_event(self, event: WebhookEvent) -> Any:
        handlers = self._event_handlers.get(event.source, [])
        if not handlers:
            handler = self._handlers.get(event.source)
            if handler:
                return await handler(event)

        results = []
        for handler in handlers:
            try:
                result = await handler(event)
                results.append(result)
            except Exception as e:
                logger.error(f"Handler error: {e}")
                results.append({"error": str(e)})

        return results[0] if len(results) == 1 else results

    def on_event(self, source: str, handler: Callable) -> None:
        if source not in self._event_handlers:
            self._event_handlers[source] = []
        self._event_handlers[source].append(handler)

    async def call_api(self, integration_id: str, method: str,
                        endpoint: str, data: dict = None,
                        headers: dict = None) -> dict:
        integration = self.integrations.get(integration_id)
        if not integration:
            return {"error": "Integration not found"}

        base_url = integration.config.get("base_url", "")
        api_key = integration.config.get("api_key", "")

        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        req_headers = {"Authorization": f"Bearer {api_key}"}
        if headers:
            req_headers.update(headers)

        async with httpx.AsyncClient() as client:
            try:
                if method.upper() == "GET":
                    resp = await client.get(url, headers=req_headers, params=data, timeout=30)
                elif method.upper() == "POST":
                    resp = await client.post(url, headers=req_headers, json=data, timeout=30)
                elif method.upper() == "PUT":
                    resp = await client.put(url, headers=req_headers, json=data, timeout=30)
                elif method.upper() == "DELETE":
                    resp = await client.delete(url, headers=req_headers, timeout=30)
                else:
                    return {"error": f"Unsupported method: {method}"}

                return {
                    "status": resp.status_code,
                    "data": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
                }
            except httpx.TimeoutException:
                return {"error": "Request timed out"}
            except Exception as e:
                return {"error": str(e)}

    def _find_integration(self, name: str, integration_type: IntegrationType) -> Integration | None:
        for integration in self.integrations.values():
            if integration.name == name and integration.type == integration_type:
                return integration
        return None

    def _verify_signature(self, payload: dict, headers: dict, secret: str) -> bool:
        if not headers:
            return False
        sig = headers.get("x-hub-signature-256") or headers.get("x-signature")
        if not sig:
            return False
        expected = "sha256=" + hmac.new(
            secret.encode(),
            json.dumps(payload, separators=(",", ":")).encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(sig, expected)

    async def _handle_github(self, event: WebhookEvent) -> dict:
        action = event.payload.get("action", "")
        repo = event.payload.get("repository", {}).get("full_name", "")

        if event.event_type == "push":
            commits = event.payload.get("commits", [])
            return {
                "action": "push",
                "repo": repo,
                "commits": len(commits),
                "message": f"Push to {repo} with {len(commits)} commits",
            }
        elif event.event_type == "issues":
            issue = event.payload.get("issue", {})
            return {
                "action": action,
                "repo": repo,
                "issue": issue.get("title", ""),
            }

        return {"action": event.event_type, "repo": repo}

    async def _handle_slack(self, event: WebhookEvent) -> dict:
        return {"action": event.event_type, "payload": event.payload}

    async def _handle_discord(self, event: WebhookEvent) -> dict:
        return {"action": event.event_type, "payload": event.payload}

    async def _handle_jira(self, event: WebhookEvent) -> dict:
        return {"action": event.event_type, "payload": event.payload}

    async def _handle_linear(self, event: WebhookEvent) -> dict:
        return {"action": event.event_type, "payload": event.payload}

    async def _handle_notion(self, event: WebhookEvent) -> dict:
        return {"action": event.event_type, "payload": event.payload}

    async def _handle_zapier(self, event: WebhookEvent) -> dict:
        return {"action": event.event_type, "payload": event.payload}

    def get_webhook_url(self, integration_id: str) -> str | None:
        integration = self.integrations.get(integration_id)
        if not integration or integration.type != IntegrationType.WEBHOOK:
            return None
        return integration.config.get("webhook_url")

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        return [e.to_dict() for e in self.webhook_queue[-limit:]]
