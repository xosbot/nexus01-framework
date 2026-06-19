import pytest

from gateway.approvals import ApprovalManager
from gateway.gateway import NexusGateway
from gateway.types import ChannelKind, InboundMessage
from core.bus import Message, MessageBus


@pytest.fixture
def msg_bus():
    return MessageBus()


@pytest.fixture
def gateway(msg_bus):
    return NexusGateway(msg_bus, require_approval_for_exec=True)


@pytest.mark.asyncio
async def test_gateway_exec_requires_approval(gateway):
    inbound = InboundMessage(
        channel=ChannelKind.TELEGRAM,
        session_id="123",
        text="exec ls -la",
        user_id="user1",
    )
    response = await gateway.handle(inbound)
    assert response.requires_approval
    assert "ls -la" in response.text


@pytest.mark.asyncio
async def test_gateway_osint_no_approval(gateway, msg_bus):
    async def fake_orchestrator(message: Message):
        await msg_bus.publish(Message(
            sender="orchestrator",
            recipient=message.sender,
            type="response",
            payload={
                "data": {"status": "complete", "route": ["osint"], "output": "intel report"},
                "_correlation_id": message.payload.get("_correlation_id"),
            },
        ))

    msg_bus.subscribe("orchestrator", fake_orchestrator)

    inbound = InboundMessage(
        channel=ChannelKind.WHATSAPP,
        session_id="15551234",
        text="osint AI frameworks",
        user_id="15551234",
    )
    response = await gateway.handle(inbound)
    assert not response.requires_approval
    assert "intel report" in response.text


@pytest.mark.asyncio
async def test_gateway_approval_flow(gateway, msg_bus):
    executed = []

    async def fake_orchestrator(message: Message):
        executed.append(message.payload.get("text"))
        await msg_bus.publish(Message(
            sender="orchestrator",
            recipient=message.sender,
            type="response",
            payload={
                "data": {"status": "complete", "route": ["executor"], "output": "done"},
                "_correlation_id": message.payload.get("_correlation_id"),
            },
        ))

    msg_bus.subscribe("orchestrator", fake_orchestrator)

    first = await gateway.handle(InboundMessage(
        channel=ChannelKind.SLACK,
        session_id="C123",
        text="exec echo hello",
        user_id="U1",
    ))
    assert first.requires_approval

    second = await gateway.handle(InboundMessage(
        channel=ChannelKind.SLACK,
        session_id="C123",
        text="yes",
        user_id="U1",
        metadata={"approval_decision": True, "approval_id": first.approval_id},
    ))
    assert "Approved" in second.text
    assert executed == ["echo hello"]


def test_approval_manager_ttl():
    mgr = ApprovalManager()
    a = mgr.create("telegram", "1", "exec rm")
    assert mgr.get(a.id) is not None
    mgr.clear(a.id)
    assert mgr.get(a.id) is None


def test_gateway_user_allowlist(msg_bus):
    gw = NexusGateway(msg_bus, allowed_users={"telegram": ["999"]})
    assert gw.is_user_allowed("telegram", "999")
    assert not gw.is_user_allowed("telegram", "111")
