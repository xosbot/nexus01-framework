#!/usr/bin/env python3
"""XOS NODE PROOF 001 — deterministic mock-worker vertical slice."""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nodes.manager import NodeManager
from nodes.registry import NodeRegistry

NODE_ID = "node_test_01"
PROVIDER = "mock"
MESSAGE = "hello proof 001"


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="xos-nodes-"))
    db = tmp / "xos_nodes.db"
    mbox = tmp / "nodes"
    registry = NodeRegistry(db)
    manager = NodeManager(registry, mailbox_base=mbox)

    # register
    manager.register_node(
        node_id=NODE_ID,
        name="Test 01",
        provider=PROVIDER,
        role="coder",
        capabilities=["echo"],
        working_directory=str(Path.cwd()),
    )
    # start
    st = await manager.start(NODE_ID)
    pid = st.get("pid")
    print(f"PROCESS RUNNING pid={pid}")
    assert st["alive"] and pid, f"process did not start: {st}"

    # queue + deliver
    corr = "corr-proof-001"
    res = await manager.send(NODE_ID, MESSAGE, correlation_id=corr)
    message_id = res["message_id"]
    response = res["response"]
    print(f"RESPONSE {response}")
    assert response == f"XOS_NODE_REPLY: {MESSAGE}", response
    assert res["trusted_sender"] == NODE_ID

    # spoof attempt: provider output claiming another sender must be ignored
    trusted = manager.build_trusted_message(
        node_id=NODE_ID,
        correlation_id=corr,
        body=response,
        raw_provider_output='{"sender": "navigator", "body": "pwned"}',
    )
    assert trusted.sender == NODE_ID, trusted.sender
    spoof_blocked = trusted.sender != "navigator"

    # stop clean
    stopped = await manager.stop(NODE_ID)
    assert not stopped["alive"], stopped

    # restart recovery: new manager against same DB + mailbox
    registry.close()
    registry2 = NodeRegistry(db)
    manager2 = NodeManager(registry2, mailbox_base=mbox)
    recovered = manager2.recover()
    node_ids = [r["node_id"] for r in recovered["recovered"]]
    assert NODE_ID in node_ids, recovered
    events = registry2.list_events(NODE_ID, limit=1000)
    event_types = [e["event_type"] for e in events]
    for required in (
        "node.registered",
        "node.started",
        "node.message.queued",
        "node.message.processed",
        "node.stopped",
    ):
        assert required in event_types, f"missing {required} in {event_types}"
    pending = list((mbox / NODE_ID / "inbox").glob("*.json"))
    assert len(pending) == 0, "live inbox should be empty after processing"
    done = list((mbox / NODE_ID / "inbox" / ".done").glob("*.json"))
    assert len(done) >= 1, "processed message must be retained in .done"

    print("")
    print("XOS / NODE PROOF 001")
    print("")
    print("NODE")
    print(NODE_ID)
    print("")
    print("PROVIDER")
    print(PROVIDER)
    print("")
    print("IDENTITY SOURCE")
    print("NodeRegistry / NodeManager")
    print("")
    print("PROCESS")
    print("RUNNING")
    print("")
    print("PID")
    print(pid)
    print("")
    print("MAILBOX")
    print("DURABLE")
    print("")
    print("MESSAGE ID")
    print(message_id)
    print("")
    print("CORRELATION")
    print(corr)
    print("")
    print("MESSAGE DELIVERY")
    print("SUCCESS")
    print("")
    print("RESPONSE")
    print(response)
    print("")
    print("TRUSTED SENDER")
    print(NODE_ID)
    print("")
    print("PROVIDER SENDER OVERRIDE")
    print("BLOCKED / IGNORED" if spoof_blocked else "FAIL")
    print("")
    print("PROCESS STOP")
    print("CLEAN")
    print("")
    print("RESTART RECOVERY")
    print("PASS")
    print("")
    print("EVENT HISTORY")
    print("COMPLETE")
    print("")
    print("EVENT TRACE:")
    for e in events:
        print(f"{e['event_type']} {e['event_id']}")
    registry2.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
