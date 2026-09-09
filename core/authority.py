"""Deterministic XOS authority requests, capability grants, and evidence ledger.

Hardened v0.1: WAL, FK, busy_timeout, RLock, UTC, single-use atomic, fail-closed,
crash-aware execute_with_grant, and legacy shim for gateway/executor compatibility.
"""

from __future__ import annotations

import inspect
import json
import sqlite3
import threading
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

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


class RequestNotFound(AuthorityError, KeyError):
    pass


class RequestNotPending(AuthorityError, ValueError):
    pass


class GrantNotFound(AuthorityError, KeyError):
    pass


class GrantExpired(AuthorityError, ValueError):
    pass


class GrantConsumed(AuthorityError, ValueError):
    pass


class GrantScopeMismatch(AuthorityError, ValueError):
    pass


class AuthorityBusy(AuthorityError):
    """SQLite transaction could not be acquired — fail closed, do not execute."""

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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "actor": self.actor,
            "principal": self.principal,
            "action": self.action,
            "resource": self.resource,
            "environment": self.environment,
            "risk_class": self.risk_class.value,
            "requested_scope": self.requested_scope,
            "correlation_id": self.correlation_id,
            "status": self.status.value,
            "policy_decision": self.policy_decision.value,
            "policy_reason": self.policy_reason,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            # compat fields for legacy callers
            "actor_id": self.actor,
            "actor_type": "agent",
            "session_id": self.correlation_id,
            "params": self.requested_scope,
            "iso": self.created_at,
        }


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

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "action": self.action,
            "resource": self.resource,
            "issued_by": self.issued_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "single_use": self.single_use,
            "consumed_at": self.consumed_at,
            # compat
            "actor_id": self.issued_by,
            "session_id": "",
            "scope": {"action": self.action, "resource": self.resource},
            "iso_expires": self.expires_at,
            "iso_created": self.created_at,
            "used": self.consumed_at is not None,
            "expired": self.is_expired(),
        }

    def is_expired(self) -> bool:
        try:
            return datetime.now(timezone.utc) >= datetime.fromisoformat(self.expires_at)
        except Exception:
            return True


