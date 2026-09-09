"""P0 hardening tests — auth, binding, atomic, crash, trace, ColdMode."""

from __future__ import annotations

import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from core.authority import (
    AuthorityService,
    ControlMode,
    GrantConsumed,
    GrantExpired,
    GrantScopeMismatch,
    RiskClass,
)
from fastapi.testclient import TestClient

# --- helpers for auth ---

def _make_app_with_authority(tmp_path=None):
    import api.auth as auth_mod
    from api.server import create_api_app

    # patch env keys for test
    auth_mod.API_KEY = auth_mod._parse_key("admin:test-admin-key")
    auth_mod.READONLY_KEY = auth_mod._parse_key("read:test-readonly-key")
    # ensure clean rate limiter
    auth_mod._rate_limiter._requests.clear()

    db = tempfile.mktemp(suffix=".db") if tmp_path is None else str(tmp_path / "auth.db")
    authority = AuthorityService(db_path=db)
    memory = MagicMock()
    memory.stats.return_value = {"sessions": 0, "conversations": 0, "knowledge": 0, "by_agent": {}}
    memory.projects = MagicMock()
    memory.sessions = MagicMock()
    memory.users = MagicMock()
    # need users.get for api_keys lookup? but env key bypasses that
    memory.api_keys = MagicMock()
    llm = MagicMock()
    llm.provider_status.return_value = []
    llm.stats.return_value = {}
    rag = MagicMock()
    rag.stats.return_value = {}
    gateway = MagicMock()
    nexus = SimpleNamespace(gateway=gateway, memory=memory, llm=llm, rag=rag, channels=[], brain=None, copilot=None, integrations=None, proactive=None, social_media=None, authority=authority, cost_tracker=MagicMock())
    nexus.cost_tracker.summary.return_value = {}
    app = create_api_app(nexus)
    return app, authority, auth_mod


def _create_request_for_test(auth):
    return auth.create_request(
        actor="agent.nexus",
        principal="navigator",
        action="run_command",
        resource="shell:echo hi",
        environment="local",
        risk_class=RiskClass.MEDIUM,
        requested_scope={"cmd": "echo hi"},
        correlation_id="corr-hard-001",
        mode=ControlMode.CONFIRM,
    )


# --- P0: approver identity must come from auth ---

def test_anonymous_approve_401(tmp_path):
    app, auth, _ = _make_app_with_authority(tmp_path)
    client = TestClient(app)
    req = _create_request_for_test(auth)
    # no auth header
    r = client.post(f"/api/authority/requests/{req.id}/approve", json={})
    assert r.status_code == 401, r.text


def test_normal_user_approve_403(tmp_path):
    app, auth, auth_mod = _make_app_with_authority(tmp_path)
    # create a user role token via env? env only supports admin/read. Simulate user via JWT
    import core.jwt_auth as jwt_mod
    jwt_mod.reset_secret_cache()
    token = jwt_mod.issue_token("user123", scope="user")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    req = _create_request_for_test(auth)
    r = client.post(f"/api/authority/requests/{req.id}/approve", json={})
    assert r.status_code == 403, r.text


def test_readonly_approve_403(tmp_path):
    app, auth, _ = _make_app_with_authority(tmp_path)
    client = TestClient(app, headers={"X-API-Key": "read:test-readonly-key"})
    req = _create_request_for_test(auth)
    r = client.post(f"/api/authority/requests/{req.id}/approve", json={})
    assert r.status_code == 403, r.text


