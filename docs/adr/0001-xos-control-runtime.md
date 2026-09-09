# ADR 0001 — XOS Control Runtime v0

**Status:** Accepted for prototype  
**Date:** 2026-09-09

## Context

NEXUS already provides agents, routing, tools, memory, sandboxing, and Cold Mode
risk checks. What it does not yet provide is a durable authority boundary that
answers a different question from model confidence or operational safety:

> Is this actor actually permitted to perform this consequential action on this
> resource, in this environment, right now?

XOS Control v0 introduces that boundary without replacing NEXUS, changing the
message bus, or rewriting Cold Mode.

## Decision

The runtime is separated into five responsibilities:

1. **IVA — intelligence:** reasons, retrieves context, and proposes actions.
2. **NEXUS — orchestration:** decomposes work, routes tasks, and coordinates agents.
3. **XOS Control — authority:** evaluates policy, requests human approval, issues
   short-lived capability grants, and records evidence.
4. **Execution adapters — action:** shell, GitHub, browser, broker, payment,
   filesystem, and other consequential boundaries.
5. **Evidence ledger — proof:** durable append-first record of requests,
   decisions, grants, execution starts, outcomes, and failures.

An LLM may recommend an action. It does not authorize itself.

## Default operating mode

XOS defaults to **CONFIRM** mode.

| Mode | Meaning |
| --- | --- |
| OBSERVE | Consequential actions are denied. |
| PROPOSE | Agents may formulate actions, but execution is denied. |
| CONFIRM | Consequential actions require an explicit human capability grant. |
| DELEGATED | Future: narrow capabilities may be pre-authorized by policy. |
| AUTONOMOUS_DOMAIN | Future: bounded domains with budgets and kill switches. |

In v0, DELEGATED and AUTONOMOUS_DOMAIN intentionally fall back to CONFIRM
semantics until an explicit delegation policy exists.

## Vertical slice

```text
Agent / App
    |
    v
AuthorityRequest
    |
    v
Policy evaluation
    |------------------|
    v                  v
 DENY             REQUIRE_HUMAN
                        |
                        v
                 Root operator approval
                        |
                        v
                  CapabilityGrant
                  (short-lived,
                   scoped,
                   single-use)
                        |
                        v
                    Executor
                        |
                        v
                 Evidence ledger
```

## Authority request

A request binds:

- actor
- principal
- action
- resource
- environment
- risk class
- requested scope
- correlation id

## Capability grant

A grant is:

- tied to exactly one authority request
- scoped to that request's action and resource
- time limited
- single use by default
- invalid after consumption, expiry, denial, or scope mismatch

Executors receive a grant. They must never rely on a natural-language statement
such as "the user approved this".

## Evidence

Every meaningful transition is recorded as an immutable ledger event through the
service API. The initial event vocabulary is:

- `request.created`
- `request.denied`
- `request.approved`
- `grant.issued`
- `grant.expired`
- `grant.consumed`
- `execution.started`
- `execution.succeeded`
- `execution.failed`

The request and grant tables are mutable operational state. The evidence table is
append-only by API contract.

## Relationship to Cold Mode

Cold Mode remains a separate operational-risk layer.

```text
AUTHORITY: May this action happen?
RISK:      Is it safe enough to attempt?
```

Both gates must eventually pass before a consequential adapter executes. Model
confidence can never substitute for authority.

## v0 scope

Included:

- SQLite persistence
- OBSERVE / PROPOSE / CONFIRM policy evaluation
- durable authority requests
- explicit approve / deny
- expiring capability grants
- single-use grant consumption
- async authorized-execution wrapper
- append-only evidence events
- deterministic tests using an injectable clock

Deferred:

- provider/PTY adapters
- durable agent mailboxes
- delegation policy language
- identity federation
- cryptographic grant signing
- distributed control-plane consensus
- XOS Universe UI

## Security invariants

1. No grant is created without an existing pending request.
2. A denied request can never be approved later.
3. Action and resource must exactly match the grant scope.
4. Expired grants fail closed.
5. Consumed single-use grants fail closed.
6. Execution evidence is recorded for both success and failure.
7. Policy state is deterministic and never depends on an LLM response.

## Follow-up

After this slice is tested, wire `AuthorityService` into `ExecutorAgent` so
WRITE/EXECUTE/ADMIN actions require XOS authority before Cold Mode and tool
execution. Read-only behavior should remain backward compatible.