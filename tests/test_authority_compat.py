"""Compat: legacy shim still works via hardened authority.

Verifies our 8/8 v0 scenarios still pass through the legacy request() shim
but using hardened semantics (PENDING, single-use, scope, expiry, evidence).
"""

from __future__ import annotations

import time

import pytest

from core.authority import AuthorityService, GrantConsumed, GrantExpired, GrantScopeMismatch, RequestNotPending


@pytest.fixture
def svc(tmp_path):
    db = tmp_path / "authority.db"
    return AuthorityService(db_path=db, grant_ttl_seconds=600)


@pytest.fixture
def svc_short_ttl(tmp_path):
    db = tmp_path / "authority_short.db"
    return AuthorityService(db_path=db, grant_ttl_seconds=1)


def test_request_pending_for_execute(svc):
    res = svc.request(actor_id="agent:osint", action="run_command", resource="shell:ls")
    assert res["request"]["status"].lower() == "pending"
    assert res["grant"] is None
    assert res["policy"]["require_approval"] is True


def test_approve_issues_scoped_grant(svc):
    res = svc.request(actor_id="human:alice", action="run_command", resource="shell:deploy", session_id="s1")
    req_id = res["request"]["id"]
    # legacy approve without ttl should use service default
    grant = svc.approve(req_id, approved_by="human:alice")
    # grant is CapabilityGrant object; to_dict for compat check
    gd = grant.to_dict() if hasattr(grant, "to_dict") else grant
    assert gd["action"] == "run_command"
    assert gd["resource"] == "shell:deploy"
    assert gd["single_use"] is True
    assert gd["consumed_at"] is None
    ok, _ = svc.verify_grant(gd["id"], "run_command", "shell:deploy")
    assert ok


def test_deny_blocks_grant(svc):
    res = svc.request(actor_id="agent:exec", action="delete", resource="db:users")
    req_id = res["request"]["id"]
    out = svc.deny(req_id, denied_by="human:bob", reason="too risky")
    # out is AuthorityRequest, check status
    assert out.status.value.lower() == "denied" if hasattr(out, "status") else out["request"]["status"].lower() == "denied"
    with pytest.raises(RequestNotPending):
        svc.approve(req_id, approved_by="human:bob")


def test_grant_expiry(svc_short_ttl):
    res = svc_short_ttl.request(actor_id="agent:exec", action="run_command", resource="shell:tmp")
    grant = svc_short_ttl.approve(res["request"]["id"], approved_by="human")
    gd = grant.to_dict() if hasattr(grant, "to_dict") else grant
    ok, _ = svc_short_ttl.verify_grant(gd["id"], "run_command", "shell:tmp")
    assert ok
    time.sleep(1.2)
    # verify should now be expired
    ok2, reason = svc_short_ttl.verify_grant(gd["id"], "run_command", "shell:tmp")
    assert not ok2
    assert "expired" in reason.lower()
    with pytest.raises(GrantExpired):
        svc_short_ttl.consume_grant(gd["id"], action="run_command", resource="shell:tmp")


def test_single_use_grant(svc):
    res = svc.request(actor_id="agent:exec", action="write_file", resource="/tmp/demo.txt")
    grant = svc.approve(res["request"]["id"], approved_by="human")
    gd = grant.to_dict() if hasattr(grant, "to_dict") else grant
    consumed = svc.consume_grant(gd["id"], action="write_file", resource="/tmp/demo.txt")
    assert consumed.consumed_at is not None if hasattr(consumed, "consumed_at") else True
    with pytest.raises(GrantConsumed):
        svc.consume_grant(gd["id"], action="write_file", resource="/tmp/demo.txt")
    ok3, reason3 = svc.verify_grant(gd["id"], "write_file", "/tmp/demo.txt")
    assert not ok3
    assert "already used" in reason3.lower()


def test_scope_must_match(svc):
    res = svc.request(actor_id="agent:exec", action="run_command", resource="shell:allowed")
    grant = svc.approve(res["request"]["id"], approved_by="human")
    gd = grant.to_dict() if hasattr(grant, "to_dict") else grant
    ok, reason = svc.verify_grant(gd["id"], "run_command", "shell:other")
    assert not ok
    assert "scope mismatch" in reason.lower()
    # scope mismatch should not consume
    with pytest.raises(GrantScopeMismatch):
        svc.consume_grant(gd["id"], action="github.delete_repository", resource="xosbot/nexus01-framework")
    # correct scope still consumes
    consumed = svc.consume_grant(gd["id"], action="run_command", resource="shell:allowed")
    assert consumed is not None


def test_evidence_recorded(svc):
    res = svc.request(actor_id="agent:exec", action="run_command", resource="shell:evidence")
    grant = svc.approve(res["request"]["id"], approved_by="human")
    gd = grant.to_dict() if hasattr(grant, "to_dict") else grant
    svc.consume_grant(gd["id"], action="run_command", resource="shell:evidence")
    # record_evidence via shim
    ev = svc.record_evidence(
        request_id=res["request"]["id"],
        grant_id=gd["id"],
        actor_id="agent:exec",
        action="run_command",
        resource="shell:evidence",
        input_data={"cmd": "echo hi"},
        outcome="ok",
        success=True,
        duration_ms=42,
    )
    assert ev["request_id"] == res["request"]["id"]
    listed = svc.list_evidence(request_id=res["request"]["id"])
    assert len([e for e in listed if e.event_type in ("execution.succeeded", "grant.consumed")]) >= 1


def test_confirm_mode_requires_human(tmp_path):
    # hardened: CONFIRM always requires human, OBSERVE denies
    from core.authority import ControlMode

    svc = AuthorityService(db_path=tmp_path / "confirm.db")
    req = svc.create_request(actor="agent:reader", principal="navigator", action="read_file", resource="/tmp/foo", mode=ControlMode.CONFIRM)
    assert req.status.value == "PENDING"
    # OBSERVE should be denied
    req2 = svc.create_request(actor="agent:reader", principal="navigator", action="read_file", resource="/tmp/foo", mode=ControlMode.OBSERVE)
    assert req2.status.value == "DENIED"
