from __future__ import annotations

import pytest

from core.authority import (
    AuthorityService,
    ControlMode,
    GrantConsumed,
    GrantExpired,
    GrantScopeMismatch,
    PolicyDecision,
    RequestNotPending,
    RequestStatus,
    RiskClass,
)


@pytest.fixture
def authority():
    service = AuthorityService(":memory:")
    try:
        yield service
    finally:
        service.close()


def _request(authority: AuthorityService, *, mode: ControlMode = ControlMode.CONFIRM):
    return authority.create_request(
        actor="agent.coder.01",
        principal="navigator",
        action="github.create_branch",
        resource="xosbot/nexus01-framework",
        environment="production",
        risk_class=RiskClass.MEDIUM,
        requested_scope={"branch": "proof/xos-control-001"},
        correlation_id="corr-proof-001",
        mode=mode,
    )


def test_confirm_mode_requires_human_and_issues_single_use_grant(authority: AuthorityService):
    request = _request(authority)

    assert request.status is RequestStatus.PENDING
    assert request.policy_decision is PolicyDecision.REQUIRE_HUMAN

    grant = authority.approve(request.id, approved_by="navigator", ttl_seconds=300)
    approved = authority.get_request(request.id)

    assert approved.status is RequestStatus.APPROVED
    assert approved.decided_by == "navigator"
    assert grant.request_id == request.id
    assert grant.action == request.action
    assert grant.resource == request.resource
    assert grant.single_use is True

    consumed = authority.consume_grant(
        grant.id,
        action="github.create_branch",
        resource="xosbot/nexus01-framework",
    )
    assert consumed.consumed_at is not None

    with pytest.raises(GrantConsumed):
        authority.consume_grant(
            grant.id,
            action="github.create_branch",
            resource="xosbot/nexus01-framework",
        )

    assert [e.event_type for e in authority.list_evidence(request_id=request.id)] == [
        "request.created",
        "request.approved",
        "grant.issued",
        "grant.consumed",
    ]


@pytest.mark.parametrize("mode", [ControlMode.OBSERVE, ControlMode.PROPOSE])
def test_non_execution_modes_fail_closed(authority: AuthorityService, mode: ControlMode):
    request = _request(authority, mode=mode)

    assert request.status is RequestStatus.DENIED
    assert request.policy_decision is PolicyDecision.DENY
    assert request.decided_by == "xos.policy"

    with pytest.raises(RequestNotPending):
        authority.approve(request.id, approved_by="navigator")

    assert [e.event_type for e in authority.list_evidence(request_id=request.id)] == [
        "request.created",
        "request.denied",
    ]


def test_explicit_denial_cannot_be_reversed(authority: AuthorityService):
    request = _request(authority)
    denied = authority.deny(request.id, denied_by="navigator", reason="Not this branch")

    assert denied.status is RequestStatus.DENIED
    assert denied.decided_by == "navigator"

    with pytest.raises(RequestNotPending):
        authority.approve(request.id, approved_by="navigator")


def test_scope_mismatch_fails_without_consuming_grant(authority: AuthorityService):
    request = _request(authority)
    grant = authority.approve(request.id, approved_by="navigator")

    with pytest.raises(GrantScopeMismatch):
        authority.consume_grant(
            grant.id,
            action="github.delete_repository",
            resource="xosbot/nexus01-framework",
        )

    still_valid = authority.consume_grant(
        grant.id,
        action="github.create_branch",
        resource="xosbot/nexus01-framework",
    )
    assert still_valid.consumed_at is not None


def test_expired_grant_fails_closed(authority: AuthorityService):
    request = _request(authority)
    grant = authority.approve(request.id, approved_by="navigator", ttl_seconds=0)

    with pytest.raises(GrantExpired):
        authority.consume_grant(
            grant.id,
            action="github.create_branch",
            resource="xosbot/nexus01-framework",
        )


@pytest.mark.asyncio
async def test_authorized_execution_records_success(authority: AuthorityService):
    request = _request(authority)
    grant = authority.approve(request.id, approved_by="navigator")

    async def create_branch() -> dict[str, str]:
        return {"branch": "proof/xos-control-001"}

    result = await authority.execute_with_grant(
        grant.id,
        action="github.create_branch",
        resource="xosbot/nexus01-framework",
        executor=create_branch,
        actor="agent.coder.01",
        principal="navigator",
    )

    assert result == {"branch": "proof/xos-control-001"}
    assert [e.event_type for e in authority.list_evidence(request_id=request.id)] == [
        "request.created",
        "request.approved",
        "grant.issued",
        "grant.consumed",
        "execution.started",
        "execution.succeeded",
    ]


@pytest.mark.asyncio
async def test_authorized_execution_records_failure_and_reraises(authority: AuthorityService):
    request = authority.create_request(
        actor="agent.coder.02",
        principal="navigator",
        action="github.create_branch",
        resource="xosbot/nexus01-framework",
        mode=ControlMode.CONFIRM,
    )
    grant = authority.approve(request.id, approved_by="navigator")

    async def fail() -> None:
        raise RuntimeError("simulated adapter failure")

    with pytest.raises(RuntimeError, match="simulated adapter failure"):
        await authority.execute_with_grant(
            grant.id,
            action="github.create_branch",
            resource="xosbot/nexus01-framework",
            executor=fail,
            actor="agent.coder.02",
            principal="navigator",
        )

    events = authority.list_evidence(request_id=request.id)
    assert [e.event_type for e in events] == [
        "request.created",
        "request.approved",
        "grant.issued",
        "grant.consumed",
        "execution.started",
        "execution.failed",
    ]
    assert events[-1].data["error_type"] == "RuntimeError"
