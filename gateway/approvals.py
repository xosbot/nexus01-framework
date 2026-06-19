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

    @property
    def key(self) -> str:
        return f"{self.channel}:{self.session_id}"


class ApprovalManager:
    TTL = timedelta(minutes=10)

    def __init__(self) -> None:
        self._pending: dict[str, PendingApproval] = {}
        self._by_key: dict[str, str] = {}

    def create(self, channel: str, session_id: str, text: str, payload: dict | None = None) -> PendingApproval:
        self.clear_session(channel, session_id)
        approval = PendingApproval(
            id=uuid.uuid4().hex[:12],
            channel=channel,
            session_id=session_id,
            text=text,
            payload=payload or {},
        )
        self._pending[approval.id] = approval
        self._by_key[approval.key] = approval.id
        return approval

    def get_for_session(self, channel: str, session_id: str) -> PendingApproval | None:
        approval_id = self._by_key.get(f"{channel}:{session_id}")
        if not approval_id:
            return None
        approval = self._pending.get(approval_id)
        if approval and datetime.now() - approval.created_at > self.TTL:
            self.clear(approval_id)
            return None
        return approval

    def get(self, approval_id: str) -> PendingApproval | None:
        approval = self._pending.get(approval_id)
        if approval and datetime.now() - approval.created_at > self.TTL:
            self.clear(approval_id)
            return None
        return approval

    def clear(self, approval_id: str) -> None:
        approval = self._pending.pop(approval_id, None)
        if approval:
            self._by_key.pop(approval.key, None)

    def clear_session(self, channel: str, session_id: str) -> None:
        approval = self.get_for_session(channel, session_id)
        if approval:
            self.clear(approval.id)
