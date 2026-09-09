"""XOS Control Runtime — authority, grants, evidence.

Implements the chain:
  AGENT/HUMAN → AUTHORITY REQUEST → POLICY → HUMAN AUTHORITY → SCOPED GRANT → EXECUTION BOUNDARY → EVIDENCE

SQLite-backed, thread-safe, durable, auditable.
Preferred DB is data/authority.db (WAL). Standard library + sqlite3 only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.policy import Policy, PolicyDecision

_DEFAULT_DB = Path(__file__).parent.parent / "data" / "authority.db"

_lock = threading.RLock()


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------

@dataclass
class AuthorityRequest:
    id: str
    ts: float
    actor_type: str  # human | agent
    actor_id: str
    session_id: str
    action: str
    resource: str
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    status: str = "pending"  # pending | approved | denied | expired
    correlation_id: str = ""
    policy_decision: str = ""
    policy_reason: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.ts))
        return d


@dataclass
class Grant:
    id: str
    request_id: str
    actor_id: str
    session_id: str
    action: str
    resource: str
    scope: dict[str, Any] = field(default_factory=dict)
    expires_at: float = 0.0
    single_use: bool = True
    used: bool = False
    created_at: float = 0.0
    created_by: str = ""
    revoked_at: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["iso_expires"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.expires_at)) if self.expires_at else None
        d["iso_created"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.created_at))
        d["expired"] = self.is_expired()
        return d

    def is_expired(self, now: float | None = None) -> bool:
        if now is None:
            now = time.time()
        return self.expires_at > 0 and now > self.expires_at


@dataclass
class Evidence:
    id: str
    request_id: str
    grant_id: str
    actor_id: str
    action: str
    resource: str
    input_data: dict[str, Any] = field(default_factory=dict)
    outcome: str = ""
    success: bool = True
    ts: float = 0.0
    duration_ms: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.ts))
        return d


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class AuthorityService:
    """Durable authority service.

    Thread-safe via _lock. Each method opens its own sqlite connection.
    Scoped grants are single-use by default and expire.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        grant_ttl_seconds: int = 600,
        policy: Policy | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.grant_ttl_seconds = grant_ttl_seconds
        self.policy = policy or Policy()
        # ensure parent exists and schema created
        self._ensure_schema()

    # -- low-level db helpers ------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(self.db_path), timeout=5.0)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        return c

    def _ensure_tables(self, c: sqlite3.Connection) -> None:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS authority_requests (
                id TEXT PRIMARY KEY,
                ts REAL NOT NULL,
                actor_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                params_json TEXT NOT NULL DEFAULT '{}',
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                correlation_id TEXT NOT NULL DEFAULT '',
                policy_decision TEXT NOT NULL DEFAULT '',
                policy_reason TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS grants (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                scope_json TEXT NOT NULL DEFAULT '{}',
                expires_at REAL NOT NULL,
                single_use INTEGER NOT NULL DEFAULT 1,
                used INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                created_by TEXT NOT NULL DEFAULT '',
                revoked_at REAL,
                FOREIGN KEY(request_id) REFERENCES authority_requests(id)
            );
            CREATE TABLE IF NOT EXISTS evidence (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                grant_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                input_json TEXT NOT NULL DEFAULT '{}',
                outcome TEXT NOT NULL DEFAULT '',
                success INTEGER NOT NULL DEFAULT 1,
                ts REAL NOT NULL,
                duration_ms INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_requests_status ON authority_requests(status, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_requests_session ON authority_requests(session_id, ts DESC);
            CREATE INDEX IF NOT EXISTS idx_grants_request ON grants(request_id);
            CREATE INDEX IF NOT EXISTS idx_grants_expires ON grants(expires_at);
            CREATE INDEX IF NOT EXISTS idx_evidence_request ON evidence(request_id, ts DESC);
        """)

    def _ensure_schema(self) -> None:
        with _lock:
            c = self._conn()
            try:
                self._ensure_tables(c)
                c.commit()
            finally:
                c.close()

    # -- request lifecycle ---------------------------------------------------

    def request(
        self,
        *,
        actor_type: str = "agent",
        actor_id: str,
        session_id: str = "",
        action: str,
        resource: str = "",
        params: dict | None = None,
        reason: str = "",
        correlation_id: str = "",
    ) -> dict:
        """Register an intent. Returns dict with request + policy decision.

        If policy says allow → request is auto-approved and a grant is issued.
        If policy says require_approval → request stays pending.
        If policy says deny → request is denied immediately.
        """
        if not actor_id or not action:
            raise ValueError("actor_id and action are required")

        decision: PolicyDecision = self.policy.evaluate(action, resource, actor_id)
        now = time.time()
        req_id = uuid.uuid4().hex[:16]
        corr = correlation_id or uuid.uuid4().hex[:12]

        # Determine initial status from policy
        if decision.deny:
            status = "denied"
        elif decision.allow and not decision.require_approval:
            status = "approved"
        else:
            status = "pending"

        req = AuthorityRequest(
            id=req_id,
            ts=now,
            actor_type=actor_type,
            actor_id=actor_id,
            session_id=session_id,
            action=action,
            resource=resource,
            params=params or {},
            reason=reason,
            status=status,
            correlation_id=corr,
            policy_decision=("allow" if decision.allow else "deny" if decision.deny else "require_approval"),
            policy_reason=decision.reason,
        )

        with _lock:
            c = self._conn()
            try:
                self._ensure_tables(c)
                c.execute(
                    "INSERT INTO authority_requests (id, ts, actor_type, actor_id, session_id, action, resource, params_json, reason, status, correlation_id, policy_decision, policy_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (req.id, req.ts, req.actor_type, req.actor_id, req.session_id, req.action, req.resource, json.dumps(req.params), req.reason, req.status, req.correlation_id, req.policy_decision, req.policy_reason),
                )
                c.commit()
            finally:
                c.close()

        # emit audit event (best effort)
        try:
            from core.events import emit
            emit("authority_requested", f"request {req.id} {action} -> {req.status}", session_id=session_id, agent=actor_id, data=req.to_dict())
        except Exception:
            pass

        result: dict[str, Any] = {"request": req.to_dict(), "policy": asdict(decision)}

        # Auto-issue grant if policy allowed
        if status == "approved":
            grant = self._issue_grant(req, created_by="policy:auto-allow")
            result["grant"] = grant.to_dict()
        elif status == "pending":
            result["grant"] = None
        else:
            result["grant"] = None

        return result

    def approve(
        self,
        request_id: str,
        approved_by: str = "human",
        ttl_seconds: int | None = None,
    ) -> dict:
        """Approve a pending request and issue a scoped grant."""
        with _lock:
            c = self._conn()
            try:
                self._ensure_tables(c)
                row = c.execute("SELECT * FROM authority_requests WHERE id = ?", (request_id,)).fetchone()
                if not row:
                    raise KeyError(f"request {request_id} not found")
                if row["status"] != "pending":
                    raise ValueError(f"request {request_id} is not pending (status={row['status']})")
                # optimistic: mark approved
                c.execute("UPDATE authority_requests SET status='approved' WHERE id=?", (request_id,))
                c.commit()
                # re-fetch as object for grant issuance
                req = self._row_to_request(row)
                req.status = "approved"
            finally:
                c.close()

        grant = self._issue_grant(req, created_by=approved_by, ttl_seconds=ttl_seconds)

        try:
            from core.events import emit
            emit("authority_approved", f"approved {request_id} -> grant {grant.id}", session_id=req.session_id, agent=approved_by, data={"request_id": request_id, "grant_id": grant.id})
        except Exception:
            pass

        return {"request": req.to_dict(), "grant": grant.to_dict()}

    def deny(self, request_id: str, denied_by: str = "human", reason: str = "") -> dict:
        with _lock:
            c = self._conn()
            try:
                self._ensure_tables(c)
                row = c.execute("SELECT * FROM authority_requests WHERE id = ?", (request_id,)).fetchone()
                if not row:
                    raise KeyError(f"request {request_id} not found")
                if row["status"] != "pending":
                    raise ValueError(f"request {request_id} is not pending (status={row['status']})")
                c.execute("UPDATE authority_requests SET status='denied' WHERE id=?", (request_id,))
                c.commit()
                req = self._row_to_request(row)
                req.status = "denied"
            finally:
                c.close()

        try:
            from core.events import emit
            emit("authority_denied", f"denied {request_id}: {reason}", session_id=req.session_id, agent=denied_by, data={"request_id": request_id, "reason": reason})
        except Exception:
            pass

        return {"request": req.to_dict(), "grant": None}

    def get_request(self, request_id: str) -> dict | None:
        with _lock:
            c = self._conn()
            try:
                row = c.execute("SELECT * FROM authority_requests WHERE id = ?", (request_id,)).fetchone()
                if not row:
                    return None
                return self._row_to_request(row).to_dict()
            finally:
                c.close()

    def list_requests(self, status: str | None = None, limit: int = 50) -> list[dict]:
        with _lock:
            c = self._conn()
            try:
                if status:
                    rows = c.execute("SELECT * FROM authority_requests WHERE status=? ORDER BY ts DESC LIMIT ?", (status, limit)).fetchall()
                else:
                    rows = c.execute("SELECT * FROM authority_requests ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
                return [self._row_to_request(r).to_dict() for r in rows]
            finally:
                c.close()

    def list_pending(self, limit: int = 50) -> list[dict]:
        return self.list_requests(status="pending", limit=limit)

    # -- grants --------------------------------------------------------------

    def _issue_grant(self, req: AuthorityRequest, created_by: str = "human", ttl_seconds: int | None = None) -> Grant:
        ttl = ttl_seconds if ttl_seconds is not None else self.grant_ttl_seconds
        now = time.time()
        grant = Grant(
            id=uuid.uuid4().hex[:16],
            request_id=req.id,
            actor_id=req.actor_id,
            session_id=req.session_id,
            action=req.action,
            resource=req.resource,
            scope={"action": req.action, "resource": req.resource},
            expires_at=now + ttl,
            single_use=True,
            used=False,
            created_at=now,
            created_by=created_by,
        )
        with _lock:
            c = self._conn()
            try:
                c.execute(
                    "INSERT INTO grants (id, request_id, actor_id, session_id, action, resource, scope_json, expires_at, single_use, used, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (grant.id, grant.request_id, grant.actor_id, grant.session_id, grant.action, grant.resource, json.dumps(grant.scope), grant.expires_at, int(grant.single_use), int(grant.used), grant.created_at, grant.created_by),
                )
                c.commit()
            finally:
                c.close()

        try:
            from core.events import emit
            emit("grant_issued", f"grant {grant.id} for {req.action} on {req.resource}", session_id=req.session_id, agent=created_by, data=grant.to_dict())
        except Exception:
            pass

        return grant

    def get_grant(self, grant_id: str) -> dict | None:
        with _lock:
            c = self._conn()
            try:
                row = c.execute("SELECT * FROM grants WHERE id = ?", (grant_id,)).fetchone()
                if not row:
                    return None
                return self._row_to_grant(row).to_dict()
            finally:
                c.close()

    def verify_grant(self, grant_id: str, action: str, resource: str) -> tuple[bool, str]:
        """Check grant validity without consuming."""
        with _lock:
            c = self._conn()
            try:
                row = c.execute("SELECT * FROM grants WHERE id = ?", (grant_id,)).fetchone()
                if not row:
                    return False, "grant not found"
                grant = self._row_to_grant(row)
            finally:
                c.close()
        if grant.revoked_at:
            return False, "grant revoked"
        if grant.is_expired():
            return False, "grant expired"
        if grant.single_use and grant.used:
            return False, "grant already used"
        # scope check — exact match in v0 (no wildcards)
        if grant.action != action:
            return False, f"action scope mismatch: grant={grant.action} vs request={action}"
        if grant.resource != resource:
            return False, f"resource scope mismatch: grant={grant.resource} vs request={resource}"
        return True, "ok"

    def consume_grant(self, grant_id: str, action: str, resource: str) -> tuple[bool, str]:
        """Atomically verify and mark single-use grant as used."""
        with _lock:
            c = self._conn()
            try:
                row = c.execute("SELECT * FROM grants WHERE id = ?", (grant_id,)).fetchone()
                if not row:
                    return False, "grant not found"
                grant = self._row_to_grant(row)
                if grant.revoked_at:
                    return False, "grant revoked"
                if grant.is_expired():
                    return False, "grant expired"
                if grant.single_use and grant.used:
                    return False, "grant already used"
                if grant.action != action:
                    return False, f"action scope mismatch: grant={grant.action} vs request={action}"
                if grant.resource != resource:
                    return False, f"resource scope mismatch: grant={grant.resource} vs request={resource}"
                if grant.single_use:
                    # atomic update where used=0
                    cur = c.execute("UPDATE grants SET used=1 WHERE id=? AND used=0", (grant_id,))
                    if cur.rowcount == 0:
                        return False, "grant already used (race)"
                    c.commit()
                else:
                    c.commit()
                # emit
                try:
                    from core.events import emit
                    emit("grant_consumed", f"grant {grant_id} consumed for {action}", session_id=grant.session_id, agent=grant.actor_id, data={"grant_id": grant_id, "action": action, "resource": resource})
                except Exception:
                    pass
                return True, "ok"
            finally:
                c.close()

    def revoke_grant(self, grant_id: str) -> bool:
        with _lock:
            c = self._conn()
            try:
                cur = c.execute("UPDATE grants SET revoked_at=? WHERE id=?", (time.time(), grant_id))
                c.commit()
                return cur.rowcount > 0
            finally:
                c.close()

    # -- evidence ------------------------------------------------------------

    def record_evidence(
        self,
        *,
        request_id: str,
        grant_id: str = "",
        actor_id: str = "",
        action: str,
        resource: str = "",
        input_data: dict | None = None,
        outcome: str = "",
        success: bool = True,
        duration_ms: int = 0,
    ) -> dict:
        ev = Evidence(
            id=uuid.uuid4().hex[:16],
            request_id=request_id,
            grant_id=grant_id,
            actor_id=actor_id,
            action=action,
            resource=resource,
            input_data=input_data or {},
            outcome=outcome[:4000],
            success=success,
            ts=time.time(),
            duration_ms=duration_ms,
        )
        with _lock:
            c = self._conn()
            try:
                c.execute(
                    "INSERT INTO evidence (id, request_id, grant_id, actor_id, action, resource, input_json, outcome, success, ts, duration_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (ev.id, ev.request_id, ev.grant_id, ev.actor_id, ev.action, ev.resource, json.dumps(ev.input_data), ev.outcome, int(ev.success), ev.ts, ev.duration_ms),
                )
                c.commit()
            finally:
                c.close()

        try:
            from core.events import emit
            emit("execution_evidence", f"evidence {ev.id} for {action} success={success}", session_id="", agent=actor_id, data=ev.to_dict())
        except Exception:
            pass

        return ev.to_dict()

    def list_evidence(self, request_id: str | None = None, grant_id: str | None = None, limit: int = 50) -> list[dict]:
        with _lock:
            c = self._conn()
            try:
                if request_id:
                    rows = c.execute("SELECT * FROM evidence WHERE request_id=? ORDER BY ts DESC LIMIT ?", (request_id, limit)).fetchall()
                elif grant_id:
                    rows = c.execute("SELECT * FROM evidence WHERE grant_id=? ORDER BY ts DESC LIMIT ?", (grant_id, limit)).fetchall()
                else:
                    rows = c.execute("SELECT * FROM evidence ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
                return [self._row_to_evidence(r).to_dict() for r in rows]
            finally:
                c.close()

    def stats(self) -> dict:
        with _lock:
            c = self._conn()
            try:
                total_req = c.execute("SELECT COUNT(*) AS n FROM authority_requests").fetchone()["n"]
                pending = c.execute("SELECT COUNT(*) AS n FROM authority_requests WHERE status='pending'").fetchone()["n"]
                total_grants = c.execute("SELECT COUNT(*) AS n FROM grants").fetchone()["n"]
                total_evidence = c.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
                by_status = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) AS n FROM authority_requests GROUP BY status").fetchall()}
                return {"total_requests": total_req, "pending": pending, "total_grants": total_grants, "total_evidence": total_evidence, "by_status": by_status}
            finally:
                c.close()

    def cleanup_expired(self) -> int:
        """Mark pending requests that have outlived grant TTL as expired (optional). No auto-delete."""
        # grants are not deleted, just reported as expired via is_expired()
        # This marks very old pending requests as expired
        cutoff = time.time() - (self.grant_ttl_seconds * 10)
        with _lock:
            c = self._conn()
            try:
                cur = c.execute("UPDATE authority_requests SET status='expired' WHERE status='pending' AND ts < ?", (cutoff,))
                c.commit()
                return cur.rowcount
            finally:
                c.close()

    # -- helpers -------------------------------------------------------------

    def _ensure_schema_once(self, c: sqlite3.Connection) -> None:
        self._ensure_tables(c)

    def _row_to_request(self, r: sqlite3.Row) -> AuthorityRequest:
        return AuthorityRequest(
            id=r["id"], ts=r["ts"], actor_type=r["actor_type"], actor_id=r["actor_id"],
            session_id=r["session_id"], action=r["action"], resource=r["resource"],
            params=json.loads(r["params_json"] or "{}"), reason=r["reason"],
            status=r["status"], correlation_id=r["correlation_id"],
            policy_decision=r["policy_decision"], policy_reason=r["policy_reason"],
        )

    def _row_to_grant(self, r: sqlite3.Row) -> Grant:
        return Grant(
            id=r["id"], request_id=r["request_id"], actor_id=r["actor_id"],
            session_id=r["session_id"], action=r["action"], resource=r["resource"],
            scope=json.loads(r["scope_json"] or "{}"), expires_at=r["expires_at"],
            single_use=bool(r["single_use"]), used=bool(r["used"]),
            created_at=r["created_at"], created_by=r["created_by"],
            revoked_at=r["revoked_at"],
        )

    def _row_to_evidence(self, r: sqlite3.Row) -> Evidence:
        return Evidence(
            id=r["id"], request_id=r["request_id"], grant_id=r["grant_id"],
            actor_id=r["actor_id"], action=r["action"], resource=r["resource"],
            input_data=json.loads(r["input_json"] or "{}"), outcome=r["outcome"],
            success=bool(r["success"]), ts=r["ts"], duration_ms=r["duration_ms"],
        )

    def clear_all(self) -> None:
        """For tests only."""
        with _lock:
            c = self._conn()
            try:
                c.execute("DELETE FROM evidence")
                c.execute("DELETE FROM grants")
                c.execute("DELETE FROM authority_requests")
                c.commit()
            finally:
                c.close()
