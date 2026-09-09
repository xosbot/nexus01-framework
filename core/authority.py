"""Deterministic XOS authority requests, capability grants, and evidence ledger."""

from __future__ import annotations

import inspect
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class ControlMode(str, Enum):
    OBSERVE = "OBSERVE"
    PROPOSE = "PROPOSE"
    CONFIRM = "CONFIRM"
    DELEGATED = "DELEGATED"
    AUTONOMOUS_DOMAIN = "AUTONOMOUS_DOMAIN"


class PolicyDecision(str, Enum):
    DENY = "DENY"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"


class RequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RiskClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AuthorityError(RuntimeError):
    """Base class for deterministic authority failures."""


class RequestNotFound(AuthorityError):
    pass


class RequestNotPending(AuthorityError):
    pass


class GrantNotFound(AuthorityError):
    pass


class GrantExpired(AuthorityError):
    pass


class GrantConsumed(AuthorityError):
    pass


class GrantScopeMismatch(AuthorityError):
    pass


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason: str


@dataclass(frozen=True)
class AuthorityRequest:
    id: str
    actor: str
    principal: str
    action: str
    resource: str
    environment: str
    risk_class: RiskClass
    requested_scope: dict[str, Any]
    correlation_id: str
    status: RequestStatus
    policy_decision: PolicyDecision
    policy_reason: str
    created_at: str
    decided_at: str | None = None
    decided_by: str | None = None


@dataclass(frozen=True)
class CapabilityGrant:
    id: str
    request_id: str
    action: str
    resource: str
    issued_by: str
    created_at: str
    expires_at: str
    single_use: bool
    consumed_at: str | None = None


@dataclass(frozen=True)
class EvidenceEvent:
    event_id: str
    event_type: str
    request_id: str | None
    grant_id: str | None
    actor: str | None
    data: dict[str, Any]
    created_at: str


class AuthorityPolicy:
    """Fail-closed v0 policy. Delegation modes intentionally require confirmation."""

    @staticmethod
    def evaluate(mode: ControlMode) -> PolicyResult:
        if mode is ControlMode.OBSERVE:
            return PolicyResult(PolicyDecision.DENY, "OBSERVE mode forbids consequential execution")
        if mode is ControlMode.PROPOSE:
            return PolicyResult(PolicyDecision.DENY, "PROPOSE mode permits proposals but not execution")
        if mode is ControlMode.CONFIRM:
            return PolicyResult(PolicyDecision.REQUIRE_HUMAN, "CONFIRM mode requires explicit human approval")
        return PolicyResult(
            PolicyDecision.REQUIRE_HUMAN,
            f"{mode.value} has no delegation policy in v0; falling back to confirmation",
        )