@dataclass(frozen=True)
class EvidenceEvent:
    event_id: str
    event_type: str
    request_id: str | None
    grant_id: str | None
    actor: str | None
    data: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "request_id": self.request_id,
            "grant_id": self.grant_id,
            "actor": self.actor,
            "data": self.data,
            "created_at": self.created_at,
            "id": self.event_id,
            "iso": self.created_at,
        }


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

    def __init__(self, db_path: str | Path = "data/xos_control.db", grant_ttl_seconds: int = 300, policy=None) -> None:
        # policy param kept for compat with legacy callers (core/app.py)
        self.db_path = str(db_path)
        self.grant_ttl_seconds = grant_ttl_seconds
        self._policy = policy
        self._lock = threading.RLock()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        # durability + concurrency
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            pass
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> AuthorityService:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
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
                CREATE INDEX IF NOT EXISTS idx_authority_request_actor
                    ON authority_requests(actor, status);

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
                CREATE INDEX IF NOT EXISTS idx_capability_grant_expires
                    ON capability_grants(expires_at);

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
                CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(event_type, id);
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
        if not actor or not principal or not action or not resource:
            raise ValueError("actor, principal, action, resource are required")
        policy = AuthorityPolicy.evaluate(mode)
        request_id = self._request_id()
        created_at = self._iso(self._now())
        status = RequestStatus.DENIED if policy.decision is PolicyDecision.DENY else RequestStatus.PENDING
        decided_at = created_at if status is RequestStatus.DENIED else None
        decided_by = "xos.policy" if status is RequestStatus.DENIED else None
        scope = requested_scope or {}

        with self._lock, self._conn:
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
                data={"mode": mode.value, "policy_decision": policy.decision.value, "principal": principal},
            )
            if status is RequestStatus.DENIED:
                self._append_evidence(
                    event_type="request.denied",
                    request_id=request_id,
                    actor="xos.policy",
                    data={"reason": policy.reason},
                )
            # emit to global events for auditability (best effort)
            try:
                from core.events import emit
                emit("authority_requested", f"request {request_id} {action} -> {status.value}", session_id=correlation_id or "", agent=actor, data={"request_id": request_id, "mode": mode.value})
            except Exception:
                pass

        return self.get_request(request_id)

    def approve(
        self,
        request_id: str,
        approved_by: str = "human",
        *args,
        ttl_seconds: int | None = None,
        single_use: bool = True,
        **kwargs,
    ) -> CapabilityGrant:
        # handle legacy positional approved_by
        if args:
            approved_by = args[0] if args[0] else approved_by
        if "approved_by" in kwargs:
            approved_by = kwargs["approved_by"]
        if ttl_seconds is None and "ttl_seconds" in kwargs:
            ttl_seconds = kwargs["ttl_seconds"]
        if ttl_seconds is None:
            ttl_seconds = getattr(self, "grant_ttl_seconds", 300)
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be >= 0")

        with self._lock, self._conn:
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
            try:
                from core.events import emit
                emit("authority_approved", f"approved {request_id} -> grant {grant_id}", session_id=row["correlation_id"] or "", agent=approved_by, data={"request_id": request_id, "grant_id": grant_id})
                emit("grant_issued", f"grant {grant_id} for {row['action']}", session_id=row["correlation_id"] or "", agent=approved_by, data={"grant_id": grant_id})
            except Exception:
                pass

        return self.get_grant(grant_id)

    def deny(self, request_id: str, denied_by: str = "human", reason: str = "", *args, **kwargs) -> AuthorityRequest:
        if args:
            if len(args) >= 1:
                denied_by = args[0]
            if len(args) >= 2:
                reason = args[1]
        if "denied_by" in kwargs:
            denied_by = kwargs["denied_by"]
        if "reason" in kwargs:
            reason = kwargs["reason"]
        with self._lock, self._conn:
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
            try:
                from core.events import emit
                emit("authority_denied", f"denied {request_id}: {reason}", session_id="", agent=denied_by, data={"request_id": request_id})
            except Exception:
                pass

        return self.get_request(request_id)

    def consume_grant(self, grant_id: str, action: str | None = None, resource: str | None = None, actor: str | None = None, principal: str | None = None, **kwargs) -> CapabilityGrant:
        if action is None:
            action = kwargs.get("action")
        if resource is None:
            resource = kwargs.get("resource")
        if actor is None:
            actor = kwargs.get("actor")
        if principal is None:
            principal = kwargs.get("principal")
        if not action or not resource:
            raise ValueError("action and resource are required")
        with self._lock:
            # Use explicit transaction to ensure DB-level atomicity across connections — fail closed if cannot acquire
            try:
                self._conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise AuthorityBusy(f"Transaction busy, fail closed: {exc}") from exc
            except sqlite3.Error as exc:
                raise AuthorityError(f"Transaction failed: {exc}") from exc
            try:
                row = self._conn.execute(
                    """
                    SELECT g.*, r.status AS request_status, r.actor AS req_actor, r.principal AS req_principal
                    FROM capability_grants g
                    JOIN authority_requests r ON r.id = g.request_id
                    WHERE g.id = ?
                    """,
                    (grant_id,),
                ).fetchone()
                if row is None:
                    self._conn.execute("ROLLBACK")
                    raise GrantNotFound(grant_id)
                if RequestStatus(row["request_status"]) is not RequestStatus.APPROVED:
                    self._conn.execute("ROLLBACK")
                    raise AuthorityError(f"Grant {grant_id} is not backed by an approved request")
                if row["action"] != action or row["resource"] != resource:
                    self._conn.execute("ROLLBACK")
                    raise GrantScopeMismatch(
                        f"Grant scope is {row['action']} on {row['resource']}, not {action} on {resource}"
                    )
                if actor is not None and actor != row["req_actor"]:
                    self._conn.execute("ROLLBACK")
                    raise GrantScopeMismatch(f"Grant actor mismatch: {row['req_actor']} vs {actor}")
                if principal is not None and principal != row["req_principal"]:
                    self._conn.execute("ROLLBACK")
                    raise GrantScopeMismatch(f"Grant principal mismatch: {row['req_principal']} vs {principal}")
                if self._now() >= datetime.fromisoformat(row["expires_at"]):
                    self._conn.execute("ROLLBACK")
                    raise GrantExpired(grant_id)
                if bool(row["single_use"]) and row["consumed_at"] is not None:
                    self._conn.execute("ROLLBACK")
                    raise GrantConsumed(grant_id)

                if bool(row["single_use"]):
                    now_iso = self._iso(self._now())
                    # Final atomic UPDATE enforces all predicates; DB determines winner
                    if actor is not None and principal is not None:
                        cur = self._conn.execute(
                            """
                            UPDATE capability_grants SET consumed_at = ?
                            WHERE id = ? AND consumed_at IS NULL
                              AND expires_at > ?
                              AND action = ? AND resource = ?
                              AND (SELECT status FROM authority_requests WHERE id = request_id) = 'APPROVED'
                              AND (SELECT actor FROM authority_requests WHERE id = request_id) = ?
                              AND (SELECT principal FROM authority_requests WHERE id = request_id) = ?
                            """,
                            (now_iso, grant_id, now_iso, action, resource, row["req_actor"], row["req_principal"]),
                        )
                    else:
                        cur = self._conn.execute(
                            """
                            UPDATE capability_grants SET consumed_at = ?
                            WHERE id = ? AND consumed_at IS NULL
                              AND expires_at > ?
                              AND action = ? AND resource = ?
                              AND (SELECT status FROM authority_requests WHERE id = request_id) = 'APPROVED'
                            """,
                            (now_iso, grant_id, now_iso, action, resource),
                        )
                    if cur.rowcount != 1:
                        self._conn.execute("ROLLBACK")
                        check = self._conn.execute("SELECT consumed_at, expires_at FROM capability_grants WHERE id=?", (grant_id,)).fetchone()
                        if check and check["consumed_at"] is not None:
                            raise GrantConsumed(grant_id)
                        if check and self._now() >= datetime.fromisoformat(check["expires_at"]):
                            raise GrantExpired(grant_id)
                        raise GrantScopeMismatch(f"Atomic consume failed for {grant_id}")
                    self._conn.execute("COMMIT")
                    # evidence after commit (still durable)
                    with self._lock, self._conn:
                        self._append_evidence(
                            event_type="grant.consumed",
                            request_id=row["request_id"],
                            grant_id=grant_id,
                            actor=actor or "xos.executor",
                            data={"action": action, "resource": resource, "actor": actor, "principal": principal},
                        )
                    try:
                        from core.events import emit
                        emit("grant_consumed", f"grant {grant_id} consumed for {action}", session_id=row["request_id"], agent=actor or "xos.executor", data={"grant_id": grant_id})
                    except Exception:
                        pass
                else:
                    self._conn.execute("COMMIT")
                    with self._lock, self._conn:
                        self._append_evidence(
                            event_type="grant.consumed",
                            request_id=row["request_id"],
                            grant_id=grant_id,
                            actor=actor or "xos.executor",
                            data={"action": action, "resource": resource, "actor": actor, "principal": principal},
                        )
                    try:
                        from core.events import emit
                        emit("grant_consumed", f"grant {grant_id} consumed for {action}", session_id=row["request_id"], agent=actor or "xos.executor", data={"grant_id": grant_id})
                    except Exception:
                        pass
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        return self.get_grant(grant_id)

    def begin_execution(self, grant_id: str, *, actor: str, principal: str, action: str, resource: str) -> CapabilityGrant:
        """Atomic pre-execution transition: validate + consume + grant.consumed + execution.started in ONE transaction.

        All 11 predicates are enforced by the final UPDATE/COMMIT. Only after COMMIT may the external tool execute.
        If transaction fails, DO NOT EXECUTE.
        """
        if not actor or not principal:
            raise ValueError("actor and principal are required for execution")
        if not action or not resource:
            raise ValueError("action and resource are required")
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                raise AuthorityBusy(f"Transaction busy, fail closed: {exc}") from exc
            except sqlite3.Error as exc:
                raise AuthorityError(f"Transaction failed: {exc}") from exc
            try:
                row = self._conn.execute(
                    """
                    SELECT g.*, r.status AS request_status, r.actor AS req_actor, r.principal AS req_principal, r.correlation_id AS corr
                    FROM capability_grants g JOIN authority_requests r ON r.id=g.request_id WHERE g.id=?
                    """,
                    (grant_id,),
                ).fetchone()
                if row is None:
                    self._conn.execute("ROLLBACK")
                    raise GrantNotFound(grant_id)
                if RequestStatus(row["request_status"]) is not RequestStatus.APPROVED:
                    self._conn.execute("ROLLBACK")
                    raise AuthorityError(f"Grant {grant_id} not backed by APPROVED request")
                if row["action"] != action or row["resource"] != resource:
                    self._conn.execute("ROLLBACK")
                    raise GrantScopeMismatch(f"Grant scope is {row['action']} on {row['resource']}, not {action} on {resource}")
                if row["req_actor"] != actor:
                    self._conn.execute("ROLLBACK")
                    raise GrantScopeMismatch(f"Grant actor mismatch: {row['req_actor']} vs {actor}")
                if row["req_principal"] != principal:
                    self._conn.execute("ROLLBACK")
                    raise GrantScopeMismatch(f"Grant principal mismatch: {row['req_principal']} vs {principal}")
                if self._now() >= datetime.fromisoformat(row["expires_at"]):
                    self._conn.execute("ROLLBACK")
                    raise GrantExpired(grant_id)
                if bool(row["single_use"]) and row["consumed_at"] is not None:
                    self._conn.execute("ROLLBACK")
                    raise GrantConsumed(grant_id)
                now_iso = self._iso(self._now())
                # Atomic UPDATE enforcing all predicates
                cur = self._conn.execute(
                    """
                    UPDATE capability_grants SET consumed_at=?
                    WHERE id=? AND consumed_at IS NULL
                      AND expires_at>?
                      AND action=? AND resource=?
                      AND (SELECT status FROM authority_requests WHERE id=request_id)='APPROVED'
                      AND (SELECT actor FROM authority_requests WHERE id=request_id)=?
                      AND (SELECT principal FROM authority_requests WHERE id=request_id)=?
                    """,
                    (now_iso, grant_id, now_iso, action, resource, actor, principal),
                )
                if cur.rowcount != 1:
                    self._conn.execute("ROLLBACK")
                    check = self._conn.execute("SELECT consumed_at FROM capability_grants WHERE id=?", (grant_id,)).fetchone()
                    if check and check["consumed_at"] is not None:
                        raise GrantConsumed(grant_id)
                    raise GrantScopeMismatch(f"Atomic begin_execution failed for {grant_id}")
                # Append grant.consumed and execution.started in SAME transaction
                self._conn.execute(
                    """
                    INSERT INTO evidence (event_id, event_type, request_id, grant_id, actor, data, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (self._event_id(), "grant.consumed", row["request_id"], grant_id, actor, json.dumps({"action": action, "resource": resource, "actor": actor, "principal": principal}, sort_keys=True), now_iso),
                )
                self._conn.execute(
                    """
                    INSERT INTO evidence (event_id, event_type, request_id, grant_id, actor, data, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (self._event_id(), "execution.started", row["request_id"], grant_id, actor, json.dumps({"action": action, "resource": resource}, sort_keys=True), now_iso),
                )
                self._conn.execute("COMMIT")
                try:
                    from core.events import emit
                    emit("grant_consumed", f"grant {grant_id} consumed", session_id=row["request_id"], agent=actor, data={"grant_id": grant_id})
                    emit("execution_started", f"execution {grant_id} started", session_id=row["request_id"], agent=actor, data={"action": action})
                except Exception:
                    pass
            except Exception:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
        return self.get_grant(grant_id)

    async def execute_with_grant(
        self,
        grant_id: str,
        *,
        action: str,
        resource: str,
        executor: Callable[..., T | Awaitable[T]],
        actor: str = "xos.executor",
        principal: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> T:
        # Resolve principal if not provided: derive from grant's backing request (trust source is DB, not payload)
        if principal is None:
            try:
                g = self.get_grant(grant_id)
                req = self.get_request(g.request_id)
                principal = req.principal
            except Exception:
                principal = "navigator"
        # Use canonical atomic begin_execution (consume+grant.consumed+execution.started in one txn)
        try:
            grant = self.begin_execution(grant_id, actor=actor, principal=principal, action=action, resource=resource)
        except Exception:
            raise
        try:
            result = executor(*args, **(kwargs or {}))
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            try:
                self.record_execution_failed(grant, actor=actor, error=exc)
            except Exception as ev_exc:
                # evidence failure after exec — surface but don't hide original error
                raise AuthorityError(f"execution failed but evidence persistence also failed: {ev_exc}") from exc
            raise
        try:
            self.record_execution_succeeded(grant, actor=actor)
        except Exception as exc:
            raise AuthorityError(f"execution succeeded but evidence persistence failed (reconciliation required) for {grant_id}: {exc}") from exc
        return result

    def record_execution_started(self, grant: CapabilityGrant, *, actor: str) -> None:
        with self._lock, self._conn:
            self._append_evidence(
                event_type="execution.started",
                request_id=grant.request_id,
                grant_id=grant.id,
                actor=actor,
                data={"action": grant.action, "resource": grant.resource},
            )

    def record_execution_succeeded(self, grant: CapabilityGrant, *, actor: str) -> None:
        with self._lock, self._conn:
            self._append_evidence(
                event_type="execution.succeeded",
                request_id=grant.request_id,
                grant_id=grant.id,
                actor=actor,
                data={},
            )

    def record_execution_failed(self, grant: CapabilityGrant, *, actor: str, error: Exception) -> None:
        with self._lock, self._conn:
            self._append_evidence(
                event_type="execution.failed",
                request_id=grant.request_id,
                grant_id=grant.id,
                actor=actor,
                data={"error_type": type(error).__name__, "error": str(error)[:1000]},
            )

    def get_request(self, request_id: str) -> AuthorityRequest:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM authority_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise RequestNotFound(request_id)
            return self._request_from_row(row)

    def get_grant(self, grant_id: str) -> CapabilityGrant:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM capability_grants WHERE id = ?",
                (grant_id,),
            ).fetchone()
            if row is None:
                raise GrantNotFound(grant_id)
            return self._grant_from_row(row)

    def list_evidence(self, *, request_id: str | None = None) -> list[EvidenceEvent]:
        with self._lock:
            if request_id is None:
                rows = self._conn.execute("SELECT * FROM evidence ORDER BY id ASC").fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM evidence WHERE request_id = ? ORDER BY id ASC",
                    (request_id,),
                ).fetchall()
            return [self._evidence_from_row(row) for row in rows]

    def trace(self, correlation_id: str) -> list[EvidenceEvent]:
        """Ordered lifecycle for a correlation_id (via request JOIN)."""
        with self._lock:
            req_rows = self._conn.execute(
                "SELECT id FROM authority_requests WHERE correlation_id = ?", (correlation_id,)
            ).fetchall()
            if not req_rows:
                return []
            req_ids = [r["id"] for r in req_rows]
            placeholders = ",".join("?" for _ in req_ids)
            rows = self._conn.execute(
                f"SELECT * FROM evidence WHERE request_id IN ({placeholders}) ORDER BY id ASC", req_ids
            ).fetchall()
            return [self._evidence_from_row(r) for r in rows]

    def list_incomplete_executions(self) -> list[dict]:
        """Find execution.started without succeeded/failed OR grant consumed without started (legacy)."""
        with self._lock:
            incomplete: dict[str, dict] = {}
            # A: execution.started without terminal
            started = self._conn.execute(
                "SELECT grant_id, request_id FROM evidence WHERE event_type='execution.started'"
            ).fetchall()
            for row in started:
                gid = row["grant_id"]
                exists = self._conn.execute(
                    "SELECT 1 FROM evidence WHERE grant_id=? AND event_type IN ('execution.succeeded','execution.failed')",
                    (gid,),
                ).fetchone()
                if not exists:
                    incomplete[gid] = {"grant_id": gid, "request_id": row["request_id"], "status": "RECONCILIATION_REQUIRED", "reason": "started without terminal"}
            # B: legacy grant consumed without execution.started
            consumed = self._conn.execute(
                "SELECT grant_id, request_id FROM evidence WHERE event_type='grant.consumed'"
            ).fetchall()
            for row in consumed:
                gid = row["grant_id"]
                if gid in incomplete:
                    continue
                exists = self._conn.execute(
                    "SELECT 1 FROM evidence WHERE grant_id=? AND event_type='execution.started'",
                    (gid,),
                ).fetchone()
                if not exists:
                    incomplete[gid] = {"grant_id": gid, "request_id": row["request_id"], "status": "RECONCILIATION_REQUIRED", "reason": "consumed without started"}
            return list(incomplete.values())

    # -- additional helpers for stats/audit --

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS n FROM authority_requests").fetchone()["n"]
            pending = self._conn.execute("SELECT COUNT(*) AS n FROM authority_requests WHERE status='PENDING'").fetchone()["n"]
            grants = self._conn.execute("SELECT COUNT(*) AS n FROM capability_grants").fetchone()["n"]
            ev = self._conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
            by_status = {r["status"]: r["n"] for r in self._conn.execute("SELECT status, COUNT(*) AS n FROM authority_requests GROUP BY status").fetchall()}
            return {"total_requests": total, "pending": pending, "total_grants": grants, "total_evidence": ev, "by_status": by_status}

    def list_requests(self, status: str | None = None, limit: int = 50) -> list[dict]:
        with self._lock:
            if status:
                # accept both upper and lower case
                rows = self._conn.execute("SELECT * FROM authority_requests WHERE status=? ORDER BY id DESC LIMIT ?", (status.upper(), limit)).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM authority_requests ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [self._request_from_row(r).to_dict() for r in rows]

    def list_pending(self, limit: int = 50) -> list[dict]:
        return self.list_requests(status="PENDING", limit=limit)

    def clear_all(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM evidence")
            self._conn.execute("DELETE FROM capability_grants")
            self._conn.execute("DELETE FROM authority_requests")

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
        # also emit to events for global audit
        try:
            from core.events import emit
            emit(event_type, f"{event_type} {request_id or grant_id or ''}", session_id=request_id or "", agent=actor or "", data=data or {})
        except Exception:
            pass

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

    # ------------------------------------------------------------------
    # Legacy shim — maps old v0 API (request/verify_grant/etc) to hardened API
    # ------------------------------------------------------------------

    def request(self, *, actor_type: str = "agent", actor_id: str = "", session_id: str = "", action: str = "", resource: str = "", params: dict | None = None, reason: str = "", correlation_id: str = "", principal: str | None = None, environment: str = "local", risk_class: Any = None, **kwargs) -> dict:
        """Legacy request() shim: actor_id+action+resource+params -> create_request."""
        actor = actor_id or kwargs.get("actor") or "unknown"
        princ = principal or kwargs.get("principal") or actor_id or "navigator"
        # legacy Policy handling: if service was constructed with a legacy Policy, respect it
        if getattr(self, "_policy", None) is not None and hasattr(self._policy, "evaluate"):
            # legacy Policy.evaluate(action, resource, actor_id)
            try:
                legacy_decision = self._policy.evaluate(action, resource, actor)
                # map legacy decision to hardened behavior
                if legacy_decision.deny:
                    # create a DENIED request via OBSERVE mode then override reason
                    mode = ControlMode.OBSERVE
                elif legacy_decision.allow and not legacy_decision.require_approval:
                    # auto-allow: create then immediately approve with short TTL
                    # we emulate by creating CONFIRM then auto-approving
                    # but for shim, we return approved directly
                    req = self.create_request(
                        actor=actor,
                        principal=princ,
                        action=action,
                        resource=resource or "default",
                        environment=environment,
                        risk_class=RiskClass.MEDIUM,
                        requested_scope=params or {},
                        correlation_id=correlation_id or session_id or None,
                        mode=ControlMode.CONFIRM,
                    )
                    # auto-approve via policy: mimic legacy allow
                    try:
                        grant = self.approve(req.id, approved_by="policy:auto-allow", ttl_seconds=getattr(self, "grant_ttl_seconds", 300))
                        req_approved = self.get_request(req.id)
                        return {"request": req_approved.to_dict(), "policy": {"allow": True, "require_approval": False, "deny": False, "reason": legacy_decision.reason, "risk": legacy_decision.risk}, "grant": grant.to_dict()}
                    except Exception:
                        return {"request": req.to_dict(), "policy": {"allow": True, "require_approval": False, "deny": False, "reason": legacy_decision.reason, "risk": legacy_decision.risk}, "grant": None}
                else:
                    mode = ControlMode.CONFIRM
                    rc = RiskClass.MEDIUM
                    if isinstance(risk_class, RiskClass):
                        rc = risk_class
                    elif isinstance(risk_class, str):
                        try:
                            rc = RiskClass(risk_class.upper())
                        except Exception:
                            rc = RiskClass.MEDIUM
                    req = self.create_request(
                        actor=actor,
                        principal=princ,
                        action=action,
                        resource=resource or "default",
                        environment=environment,
                        risk_class=rc,
                        requested_scope=params or {},
                        correlation_id=correlation_id or session_id or None,
                        mode=mode,
                    )
                    return {"request": req.to_dict(), "policy": {"allow": False, "require_approval": True, "deny": False, "reason": legacy_decision.reason, "risk": legacy_decision.risk}, "grant": None}
            except Exception:
                pass
        # default hardened path: CONFIRM requires human
        mode = ControlMode.CONFIRM
        if not action:
            raise ValueError("actor_id and action are required")
        rc = RiskClass.MEDIUM
        if isinstance(risk_class, RiskClass):
            rc = risk_class
        elif isinstance(risk_class, str):
            try:
                rc = RiskClass(risk_class.upper())
            except Exception:
                rc = RiskClass.MEDIUM
        req = self.create_request(
            actor=actor,
            principal=princ,
            action=action,
            resource=resource or "default",
            environment=environment,
            risk_class=rc,
            requested_scope=params or {},
            correlation_id=correlation_id or session_id or None,
            mode=mode,
        )
        return {"request": req.to_dict(), "policy": {"allow": req.status != RequestStatus.DENIED, "require_approval": req.policy_decision == PolicyDecision.REQUIRE_HUMAN, "deny": req.status == RequestStatus.DENIED, "reason": req.policy_reason, "risk": req.risk_class.value.lower()}, "grant": None}

    def get_request_dict(self, request_id: str) -> dict | None:
        try:
            return self.get_request(request_id).to_dict()
        except RequestNotFound:
            return None

    def verify_grant(self, grant_id: str, action: str, resource: str, actor: str | None = None, principal: str | None = None) -> tuple[bool, str]:
        try:
            with self._lock:
                row = self._conn.execute("SELECT g.*, r.status AS rs, r.actor AS req_actor, r.principal AS req_principal FROM capability_grants g JOIN authority_requests r ON r.id=g.request_id WHERE g.id=?", (grant_id,)).fetchone()
                if row is None:
                    return False, "grant not found"
                if row["action"] != action or row["resource"] != resource:
                    return False, f"resource scope mismatch: grant={row['resource']} vs request={resource}" if row["resource"] != resource else f"action scope mismatch: grant={row['action']} vs request={action}"
                if actor is not None and actor != row["req_actor"]:
                    return False, f"actor mismatch: {row['req_actor']} vs {actor}"
                if principal is not None and principal != row["req_principal"]:
                    return False, f"principal mismatch: {row['req_principal']} vs {principal}"
                if datetime.now(timezone.utc) >= datetime.fromisoformat(row["expires_at"]):
                    return False, "grant expired"
                if bool(row["single_use"]) and row["consumed_at"] is not None:
                    return False, "grant already used"
                if row["rs"] != RequestStatus.APPROVED.value:
                    return False, "grant not backed by approved request"
            return True, "ok"
        except Exception as e:
            return False, str(e)

    def consume_grant_legacy(self, grant_id: str, action: str, resource: str) -> tuple[bool, str]:
        try:
            self.consume_grant(grant_id, action=action, resource=resource)
            return True, "ok"
        except (GrantNotFound, GrantExpired, GrantConsumed, GrantScopeMismatch, AuthorityError) as e:
            return False, str(e)

    def record_evidence(self, *, request_id: str = "", grant_id: str = "", actor_id: str = "", action: str = "", resource: str = "", input_data: dict | None = None, outcome: str = "", success: bool = True, duration_ms: int = 0, **kwargs) -> dict:
        # map legacy record_evidence to evidence ledger
        data = {"action": action, "resource": resource, "input": input_data or {}, "outcome": outcome, "success": success, "duration_ms": duration_ms}
        with self._lock, self._conn:
            self._append_evidence(event_type="execution.succeeded" if success else "execution.failed", request_id=request_id or None, grant_id=grant_id or None, actor=actor_id or None, data=data)
        return {"id": str(uuid.uuid4().hex[:16]), "request_id": request_id, "grant_id": grant_id, "actor_id": actor_id, "action": action, "resource": resource, "outcome": outcome, "success": success}

    def list_evidence_legacy(self, request_id: str | None = None, grant_id: str | None = None, limit: int = 50) -> list[dict]:
        evs = self.list_evidence(request_id=request_id)
        if grant_id:
            evs = [e for e in evs if e.grant_id == grant_id]
        return [e.to_dict() for e in evs[:limit]]

    def get_grant_dict(self, grant_id: str) -> dict | None:
        try:
            return self.get_grant(grant_id).to_dict()
        except GrantNotFound:
            return None

