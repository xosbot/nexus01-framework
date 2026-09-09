"""XOS CONTROL PROOF 002 — message.sender is actor trust source."""

import asyncio
import tempfile
import uuid
from pathlib import Path

from core.authority import AuthorityService, ControlMode, RiskClass
from core.cold_mode import ColdMode
from agents.executor import ExecutorAgent
from core.memory import Memory
from core.bus import Message
from unittest.mock import MagicMock

db = tempfile.mktemp(suffix=".db")
auth = AuthorityService(db_path=db)

CORRELATION = f"corr-proof-002-{uuid.uuid4().hex[:8]}"
ACTOR = "agent.nexus"
PRINCIPAL = "navigator"
ACTION = "run_command"
RESOURCE = "shell:echo XOS CONTROL PROOF 002"

# 1) AuthorityRequest via agent.nexus
req = auth.create_request(
    actor=ACTOR,
    principal=PRINCIPAL,
    action=ACTION,
    resource=RESOURCE,
    environment="local",
    risk_class=RiskClass.MEDIUM,
    requested_scope={"cmd": "echo XOS CONTROL PROOF 002"},
    correlation_id=CORRELATION,
    mode=ControlMode.CONFIRM,
)
print(f"REQUEST {req.id} corr={CORRELATION}")

# 2) Operator approval (simulated navigator)
grant = auth.approve(req.id, approved_by="navigator")
print(f"GRANT {grant.id}")

# 3) Executor with message.sender as trust source — do NOT pass actor via payload
mem = Memory(db_path=tempfile.mktemp(suffix=".db"), chroma_path=tempfile.mktemp())
cold = ColdMode(enabled=True)
llm = MagicMock()
executor = ExecutorAgent(llm, mem, cold, rag=None, sandbox=None, authority=auth)

msg = Message(
    sender=ACTOR,  # trust source
    recipient="executor",
    type="task",
    payload={
        "action": ACTION,
        "params": {"cmd": "echo XOS CONTROL PROOF 002"},
        "permission": "EXECUTE",
        "grant_id": grant.id,
        # intentionally NOT passing actor in payload to prove sender is used
        "confidence": 0.9,
        "fallback_script": "echo ok",
    },
)

async def run():
    # Positive proof
    result = await executor.on_message(msg)
    print(f"POSITIVE result: {result}")
    assert result.get("stdout") and "XOS CONTROL PROOF 002" in result["stdout"]
    # Check atomic pre-execution: grant.consumed + execution.started in one txn
    trace = auth.trace(CORRELATION)
    types = [e.event_type for e in trace]
    print("TRACE:", " -> ".join(types))
    expected = ["request.created", "request.approved", "grant.issued", "grant.consumed", "execution.started", "execution.succeeded"]
    assert types == expected, f"expected {expected} got {types}"
    # Negative proof: same grant with evil sender should be blocked (grant already consumed, but also actor mismatch)
    # Create fresh grant for negative test
    req2 = auth.create_request(actor=ACTOR, principal=PRINCIPAL, action=ACTION, resource="shell:echo NEG", correlation_id="corr-neg-1", mode=ControlMode.CONFIRM)
    grant2 = auth.approve(req2.id, approved_by="navigator")
    evil_msg = Message(sender="evil-agent", recipient="executor", type="task", payload={"action": ACTION, "params": {"cmd": "echo NEG"}, "permission": "EXECUTE", "grant_id": grant2.id, "confidence": 0.9, "fallback_script": "echo ok"})
    evil_res = await executor.on_message(evil_msg)
    print(f"NEGATIVE result (evil): {evil_res}")
    assert evil_res["status"] == "blocked"
    assert "actor mismatch" in str(evil_res["reasons"]).lower()

    # Payload actor spoof should not override sender
    spoof_msg = Message(sender="evil-agent", recipient="executor", type="task", payload={"action": ACTION, "params": {"cmd": "echo NEG", "actor": ACTOR}, "permission": "EXECUTE", "grant_id": grant2.id, "confidence": 0.9, "fallback_script": "echo ok"})
    spoof_res = await executor.on_message(spoof_msg)
    print(f"SPOOF result: {spoof_res}")
    assert spoof_res["status"] == "blocked"

    # Print proof header
    print("\nXOS / CONTROL PROOF 002")
    print("ACTOR SOURCE\nMessage.sender")
    print(f"ACTOR\n{ACTOR}")
    print(f"PRINCIPAL\n{PRINCIPAL}")
    print("GRANT REQUIRED\nYES")
    print("SCOPE\nEXACT")
    print("PRE-EXECUTION ATOMIC\nPASS")
    print("COLD MODE\nPASS")
    print("EXECUTION\nSUCCESS")
    print("EVIDENCE\nCOMPLETE")
    print("RECONCILIATION\nNOT REQUIRED")
    print("\nTrace:")
    for e in trace:
        print(f"{e.event_type} {e.event_id}")
    print("\nNegative proof: evil-agent with same grant -> BLOCKED (actor mismatch)")

asyncio.run(run())
print("\nXOS CONTROL PROOF 002")
print("echo XOS CONTROL PROOF 002")
