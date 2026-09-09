"""XOS Control Runtime — focused authority tests (8/8).

Covers: request → policy → approve → grant lifecycle
        grant expiry, single-use, scope, evidence, confirm mode
"""

from __future__ import annotations

import time

import pytest

from core.authority import AuthorityService
from core.policy import Policy


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
    assert res["request"]["status"] == "pending"
    assert res["grant"] is None
    assert res["policy"]["require_approval"] is True


def test_approve_issues_scoped_grant(svc):
    res = svc.request(actor_id="human:alice", action="run_command", resource="shell:deploy", session_id="s1")
    req_id = res["request"]["id"]
    out = svc.approve(req_id, approved_by="human:alice")
    grant = out["grant"]
    assert grant["action"] == "run_command"
    assert grant["resource"] == "shell:deploy"
    assert grant["single_use"] is True
    assert grant["used"] is False
    # verify without consuming still valid
    ok, _ = svc.verify_grant(grant["id"], "run_command", "shell:deploy")
    assert ok


def test_deny_blocks_grant(svc):
    res = svc.request(actor_id="agent:exec", action="delete", resource="db:users")
    req_id = res["request"]["id"]
    out = svc.deny(req_id, denied_by="human:bob", reason="too risky")
    assert out["request"]["status"] == "denied"
    assert out["grant"] is None
    # approve after deny should fail
    with pytest.raises(ValueError):
        svc.approve(req_id)


def test_grant_expiry(svc_short_ttl):
    res = svc_short_ttl.request(actor_id="agent:exec", action="run_command", resource="shell:tmp")
    grant = svc_short_ttl.approve(res["request"]["id"])["grant"]
    ok, _ = svc_short_ttl.verify_grant(grant["id"], "run_command", "shell:tmp")
    assert ok
    time.sleep(1.2)
    ok2, reason = svc_short_ttl.verify_grant(grant["id"], "run_command", "shell:tmp")
    assert not ok2
    assert "expired" in reason


def test_single_use_grant(svc):
    res = svc.request(actor_id="agent:exec", action="write_file", resource="/tmp/demo.txt")
    grant = svc.approve(res["request"]["id"])["grant"]
    ok, _ = svc.consume_grant(grant["id"], "write_file", "/tmp/demo.txt")
    assert ok
    ok2, reason = svc.consume_grant(grant["id"], "write_file", "/tmp/demo.txt")
    assert not ok2
    assert "already used" in reason
    ok3, reason3 = svc.verify_grant(grant["id"], "write_file", "/tmp/demo.txt")
    assert not ok3
    assert "already used" in reason3


def test_scope_must_match(svc):
    res = svc.request(actor_id="agent:exec", action="run_command", resource="shell:allowed")
    grant = svc.approve(res["request"]["id"])["grant"]
    ok, reason = svc.verify_grant(grant["id"], "run_command", "shell:other")
    assert not ok
    assert "scope mismatch" in reason
    ok2, reason2 = svc.verify_grant(grant["id"], "write_file", "shell:allowed")
    assert not ok2
    assert "scope mismatch" in reason2
    # correct scope still consumes
    ok3, _ = svc.consume_grant(grant["id"], "run_command", "shell:allowed")
    assert ok3


def test_evidence_recorded(svc):
    res = svc.request(actor_id="agent:exec", action="run_command", resource="shell:evidence")
    grant = svc.approve(res["request"]["id"])["grant"]
    svc.consume_grant(grant["id"], "run_command", "shell:evidence")
    ev = svc.record_evidence(
        request_id=res["request"]["id"],
        grant_id=grant["id"],
        actor_id="agent:exec",
        action="run_command",
        resource="shell:evidence",
        input_data={"cmd": "echo hi"},
        outcome="ok",
        success=True,
        duration_ms=42,
    )
    assert ev["request_id"] == res["request"]["id"]
    assert ev["grant_id"] == grant["id"]
    listed = svc.list_evidence(request_id=res["request"]["id"])
    assert len(listed) == 1
    assert listed[0]["id"] == ev["id"]


def test_confirm_mode_requires_approval_even_for_read(tmp_path):
    policy = Policy(confirm_mode=True)
    svc_confirm = AuthorityService(db_path=tmp_path / "confirm.db", policy=policy)
    res = svc_confirm.request(actor_id="agent:reader", action="read_file", resource="/tmp/foo")
    assert res["request"]["status"] == "pending"
    assert res["policy"]["require_approval"] is True
    # normal mode auto-allows read
    svc_normal = AuthorityService(db_path=tmp_path / "normal.db", policy=Policy(confirm_mode=False))
    res2 = svc_normal.request(actor_id="agent:reader", action="read_file", resource="/tmp/foo")
    assert res2["request"]["status"] == "approved"
    assert res2["grant"] is not None