def test_admin_approve_succeeds(tmp_path):
    app, auth, _ = _make_app_with_authority(tmp_path)
    client = TestClient(app, headers={"X-API-Key": "admin:test-admin-key"})
    req = _create_request_for_test(auth)
    r = client.post(f"/api/authority/requests/{req.id}/approve", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    # grant should be present
    grant = data.get("grant") or data
    assert grant is not None
    # stored approver should be authenticated admin identity, not forged
    # The approve endpoint derives approver from auth.user_id which for env key is "user_legacy"
    # So check that decided_by is that
    req2 = auth.get_request(req.id)
    assert req2.decided_by == "user_legacy"


def test_forged_approved_by_ignored(tmp_path):
    app, auth, _ = _make_app_with_authority(tmp_path)
    client = TestClient(app, headers={"X-API-Key": "admin:test-admin-key"})
    req = _create_request_for_test(auth)
    r = client.post(f"/api/authority/requests/{req.id}/approve", json={"approved_by": "navigator", "ttl_seconds": 100})
    assert r.status_code == 200
    req2 = auth.get_request(req.id)
    # forged should be ignored, stored should be user_legacy (the authenticated admin)
    assert req2.decided_by != "navigator"
    assert req2.decided_by == "user_legacy"


def test_deny_forged_ignored(tmp_path):
    app, auth, _ = _make_app_with_authority(tmp_path)
    client = TestClient(app, headers={"X-API-Key": "admin:test-admin-key"})
    req = _create_request_for_test(auth)
    r = client.post(f"/api/authority/requests/{req.id}/deny", json={"denied_by": "evil", "reason": "no"})
    assert r.status_code == 200
    req2 = auth.get_request(req.id)
    assert req2.decided_by == "user_legacy"
    assert req2.status.value == "DENIED"


# --- P0: grant actor+principal binding ---

def test_wrong_actor_fails(tmp_path):
    auth = AuthorityService(str(tmp_path / "a.db"))
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:ls", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    with pytest.raises(GrantScopeMismatch):
        auth.consume_grant(grant.id, action="run_command", resource="shell:ls", actor="executor.other", principal="navigator")
    # correct succeeds (still not consumed)
    consumed = auth.consume_grant(grant.id, action="run_command", resource="shell:ls", actor="iva", principal="navigator")
    assert consumed.consumed_at is not None


def test_wrong_principal_fails(tmp_path):
    auth = AuthorityService(str(tmp_path / "a.db"))
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:ls", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    with pytest.raises(GrantScopeMismatch):
        auth.consume_grant(grant.id, action="run_command", resource="shell:ls", actor="iva", principal="other")
    consumed = auth.consume_grant(grant.id, action="run_command", resource="shell:ls", actor="iva", principal="navigator")
    assert consumed.consumed_at is not None


def test_wrong_action_resource_fails(tmp_path):
    auth = AuthorityService(str(tmp_path / "a.db"))
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:ls", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    with pytest.raises(GrantScopeMismatch):
        auth.consume_grant(grant.id, action="run_command", resource="shell:other", actor="iva", principal="navigator")
    with pytest.raises(GrantScopeMismatch):
        auth.consume_grant(grant.id, action="write_file", resource="shell:ls", actor="iva", principal="navigator")


def test_expired_and_replay(tmp_path):
    auth = AuthorityService(str(tmp_path / "a.db"))
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:ls", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator", ttl_seconds=0)
    with pytest.raises(GrantExpired):
        auth.consume_grant(grant.id, action="run_command", resource="shell:ls", actor="iva", principal="navigator")
    # replay
    auth2 = AuthorityService(str(tmp_path / "b.db"))
    req2 = auth2.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:ls", mode=ControlMode.CONFIRM)
    grant2 = auth2.approve(req2.id, approved_by="navigator")
    auth2.consume_grant(grant2.id, action="run_command", resource="shell:ls", actor="iva", principal="navigator")
    with pytest.raises(GrantConsumed):
        auth2.consume_grant(grant2.id, action="run_command", resource="shell:ls", actor="iva", principal="navigator")


# --- P0: atomic double-consume with two independent connections ---

