import pytest
from core.bus import Message, MessageBus
from core.cold_mode import ColdMode


@pytest.fixture
def msg_bus():
    return MessageBus()


@pytest.mark.asyncio
async def test_bus_request_response(msg_bus):
    async def echo_handler(message: Message):
        data = message.payload.get("text", "")
        await msg_bus.publish(Message(
            sender="worker",
            recipient=message.sender,
            type="response",
            payload={"data": f"echo:{data}", "_correlation_id": message.payload.get("_correlation_id")},
        ))

    msg_bus.subscribe("worker", echo_handler)

    reply = await msg_bus.request(Message(
        sender="cli",
        recipient="worker",
        type="task",
        payload={"text": "hello"},
    ))

    assert reply.type == "response"
    assert reply.payload["data"] == "echo:hello"


@pytest.mark.asyncio
async def test_bus_request_timeout(msg_bus):
    with pytest.raises(TimeoutError):
        await msg_bus.request(
            Message(sender="cli", recipient="nobody", type="task", payload={}),
            timeout=0.1,
        )


def test_cold_mode_read_skips_fallback():
    cold = ColdMode(enabled=True)
    ctx = ColdMode.build_context(action="read_file", permission="READ")
    assert not cold.should_block(ctx)


def test_cold_mode_execute_requires_fallback():
    cold = ColdMode(enabled=True)
    ctx = ColdMode.build_context(action="run_command", permission="EXECUTE")
    assert cold.should_block(ctx)


def test_cold_mode_execute_with_fallback():
    cold = ColdMode(enabled=True)
    ctx = ColdMode.build_context(
        action="run_command",
        permission="EXECUTE",
        fallback_script="echo safe",
        confidence=0.8,
    )
    assert not cold.should_block(ctx)


def test_cold_mode_low_confidence_blocks():
    cold = ColdMode(enabled=True)
    ctx = ColdMode.build_context(action="read_file", permission="READ", confidence=0.5)
    assert cold.should_block(ctx)
