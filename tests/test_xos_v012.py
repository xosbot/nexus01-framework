"""v0.1.2 final boundary tests — required by spec section 10."""

from __future__ import annotations

import tempfile
import asyncio
import pytest

from core.authority import AuthorityService, ControlMode, GrantConsumed, GrantScopeMismatch, RiskClass
from core.bus import Message
from core.cold_mode import ColdMode
from agents.executor import ExecutorAgent
from core.memory import Memory
from unittest.mock import MagicMock


def _auth(tmp_path):
    return AuthorityService(str(tmp_path / "x.db"))


def _executor(auth, tmp_path=None):
    mem = Memory(db_path=tempfile.mktemp(suffix=".db"), chroma_path=tempfile.mktemp())
    cold = ColdMode(enabled=True)
    llm = MagicMock()
    return ExecutorAgent(llm, mem, cold, rag=None, sandbox=None, authority=auth)


# 1. Bypass closure — all consequential require grant regardless of permission
@pytest.mark.asyncio
async def test_write_file_write_no_grant_blocked(tmp_path):
    auth = _auth(tmp_path)
    ex = _executor(auth)
    msg = Message(sender="iva", recipient="executor", type="task", payload={"action": "write_file", "params": {"path": "/tmp/x", "content": "hi"}, "permission": "WRITE"})
    res = await ex.on_message(msg)
    assert res["status"] == "blocked"
    assert "grant required" in str(res["reasons"]).lower()


@pytest.mark.asyncio
async def test_run_command_read_no_grant_blocked(tmp_path):
    auth = _auth(tmp_path)
    ex = _executor(auth)
    msg = Message(sender="iva", recipient="executor", type="task", payload={"action": "run_command", "params": {"cmd": "echo hi"}, "permission": "READ"})
    res = await ex.on_message(msg)
    assert res["status"] == "blocked"


@pytest.mark.asyncio
async def test_delete_write_no_grant_blocked(tmp_path):
    auth = _auth(tmp_path)
    ex = _executor(auth)
    msg = Message(sender="iva", recipient="executor", type="task", payload={"action": "delete", "params": {"path": "/tmp/x"}, "permission": "WRITE"})
    res = await ex.on_message(msg)
    assert res["status"] == "blocked"


@pytest.mark.asyncio
async def test_approved_true_no_grant_blocked(tmp_path):
    auth = _auth(tmp_path)
    ex = _executor(auth)
    msg = Message(sender="iva", recipient="executor", type="task", payload={"action": "run_command", "params": {"cmd": "echo hi"}, "permission": "READ", "approved": True})
    res = await ex.on_message(msg)
    assert res["status"] == "blocked"


@pytest.mark.asyncio
async def test_arbitrary_permission_no_grant_blocked(tmp_path):
    auth = _auth(tmp_path)
    ex = _executor(auth)
    msg = Message(sender="iva", recipient="executor", type="task", payload={"action": "run_command", "params": {"cmd": "echo hi"}, "permission": "YOLO"})
    res = await ex.on_message(msg)
    assert res["status"] == "blocked"


# 2. Actor trust source: message.sender is truth, payload actor must not override
@pytest.mark.asyncio
async def test_actor_payload_cannot_override_sender(tmp_path):
    auth = _auth(tmp_path)
    # grant for iva
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:echo hi", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    ex = _executor(auth)
    # payload says actor iva but sender is evil — should be blocked (sender mismatch)
    msg = Message(sender="evil-agent", recipient="executor", type="task", payload={"action": "run_command", "params": {"cmd": "echo hi", "actor": "iva"}, "permission": "EXECUTE", "grant_id": grant.id, "confidence": 0.9, "fallback_script": "echo ok"})
    res = await ex.on_message(msg)
    assert res["status"] == "blocked"
    assert "actor mismatch" in str(res["reasons"]).lower()


@pytest.mark.asyncio
async def test_wrong_sender_rejected(tmp_path):
    auth = _auth(tmp_path)
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:echo hi", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    ex = _executor(auth)
    msg = Message(sender="evil-agent", recipient="executor", type="task", payload={"action": "run_command", "params": {"cmd": "echo hi"}, "permission": "EXECUTE", "grant_id": grant.id, "confidence": 0.9, "fallback_script": "echo ok"})
    res = await ex.on_message(msg)
    assert res["status"] == "blocked"


@pytest.mark.asyncio
async def test_correct_sender_accepted(tmp_path):
    auth = _auth(tmp_path)
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:echo hi", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    ex = _executor(auth)
    msg = Message(sender="iva", recipient="executor", type="task", payload={"action": "run_command", "params": {"cmd": "echo hi"}, "permission": "EXECUTE", "grant_id": grant.id, "confidence": 0.9, "fallback_script": "echo ok"})
    res = await ex.on_message(msg)
    assert "stdout" in res
    assert "hi" in res["stdout"]


# 3. Principal cannot be widened
def test_principal_widen_blocked(tmp_path):
    auth = _auth(tmp_path)
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:echo hi", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    # attempt to consume with different principal
    with pytest.raises(GrantScopeMismatch):
        auth.consume_grant(grant.id, action="run_command", resource="shell:echo hi", actor="iva", principal="evil-principal")
    # correct still works
    c = auth.consume_grant(grant.id, action="run_command", resource="shell:echo hi", actor="iva", principal="navigator")
    assert c.consumed_at is not None