def test_two_connections_cannot_double_consume(tmp_path):
    db = str(tmp_path / "race.db")
    auth1 = AuthorityService(db)
    auth2 = AuthorityService(db)
    req = auth1.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:ls", mode=ControlMode.CONFIRM)
    grant = auth1.approve(req.id, approved_by="navigator")
    # both have separate connections to same file
    # attempt concurrent consume
    import threading

    results = []

    def try_consume(svc):
        try:
            svc.consume_grant(grant.id, action="run_command", resource="shell:ls", actor="iva", principal="navigator")
            results.append("ok")
        except GrantConsumed:
            results.append("consumed")
        except Exception as e:
            results.append(f"err:{type(e).__name__}")

    t1 = threading.Thread(target=try_consume, args=(auth1,))
    t2 = threading.Thread(target=try_consume, args=(auth2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert sorted(results) == ["consumed", "ok"] or results.count("ok") == 1
    # exactly one grant.consumed event
    evs = auth1.list_evidence(request_id=req.id)
    consumed = [e for e in evs if e.event_type == "grant.consumed"]
    assert len(consumed) == 1
    auth1.close()
    auth2.close()


# --- P0: execution lifecycle ---

@pytest.mark.asyncio
async def test_execution_started_before_tool(tmp_path):
    auth = AuthorityService(str(tmp_path / "a.db"))
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:echo hi", mode=ControlMode.CONFIRM, correlation_id="corr-exec-1")
    grant = auth.approve(req.id, approved_by="navigator")
    order = []

    async def tool():
        # check that started already exists before tool runs
        evs = auth.list_evidence(request_id=req.id)
        types = [e.event_type for e in evs]
        order.extend(types)
        assert "execution.started" in types
        assert "grant.consumed" in types
        return "ok"

    result = await auth.execute_with_grant(grant.id, action="run_command", resource="shell:echo hi", executor=tool, actor="iva", principal="navigator")
    assert result == "ok"
    evs = auth.list_evidence(request_id=req.id)
    types = [e.event_type for e in evs]
    assert types == ["request.created", "request.approved", "grant.issued", "grant.consumed", "execution.started", "execution.succeeded"]


@pytest.mark.asyncio
async def test_failure_creates_execution_failed(tmp_path):
    auth = AuthorityService(str(tmp_path / "a.db"))
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:fail", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")

    async def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await auth.execute_with_grant(grant.id, action="run_command", resource="shell:fail", executor=fail, actor="iva", principal="navigator")
    evs = auth.list_evidence(request_id=req.id)
    assert [e.event_type for e in evs][-1] == "execution.failed"
    assert evs[-1].data["error_type"] == "RuntimeError"


# --- P0: incomplete execution survives restart ---

def test_incomplete_survives_restart(tmp_path):
    db = str(tmp_path / "reco.db")
    auth = AuthorityService(db)
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:reco", mode=ControlMode.CONFIRM, correlation_id="corr-reco-1")
    grant = auth.approve(req.id, approved_by="navigator")
    # consume and started, but not succeeded/failed
    auth.consume_grant(grant.id, action="run_command", resource="shell:reco", actor="iva", principal="navigator")
    auth.record_execution_started(grant, actor="iva")
    auth.close()
    # reopen
    auth2 = AuthorityService(db)
    incomplete = auth2.list_incomplete_executions()
    assert len(incomplete) == 1
    assert incomplete[0]["grant_id"] == grant.id
    assert incomplete[0]["status"] == "RECONCILIATION_REQUIRED"
    # now complete it and ensure not incomplete
    auth2.record_execution_succeeded(grant, actor="iva")
    incomplete2 = auth2.list_incomplete_executions()
    assert len(incomplete2) == 0
    auth2.close()


def test_completed_not_incomplete(tmp_path):
    auth = AuthorityService(str(tmp_path / "a.db"))
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:ok", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    auth.consume_grant(grant.id, action="run_command", resource="shell:ok", actor="iva", principal="navigator")
    auth.record_execution_started(grant, actor="iva")
    auth.record_execution_succeeded(grant, actor="iva")
    assert len(auth.list_incomplete_executions()) == 0


# --- trace ---

def test_trace_ordered(tmp_path):
    auth = AuthorityService(str(tmp_path / "a.db"))
    corr = "corr-trace-123"
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:trace", mode=ControlMode.CONFIRM, correlation_id=corr)
    grant = auth.approve(req.id, approved_by="navigator")
    auth.consume_grant(grant.id, action="run_command", resource="shell:trace", actor="iva", principal="navigator")
    auth.record_execution_started(grant, actor="iva")
    auth.record_execution_succeeded(grant, actor="iva")
    trace = auth.trace(corr)
    types = [e.event_type for e in trace]
    assert types == ["request.created", "request.approved", "grant.issued", "grant.consumed", "execution.started", "execution.succeeded"]
    # all share correlation via request
    for e in trace:
        assert e.request_id == req.id


# --- ColdMode still blocks ---


@pytest.mark.asyncio
async def test_coldmode_blocks_even_with_grant(tmp_path):
    from agents.executor import ExecutorAgent
    from core.cold_mode import ColdMode
    from core.memory import Memory

    auth = AuthorityService(str(tmp_path / "a.db"))
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:rm -rf /", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    mem = Memory(db_path=tempfile.mktemp(suffix=".db"), chroma_path=tempfile.mktemp())
    cold = ColdMode(enabled=True)
    from unittest.mock import MagicMock
    llm = MagicMock()
    executor = ExecutorAgent(llm, mem, cold, rag=None, sandbox=None, authority=auth)
    from core.bus import Message
    # grant is valid but ColdMode should block dangerous command even with grant (no fallback, low confidence)
    msg = Message(sender="test", recipient="executor", type="task", payload={"action": "run_command", "params": {"cmd": "rm -rf /"}, "permission": "EXECUTE", "grant_id": grant.id, "actor": "iva", "principal": "navigator", "confidence": 0.3})
    res = await executor.on_message(msg)
    assert res["status"] == "blocked"
    # grant should NOT be consumed (still valid)
    ok, _ = auth.verify_grant(grant.id, "run_command", "shell:rm -rf /", actor="iva", principal="navigator")
    # if ColdMode blocked before consume, grant remains
    assert ok


# --- tool cannot run without authority when XOS enabled ---

@pytest.mark.asyncio
async def test_no_grant_blocked(tmp_path):
    from agents.executor import ExecutorAgent
    from core.cold_mode import ColdMode
    from core.memory import Memory
    auth = AuthorityService(str(tmp_path / "a.db"))
    mem = Memory(db_path=tempfile.mktemp(suffix=".db"), chroma_path=tempfile.mktemp())
    cold = ColdMode(enabled=True)
    from unittest.mock import MagicMock
    llm = MagicMock()
    executor = ExecutorAgent(llm, mem, cold, rag=None, sandbox=None, authority=auth)
    from core.bus import Message
    msg = Message(sender="test", recipient="executor", type="task", payload={"action": "run_command", "params": {"cmd": "echo hi", "fallback": "echo ok"}, "permission": "EXECUTE", "confidence": 0.9})
    res = await executor.on_message(msg)
    assert res["status"] == "blocked"
    assert "grant required" in str(res["reasons"]).lower()

