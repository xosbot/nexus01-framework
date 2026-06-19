"""Telegram HITL (Human-in-the-Loop) approval flow for NEXUS-01.

Provides inline keyboard approval for destructive operations via Telegram.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_SECONDS = 300  # 5 minutes


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    action: str = ""
    description: str = ""
    command: str = ""
    requester: str = ""
    channel: str = ""
    session_id: str = ""
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = field(default_factory=time.monotonic)
    decided_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > APPROVAL_TIMEOUT_SECONDS

    def approve(self) -> None:
        self.status = ApprovalStatus.APPROVED
        self.decided_at = time.monotonic()

    def deny(self) -> None:
        self.status = ApprovalStatus.DENIED
        self.decided_at = time.monotonic()

    def expire(self) -> None:
        self.status = ApprovalStatus.EXPIRED
        self.decided_at = time.monotonic()


@dataclass
class ApprovalManager:
    _pending: dict[str, ApprovalRequest] = field(default_factory=dict)
    _history: list[ApprovalRequest] = field(default_factory=list)

    def create(self, action: str, description: str, command: str = "",
               requester: str = "", channel: str = "", session_id: str = "",
               metadata: dict | None = None) -> ApprovalRequest:
        req = ApprovalRequest(
            action=action,
            description=description,
            command=command,
            requester=requester,
            channel=channel,
            session_id=session_id,
            metadata=metadata or {},
        )
        self._pending[req.id] = req
        logger.info("Approval created: %s — %s", req.id, action)
        return req

    def get(self, approval_id: str) -> ApprovalRequest | None:
        req = self._pending.get(approval_id)
        if req and req.is_expired:
            req.expire()
            self._archive(req)
            return None
        return req

    def get_for_session(self, channel: str, session_id: str) -> ApprovalRequest | None:
        for req in list(self._pending.values()):
            if req.channel == channel and req.session_id == session_id:
                if req.is_expired:
                    req.expire()
                    self._archive(req)
                    continue
                return req
        return None

    def approve(self, approval_id: str) -> ApprovalRequest | None:
        req = self._pending.pop(approval_id, None)
        if not req:
            return None
        req.approve()
        self._archive(req)
        logger.info("Approval granted: %s", approval_id)
        return req

    def deny(self, approval_id: str) -> ApprovalRequest | None:
        req = self._pending.pop(approval_id, None)
        if not req:
            return None
        req.deny()
        self._archive(req)
        logger.info("Approval denied: %s", approval_id)
        return req

    def cleanup_expired(self) -> int:
        expired = [r for r in self._pending.values() if r.is_expired]
        for req in expired:
            req.expire()
            self._pending.pop(req.id, None)
            self._archive(req)
        if expired:
            logger.info("Expired %d stale approvals", len(expired))
        return len(expired)

    def _archive(self, req: ApprovalRequest) -> None:
        self._history.append(req)
        if len(self._history) > 200:
            self._history = self._history[-100:]

    def pending_count(self) -> int:
        return len(self._pending)

    def recent_history(self, n: int = 10) -> list[ApprovalRequest]:
        return self._history[-n:]