# 4. BEGIN IMMEDIATE failure fails closed — simulate lock via second connection holding transaction
def test_begin_failure_fails_closed(tmp_path):
    import sqlite3
    db = str(tmp_path / "busy.db")
    auth = AuthorityService(db)
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:echo hi", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    # Hold a lock with second connection
    conn2 = sqlite3.connect(db, timeout=1.0)
    conn2.execute("BEGIN IMMEDIATE")
    # Now auth's BEGIN should fail or busy (fail closed)
    # Reduce busy timeout to make it fail fast
    auth._conn.execute("PRAGMA busy_timeout=100")
    with pytest.raises(Exception) as exc:
        auth.consume_grant(grant.id, action="run_command", resource="shell:echo hi", actor="iva", principal="navigator")
    assert "busy" in str(exc.value).lower() or "locked" in str(exc.value).lower() or "busy" in str(type(exc.value)).lower()
    # grant remains unconsumed
    # Need new connection without lock to verify
    conn2.execute("ROLLBACK")
    conn2.close()
    auth2 = AuthorityService(db)
    ok, _ = auth2.verify_grant(grant.id, "run_command", "shell:echo hi", actor="iva", principal="navigator")
    assert ok
    evs = auth2.list_evidence(request_id=req.id)
    assert not any(e.event_type == "grant.consumed" for e in evs)
    auth.close()
    auth2.close()


# 5. Atomic pre-execution: consume+grant.consumed+execution.started in one txn
@pytest.mark.asyncio
async def test_atomic_pre_execution(tmp_path):
    auth = _auth(tmp_path)
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:atomic", mode=ControlMode.CONFIRM, correlation_id="corr-atomic-1")
    grant = auth.approve(req.id, approved_by="navigator")
    # begin_execution should produce 3 events atomically
    g = auth.begin_execution(grant.id, actor="iva", principal="navigator", action="run_command", resource="shell:atomic")
    assert g.consumed_at is not None
    evs = auth.list_evidence(request_id=req.id)
    types = [e.event_type for e in evs]
    # should be request.created, request.approved, grant.issued, grant.consumed, execution.started
    assert types == ["request.created", "request.approved", "grant.issued", "grant.consumed", "execution.started"]
    # no succeeded yet
    assert "execution.succeeded" not in types


# 6. Incomplete reconciliation both cases
def test_legacy_partial_consumed_without_started(tmp_path):
    db = str(tmp_path / "legacy.db")
    auth = AuthorityService(db)
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:legacy", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    # manually consume without started (legacy path: directly update consumed without started)
    # Use old consume that also adds grant.consumed but not started — we simulate by directly consuming via consume_grant (which now also does not add started if using old path? Actually begin_execution adds started, but consume adds grant.consumed only)
    # So consume via consume_grant (not begin_execution) will create consumed without started
    auth2 = AuthorityService(db)
    # use second connection to consume
    grant2 = auth2.consume_grant(grant.id, action="run_command", resource="shell:legacy", actor="iva", principal="navigator")
    # now incomplete should detect consumed without started
    incomplete = auth.list_incomplete_executions()
    assert any(i["grant_id"] == grant.id for i in incomplete)
    assert incomplete[0]["status"] == "RECONCILIATION_REQUIRED"
    auth.close()
    auth2.close()


# 7. ColdMode denial leaves grant unconsumed
@pytest.mark.asyncio
async def test_coldmode_leaves_grant_unconsumed(tmp_path):
    auth = _auth(tmp_path)
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:rm -rf /", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    ex = _executor(auth)
    msg = Message(sender="iva", recipient="executor", type="task", payload={"action": "run_command", "params": {"cmd": "rm -rf /"}, "permission": "EXECUTE", "grant_id": grant.id, "confidence": 0.2, "fallback_script": ""})
    res = await ex.on_message(msg)
    assert res["status"] == "blocked"
    # grant still unconsumed
    ok, _ = auth.verify_grant(grant.id, "run_command", "shell:rm -rf /", actor="iva", principal="navigator")
    assert ok


# 8. Grant replay still fails
def test_grant_replay(tmp_path):
    auth = _auth(tmp_path)
    req = auth.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:hi", mode=ControlMode.CONFIRM)
    grant = auth.approve(req.id, approved_by="navigator")
    auth.consume_grant(grant.id, action="run_command", resource="shell:hi", actor="iva", principal="navigator")
    with pytest.raises(GrantConsumed):
        auth.consume_grant(grant.id, action="run_command", resource="shell:hi", actor="iva", principal="navigator")


# 9. Two DB connections still yield one winner (already in hardening, but re-assert)
def test_two_connections_one_winner(tmp_path):
    import threading
    db = str(tmp_path / "race2.db")
    a1 = AuthorityService(db)
    a2 = AuthorityService(db)
    req = a1.create_request(actor="iva", principal="navigator", action="run_command", resource="shell:race", mode=ControlMode.CONFIRM)
    grant = a1.approve(req.id, approved_by="navigator")
    results = []

    def try_consume(svc):
        try:
            svc.consume_grant(grant.id, action="run_command", resource="shell:race", actor="iva", principal="navigator")
            results.append("ok")
        except GrantConsumed:
            results.append("consumed")
        except Exception as e:
            results.append(str(type(e)))

    t1 = threading.Thread(target=try_consume, args=(a1,))
    t2 = threading.Thread(target=try_consume, args=(a2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert results.count("ok") == 1
    assert results.count("consumed") == 1

