# ADR — XOS Control Runtime v0

**Date:** 2026-09-09
**Status:** Implemented (feat/xos-control-runtime-v0)
**Branch:** feat/xos-control-runtime-v0
**Context:** Master Build Prompt — XOS Control Runtime

## Thesis

> AI can think. XOS governs how it acts.

## Execution Chain (implemented)

```
AGENT/HUMAN → AUTHORITY REQUEST → POLICY → HUMAN AUTHORITY → SCOPED GRANT → EXECUTION BOUNDARY → ACTION → EVIDENCE → AUDIT
```

## Decision Log

| Decision | Choice | Rationale |
|---|---|---|
| Persistence | SQLite `data/authority.db` WAL | Standard library, no Redis/Postgres, aligns with existing `events.db` pattern |
| Policy | Pure Python `core/policy.py` deterministic | No LLM needed for v0, testable, prevents hidden autonomy |
| Grant scope | Exact `action`+`resource` match, single-use, 10m TTL | Prevents overly broad grants; principle of least privilege |
| Event audit | Extend `core/events.py` with `authority_*` / `grant_*` / `execution_evidence` kinds | Reuses existing durable substrate, no new infra |
| Gateway integration | `NexusGateway` creates `AuthorityRequest` + bridges `ApprovalManager` | Preserves existing Telegram/WhatsApp HITL, adds durability |
| Execution boundary | `ExecutorAgent` verifies + consumes grant before `act()` | Enforcement at tool boundary, not just gateway |
| Exposure | No public `POST /api/authority/execute` that runs arbitrary commands | Prevents bypass of authority; only approve/deny + verify are public |
| Cold Mode | Keep as inner gate (defense in depth) | Do not weaken existing safety; XOS is additive |
| Config | `config.py` adds `XOS_AUTHORITY_DB`, `XOS_GRANT_TTL_SECONDS`, `XOS_CONFIRM_MODE` | Env-driven, no secrets in code |

## What Was Added

- `core/policy.py` — `Policy.evaluate(action,resource) -> PolicyDecision`
- `core/authority.py` — `AuthorityService` with `request/approve/deny`, `verify/consume_grant`, `record_evidence`, SQLite tables `authority_requests`, `grants`, `evidence`
- `tests/test_authority.py` — 8 focused tests (pending, approve, deny, expiry, single-use, scope, evidence, confirm mode)
- `core/app.py` — instantiate `AuthorityService` and inject into `NexusGateway` + `ExecutorAgent`
- `gateway/gateway.py` — create durable authority requests for exec, sync approvals to authority, forward `grant_id`
- `agents/executor.py` — enforce scoped grant, defer consume until ColdMode passes, record evidence
- `api/server.py` — `/api/authority/request`, `/approve`, `/deny`, `/verify`, `/evidence`, `/stats`, `/pending`
- `config.py` / `core/events.py` — new flags + event kinds

## What Was Not Added (v0 constraints)

- No Redis, Postgres, or message queues
- No microservices, no public exec endpoint
- No live-money trading, no hidden autonomous execution
- No secrets in code, no overly broad grants

## Baseline Verification

- Ruff baseline on `main`: 301 errors (pre-existing debt across legacy files)
- After XOS: 328 errors (+27 from new code, same categories `BLE001/S110/I001`)
- pytest baseline: 452 passed + 1 pre-existing failure (`test_resilience` half_open flake) → 461 passed after XOS (8 new authority tests, flake passes when monotonic >999s)
- No regressions in `test_gateway`, `test_cold_mode`, `test_bus_and_cold_mode`, `test_api`

## Next Steps (not in v0)

- Dashboard UI for pending approvals + evidence timeline
- Policy YAML for custom risk rules
- Multi-actor roles (human vs agent identities)
- Grant revocation UI

## References

- `core/authority.py:1` — authority kernel
- `core/policy.py:1` — policy engine
- `agents/executor.py:36` — execution boundary
- `gateway/gateway.py:62` — authority bridge
