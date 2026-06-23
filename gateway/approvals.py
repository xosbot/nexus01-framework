import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class PendingApproval:
    id: str
    channel: str
    session_id: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    ttl: timedelta = field(default_factory=lambda: timedelta(minutes=10))

    @property
    def key(self) -> str:
        return f"{self.channel}:{self.session_id}"

    @property
    def expired(self) -> bool:
        return datetime.now() - self.created_at > self.ttl

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "channel": self.channel,
            "session_id": self.session_id,
            "text": self.text,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
            "expired": self.expired,
        }


class ApprovalManager:
    TTL = timedelta(minutes=10)

    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        self._by_key: dict[str, str] = {}
        self._expired: list[PendingApproval] = []

    def create(
        self,
        channel: str,
        session_id: str,
        text: str,
        payload: dict | None = None,
        ttl: timedelta | None = None,
    ) -> PendingApproval:
        self.clear_session(channel, session_id)
        approval = PendingApproval(
            id=uuid.uuid4().hex[:12],
            channel=channel,
            session_id=session_id,
            text=text,
            payload=payload or {},
            ttl=ttl or self.TTL,
        )
        self._pending[approval.id] = approval
        self._by_key[approval.key] = approval.id
        return approval

    def get_for_session(self, channel: str, session_id: str) -> PendingApproval | None:
        approval_id = self._by_key.get(f"{channel}:{session_id}")
        if not approval_id:
            return None
        approval = self._pending.get(approval_id)
        if approval and approval.expired:
            self._expire(approval_id)
            return None
        return approval

    def get(self, approval_id: str) -> PendingApproval | None:
        approval = self._pending.get(approval_id)
        if approval and approval.expired:
            self._expire(approval_id)
            return None
        return approval

    def list_pending(self, include_expired: bool = False) -> list[PendingApproval]:
        self._sweep_expired()
        pending = list(self._pending.values())
        if include_expired:
            pending.extend(self._expired)
        return pending

    def _sweep_expired(self) -> None:
        expired_ids = [
            aid for aid, a in self._pending.items()
            if a.expired
        ]
        for aid in expired_ids:
            self._expire(aid)

    def _expire(self, approval_id: str) -> None:
        approval = self._pending.pop(approval_id, None)
        if approval:
            self._by_key.pop(approval.key, None)
            self._expired.append(approval)
            if len(self._expired) > 100:
                self._expired = self._expired[-100:]

    def clear(self, approval_id: str) -> None:
        approval = self._pending.pop(approval_id, None)
        if approval:
            self._by_key.pop(approval.key, None)

    def clear_session(self, channel: str, session_id: str) -> None:
        approval = self.get_for_session(channel, session_id)
        if approval:
            self.clear(approval.id)
