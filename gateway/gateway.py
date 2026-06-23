import logging
import re

from core.bus import Message, MessageBus
from gateway.approvals import ApprovalManager
from gateway.types import GatewayResponse, InboundMessage

logger = logging.getLogger(__name__)

EXEC_PATTERN = re.compile(r"^\s*exec\s+", re.I)
EXEC_INTENT = re.compile(r"\b(exec|run|command|shell|deploy|install)\b", re.I)
APPROVE_WORDS = frozenset({"yes", "y", "approve", "confirm", "ok", "✅"})
CANCEL_WORDS = frozenset({"no", "n", "cancel", "abort", "stop", "❌"})

CUSTOMER_CHANNELS = frozenset({"whatsapp", "instagram"})


class NexusGateway:
    """Normalizes inbound messages from any channel and routes them through the message bus."""

    def __init__(
        self,
        bus: MessageBus,
        allowed_users: dict[str, list[str]] | None = None,
        require_approval_for_exec: bool = True,
        require_approval_for_replies: bool = True,
    ):
        self.bus = bus
        self.approvals = ApprovalManager()
        self.allowed_users = allowed_users or {}
        self.require_approval_for_exec = require_approval_for_exec
        self.require_approval_for_replies = require_approval_for_replies
        self._channels: dict[str, object] = {}

    def register_channel(self, adapter) -> None:
        self._channels[adapter.name] = adapter

    def get_channel(self, name: str):
        return self._channels.get(name)

    def is_user_allowed(self, channel: str, user_id: str) -> bool:
        allowlist = self.allowed_users.get(channel, [])
        if not allowlist:
            return True
        return str(user_id) in {str(u) for u in allowlist}

    async def handle(self, inbound: InboundMessage) -> GatewayResponse:
        channel = inbound.channel.value
        if inbound.user_id and not self.is_user_allowed(channel, inbound.user_id):
            return GatewayResponse("⛔ You are not authorized to use this bot.")

        if inbound.metadata.get("approval_decision") is not None:
            return await self._handle_approval_decision(inbound)

        if self._is_approval_reply(inbound.text):
            pending = self.approvals.get_for_session(channel, inbound.session_id)
            if pending:
                approved = inbound.text.strip().lower() in APPROVE_WORDS
                inbound.metadata["approval_decision"] = approved
                inbound.metadata["approval_id"] = pending.id
                return await self._handle_approval_decision(inbound)

        if self.require_approval_for_exec and self._needs_approval(inbound.text):
            approval = self.approvals.create(
                channel=channel,
                session_id=inbound.session_id,
                text=inbound.text,
                payload={"metadata": inbound.metadata},
            )
            cmd = inbound.text.split(maxsplit=1)[1] if EXEC_PATTERN.match(inbound.text) else inbound.text
            return GatewayResponse(
                text=(
                    "⚠️ *Execution approval required*\n\n"
                    f"Command: `{cmd}`\n\n"
                    "This will run on the host system. Approve?"
                ),
                requires_approval=True,
                approval_id=approval.id,
            )

        if self.require_approval_for_replies and channel in CUSTOMER_CHANNELS:
            return await self._handle_customer_reply(inbound)

        return await self._dispatch(inbound)

    async def _handle_customer_reply(self, inbound: InboundMessage) -> GatewayResponse:
        channel = inbound.channel.value
        response = await self._dispatch(inbound)
        if response.raw.get("status") in ("error", "blocked"):
            return response

        approval = self.approvals.create(
            channel=channel,
            session_id=inbound.session_id,
            text=inbound.text,
            payload={
                "metadata": inbound.metadata,
                "draft_reply": response.text,
                "channel": channel,
            },
            ttl=86400,
        )
        return GatewayResponse(
            text=(
                "📝 *Draft reply queued for review*\n\n"
                f"To: {inbound.session_id}\n"
                f"Draft: {response.text[:200]}{'...' if len(response.text) > 200 else ''}\n\n"
                "Approve via dashboard or reply YES/NO."
            ),
            requires_approval=True,
            approval_id=approval.id,
        )

    async def _handle_approval_decision(self, inbound: InboundMessage) -> GatewayResponse:
        channel = inbound.channel.value
        approved = inbound.metadata.get("approval_decision")
        if approved is None:
            approved = inbound.text.strip().lower() in APPROVE_WORDS

        pending = self.approvals.get(inbound.metadata.get("approval_id", "")) or self.approvals.get_for_session(
            channel, inbound.session_id
        )
        if not pending:
            return GatewayResponse("No pending approval found (it may have expired).")

        self.approvals.clear(pending.id)
        if not approved:
            return GatewayResponse("❌ Cancelled. No action taken.")

        draft_reply = pending.payload.get("draft_reply")
        if draft_reply and pending.payload.get("channel") in CUSTOMER_CHANNELS:
            target_channel = pending.payload["channel"]
            ch = self.get_channel(target_channel)
            if ch:
                await ch.send(pending.session_id, draft_reply)
                return GatewayResponse(f"✅ Reply sent to {target_channel}.")
            return GatewayResponse(f"⚠️ Channel {target_channel} not available.")

        inbound.text = pending.text
        inbound.metadata = {**pending.payload.get("metadata", {}), **inbound.metadata, "approved": True}
        response = await self._dispatch(inbound, force_exec=True)
        response.text = f"✅ Approved.\n\n{response.text}"
        return response

    async def _dispatch(self, inbound: InboundMessage, force_exec: bool = False) -> GatewayResponse:
        channel = inbound.channel.value
        sender = f"{channel}:{inbound.session_id}"
        payload = {
            "text": inbound.text,
            "channel": channel,
            "session_id": inbound.session_id,
            "user_id": inbound.user_id,
            **inbound.metadata,
        }
        if force_exec or EXEC_PATTERN.match(inbound.text):
            parts = inbound.text.split(maxsplit=1)
            payload["permission"] = "EXECUTE"
            if len(parts) > 1 and parts[0].lower() == "exec":
                payload["text"] = parts[1]
                payload["fallback_script"] = "echo rollback"

        try:
            reply = await self.bus.request(
                Message(sender=sender, recipient="orchestrator", type="task", payload=payload),
                timeout=180.0,
            )
        except TimeoutError:
            return GatewayResponse("⏱ Request timed out. Try a simpler query.")

        if reply.type == "error":
            return GatewayResponse(f"❌ Error: {reply.payload.get('error', 'unknown')}")

        data = reply.payload.get("data", {})
        if data.get("status") == "blocked":
            reasons = data.get("reasons", [])
            return GatewayResponse("🧊 Blocked by Cold Mode:\n" + "\n".join(f"• {r}" for r in reasons), raw=data)

        if data.get("status") == "error":
            return GatewayResponse(f"❌ {data.get('error', 'Request failed')}", raw=data)

        output = data.get("output") or self._format_output(data)
        route = data.get("route", [])
        prefix = f"🔗 Route: {' → '.join(route)}\n\n" if route else ""
        return GatewayResponse(prefix + output, route=route, raw=data)

    @staticmethod
    def _format_output(data: dict) -> str:
        steps = data.get("steps", [])
        if not steps:
            return str(data)
        last = steps[-1].get("result", {})
        if isinstance(last, dict):
            return last.get("analysis") or last.get("stdout") or str(last)
        return str(last)

    @staticmethod
    def _needs_approval(text: str) -> bool:
        if EXEC_PATTERN.match(text):
            return True
        return bool(EXEC_INTENT.search(text)) and not text.lower().startswith(("osint", "analyst", "analyze"))

    @staticmethod
    def _is_approval_reply(text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in APPROVE_WORDS or normalized in CANCEL_WORDS