class AuthorityService:
    """SQLite-backed authority boundary with append-first execution evidence."""

    def __init__(self, db_path: str | Path = "data/xos_control.db") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> AuthorityService:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS authority_requests (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    risk_class TEXT NOT NULL,
                    requested_scope TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    policy_decision TEXT NOT NULL,
                    policy_reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_authority_request_status
                    ON authority_requests(status);
                CREATE INDEX IF NOT EXISTS idx_authority_request_correlation
                    ON authority_requests(correlation_id);

                CREATE TABLE IF NOT EXISTS capability_grants (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    issued_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    single_use INTEGER NOT NULL,
                    consumed_at TEXT,
                    FOREIGN KEY(request_id) REFERENCES authority_requests(id)
                );

                CREATE INDEX IF NOT EXISTS idx_capability_grant_request
                    ON capability_grants(request_id);

                CREATE TABLE IF NOT EXISTS evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    request_id TEXT,
                    grant_id TEXT,
                    actor TEXT,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(request_id) REFERENCES authority_requests(id),
                    FOREIGN KEY(grant_id) REFERENCES capability_grants(id)
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_request ON evidence(request_id, id);
                CREATE INDEX IF NOT EXISTS idx_evidence_grant ON evidence(grant_id, id);
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.isoformat(timespec="microseconds")

    @staticmethod
    def _request_id() -> str:
        return f"req_{uuid.uuid4().hex}"

    @staticmethod
    def _grant_id() -> str:
        return f"grant_{uuid.uuid4().hex}"

    @staticmethod
    def _event_id() -> str:
        return f"evt_{uuid.uuid4().hex}"

    def create_request(
        self,
        *,
        actor: str,
        principal: str,
        action: str,
        resource: str,
        environment: str = "local",
        risk_class: RiskClass = RiskClass.MEDIUM,
        requested_scope: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        mode: ControlMode = ControlMode.CONFIRM,
    ) -> AuthorityRequest:
        policy = AuthorityPolicy.evaluate(mode)
        request_id = self._request_id()
        created_at = self._iso(self._now())
        status = RequestStatus.DENIED if policy.decision is PolicyDecision.DENY else RequestStatus.PENDING
        decided_at = created_at if status is RequestStatus.DENIED else None
        decided_by = "xos.policy" if status is RequestStatus.DENIED else None
        scope = requested_scope or {}

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO authority_requests (
                    id, actor, principal, action, resource, environment, risk_class,
                    requested_scope, correlation_id, status, policy_decision,
                    policy_reason, created_at, decided_at, decided_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    actor,
                    principal,
                    action,
                    resource,
                    environment,
                    risk_class.value,
                    json.dumps(scope, sort_keys=True),
                    correlation_id or uuid.uuid4().hex,
                    status.value,
                    policy.decision.value,
                    policy.reason,
                    created_at,
                    decided_at,
                    decided_by,
                ),
            )
            self._append_evidence(
                event_type="request.created",
                request_id=request_id,
                actor=actor,
                data={"mode": mode.value, "policy_decision": policy.decision.value},
            )
            if status is RequestStatus.DENIED:
                self._append_evidence(
                    event_type="request.denied",
                    request_id=request_id,
                    actor="xos.policy",
                    data={"reason": policy.reason},
                )

        return self.get_request(request_id)

    def approve(
        self,
        request_id: str,
        *,
        approved_by: str,
        ttl_seconds: int = 300,
        single_use: bool = True,
    ) -> CapabilityGrant:
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be >= 0")

        with self._conn:
            row = self._conn.execute(
                "SELECT * FROM authority_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RequestNotFound(request_id)
            if RequestStatus(row["status"]) is not RequestStatus.PENDING:
                raise RequestNotPending(f"Request {request_id} is {row['status']}")
            if PolicyDecision(row["policy_decision"]) is not PolicyDecision.REQUIRE_HUMAN:
                raise AuthorityError(f"Request {request_id} is not human-approvable")

            created = self._now()
            grant_id = self._grant_id()
            self._conn.execute(
                """
                UPDATE authority_requests
                SET status = ?, decided_at = ?, decided_by = ?
                WHERE id = ?
                """,
                (RequestStatus.APPROVED.value, self._iso(created), approved_by, request_id),
            )
            self._conn.execute(
                """
                INSERT INTO capability_grants (
                    id, request_id, action, resource, issued_by, created_at,
                    expires_at, single_use, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    grant_id,
                    request_id,
                    row["action"],
                    row["resource"],
                    approved_by,
                    self._iso(created),
                    self._iso(created + timedelta(seconds=ttl_seconds)),
                    int(single_use),
                ),
            )
            self._append_evidence(
                event_type="request.approved",
                request_id=request_id,
                actor=approved_by,
                data={"ttl_seconds": ttl_seconds, "single_use": single_use},
            )
            self._append_evidence(
                event_type="grant.issued",
                request_id=request_id,
                grant_id=grant_id,
                actor=approved_by,
                data={"action": row["action"], "resource": row["resource"]},
            )

        return self.get_grant(grant_id)

    def deny(self, request_id: str, *, denied_by: str, reason: str) -> AuthorityRequest:
        with self._conn:
            row = self._conn.execute(
                "SELECT status FROM authority_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RequestNotFound(request_id)
            if RequestStatus(row["status"]) is not RequestStatus.PENDING:
                raise RequestNotPending(f"Request {request_id} is {row['status']}")

            self._conn.execute(
                """
                UPDATE authority_requests
                SET status = ?, decided_at = ?, decided_by = ?
                WHERE id = ?
                """,
                (RequestStatus.DENIED.value, self._iso(self._now()), denied_by, request_id),
            )
            self._append_evidence(
                event_type="request.denied",
                request_id=request_id,
                actor=denied_by,
                data={"reason": reason},
            )

        return self.get_request(request_id)

    def consume_grant(self, grant_id: str, *, action: str, resource: str) -> CapabilityGrant:
        with self._conn:
            row = self._conn.execute(
                """
                SELECT g.*, r.status AS request_status
                FROM capability_grants g
                JOIN authority_requests r ON r.id = g.request_id
                WHERE g.id = ?
                """,
                (grant_id,),
            ).fetchone()
            if row is None:
                raise GrantNotFound(grant_id)
            if RequestStatus(row["request_status"]) is not RequestStatus.APPROVED:
                raise AuthorityError(f"Grant {grant_id} is not backed by an approved request")
            if row["action"] != action or row["resource"] != resource:
                raise GrantScopeMismatch(
                    f"Grant scope is {row['action']} on {row['resource']}, not {action} on {resource}"
                )
            if self._now() >= datetime.fromisoformat(row["expires_at"]):
                raise GrantExpired(grant_id)
            if bool(row["single_use"]) and row["consumed_at"] is not None:
                raise GrantConsumed(grant_id)

            consumed_at = row["consumed_at"]
            if bool(row["single_use"]):
                consumed_at = self._iso(self._now())
                self._conn.execute(
                    "UPDATE capability_grants SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
                    (consumed_at, grant_id),
                )
                if self._conn.execute("SELECT changes()").fetchone()[0] != 1:
                    raise GrantConsumed(grant_id)

            self._append_evidence(
                event_type="grant.consumed",
                request_id=row["request_id"],
                grant_id=grant_id,
                actor="xos.executor",
                data={"action": action, "resource": resource},
            )

        return self.get_grant(grant_id)

    async def execute_with_grant(
        self,
        grant_id: str,
        *,
        action: str,
        resource: str,
        executor: Callable[..., T | Awaitable[T]],
        actor: str = "xos.executor",
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> T:
        grant = self.consume_grant(grant_id, action=action, resource=resource)
        self.record_execution_started(grant, actor=actor)
        try:
            result = executor(*args, **(kwargs or {}))
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            self.record_execution_failed(grant, actor=actor, error=exc)
            raise
        self.record_execution_succeeded(grant, actor=actor)
        return result

    def record_execution_started(self, grant: CapabilityGrant, *, actor: str) -> None:
        with self._conn:
            self._append_evidence(
                event_type="execution.started",
                request_id=grant.request_id,
                grant_id=grant.id,
                actor=actor,
                data={"action": grant.action, "resource": grant.resource},
            )

    def record_execution_succeeded(self, grant: CapabilityGrant, *, actor: str) -> None:
        with self._conn:
            self._append_evidence(
                event_type="execution.succeeded",
                request_id=grant.request_id,
                grant_id=grant.id,
                actor=actor,
                data={},
            )

    def record_execution_failed(self, grant: CapabilityGrant, *, actor: str, error: Exception) -> None:
        with self._conn:
            self._append_evidence(
                event_type="execution.failed",
                request_id=grant.request_id,
                grant_id=grant.id,
                actor=actor,
                data={"error_type": type(error).__name__, "error": str(error)[:1000]},
            )

    def get_request(self, request_id: str) -> AuthorityRequest:
        row = self._conn.execute(
            "SELECT * FROM authority_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise RequestNotFound(request_id)
        return self._request_from_row(row)

    def get_grant(self, grant_id: str) -> CapabilityGrant:
        row = self._conn.execute(
            "SELECT * FROM capability_grants WHERE id = ?",
            (grant_id,),
        ).fetchone()
        if row is None:
            raise GrantNotFound(grant_id)
        return self._grant_from_row(row)

    def list_evidence(self, *, request_id: str | None = None) -> list[EvidenceEvent]:
        if request_id is None:
            rows = self._conn.execute("SELECT * FROM evidence ORDER BY id ASC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM evidence WHERE request_id = ? ORDER BY id ASC",
                (request_id,),
            ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def _append_evidence(
        self,
        *,
        event_type: str,
        request_id: str | None = None,
        grant_id: str | None = None,
        actor: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO evidence (
                event_id, event_type, request_id, grant_id, actor, data, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._event_id(),
                event_type,
                request_id,
                grant_id,
                actor,
                json.dumps(data or {}, sort_keys=True, default=str),
                self._iso(self._now()),
            ),
        )

    @staticmethod
    def _request_from_row(row: sqlite3.Row) -> AuthorityRequest:
        return AuthorityRequest(
            id=row["id"],
            actor=row["actor"],
            principal=row["principal"],
            action=row["action"],
            resource=row["resource"],
            environment=row["environment"],
            risk_class=RiskClass(row["risk_class"]),
            requested_scope=json.loads(row["requested_scope"]),
            correlation_id=row["correlation_id"],
            status=RequestStatus(row["status"]),
            policy_decision=PolicyDecision(row["policy_decision"]),
            policy_reason=row["policy_reason"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
        )

    @staticmethod
    def _grant_from_row(row: sqlite3.Row) -> CapabilityGrant:
        return CapabilityGrant(
            id=row["id"],
            request_id=row["request_id"],
            action=row["action"],
            resource=row["resource"],
            issued_by=row["issued_by"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            single_use=bool(row["single_use"]),
            consumed_at=row["consumed_at"],
        )

    @staticmethod
    def _evidence_from_row(row: sqlite3.Row) -> EvidenceEvent:
        return EvidenceEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            request_id=row["request_id"],
            grant_id=row["grant_id"],
            actor=row["actor"],
            data=json.loads(row["data"]),
            created_at=row["created_at"],
        )
