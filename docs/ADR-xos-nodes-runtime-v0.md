# ADR — XOS Nodes Runtime v0

**Status:** Accepted for prototype
**Date:** 2026-09-09
**Branch:** feat/xos-nodes-runtime-v0

## Purpose

Turn external AI coding/agent CLIs (OpenCode, Codex, Claude, Gemini, future
local CLIs, deterministic mocks) into durable, replaceable XOS workers —
without making them the control plane.

```
External provider intelligence is replaceable.

XOS owns identity.
NEXUS owns coordination.
XOS Control owns authority.
NodeManager owns process lifecycle.
Evidence remains durable.
```

## Context

XOS Control v0.1.2 is stable (durable AuthorityRequest, authenticated
approval, actor/principal-bound grants, atomic pre-execution, evidence,
reconciliation, CI green). It trusts `Message.sender`. Nodes Runtime must
therefore guarantee that a provider process can never choose its own trusted
sender identity.

No node/process/PTY/mailbox infrastructure existed (`core/bus.py`,
`core/authority.py`, `core/events.py`, `agents/executor.py` audited; only
heartbeat/session/LLM-provider concepts matched). This ADR introduces a new
`nodes/` package rather than duplicating bus/authority logic.

## Decision

### Node model

- `NodeIdentity` (persistent definition: node_id, name, provider, role,
  capabilities, working_directory, created_at) — survives restart.
- `NodeSession` (one runtime process/session: pid, state, started/ended,
  exit_code, last_seen) — history retained.
- `NodeState` (STOPPED/STARTING/RUNNING/IDLE/BUSY/WAITING/ERROR/STOPPING).
- Node IDs are generated/validated by XOS (`^[a-z0-9][a-z0-9_]{2,63}$`);
  duplicate `node_id` rejected; provider output never chooses trusted IDs.

### Registry

SQLite `data/xos_nodes.db` (gitignored via `data/` + `*.db`), WAL,
foreign_keys=ON, busy_timeout=5000, UTC timestamps, parameterized SQL.
Tables: `nodes`, `node_sessions`, `node_events`. Operations:
`register/get/list/update/update_state`, `start/get/end_session`,
`append_event/list_events`.

### Provider model

`ProviderAdapter` base (`available/version/executable/build_command/describe`).
`NodeManager` depends on the abstraction — no `if provider == ...` chains.
Adapters: `MockProvider` (deterministic `scripts/xos_mock_node.py`),
`OpenCodeProvider` (`opencode run <prompt> --format json --dir <cwd>`,
verified via local `--help`), `ClaudeProvider` (`claude -p`, verified),
`CodexProvider`/`GeminiProvider` skeletons (`available()` reflects local
install; automation flagged unsupported until verified).

### Process plane

`ProcessBackend` abstraction + `SubprocessBackend` (asyncio pipes).
PTY is a future backend — v0 does not let PTY complexity derail the slice.
Rules: argv arrays, never `shell=True`, executable + cwd validation, bounded
stdout/stderr (`MAX_OUTPUT_BYTES`), timeouts, process-group kill for orphans,
never log full env, never persist tokens.

### Mailbox / durable messaging

`data/nodes/<node_id>/{inbox,inbox/.done,outbox,outbox/.done}`,
one message = one JSON file (`id`, `correlation_id`, `from`, `to`, `act`,
`subject`, `body`, `hops`, `requires_reply`, `created_at`).
Acts: request/inform/propose/query/agree/refuse/done/error.
Write = temp + flush + fsync + atomic rename; processed moves to `.done/`
(retained). `MAX_HOPS=8`; over-limit rejected + event. Processed IDs tracked
per runtime; correlation preserved end-to-end.

### Event plane

Durable `node_events` (registered/starting/started/ready,
message.queued/sent/received/processed, busy/idle, interrupted/stopping/
stopped/failed/recovered, spoof.blocked). Bounded data (4000 chars).
`core.events` reused for live notifications only — never as durable state.

### Identity trust

`Message.sender` is the runtime trust source (matches XOS Control).
`NodeManager.build_trusted_message()` always sets `sender=node_id` from
NodeRegistry; provider-supplied `{"sender": ...}` is parsed only to log
`node.spoof.blocked` and is never honored. v0 identity is local runtime
identity, not cryptographic remote identity.

### NEXUS bridge

Live plane (`asyncio MessageBus`) + durable plane (mailbox/registry/events).
Outbound: NEXUS Message → `NodeManager.send` → durable inbox → process stdin.
Inbound: provider stdout → `NodeManager` → trusted `Message(sender=node_id)`
→ `MessageBus.publish` (if bus attached). Correlation ID preserved
(`correlation_id` + `_correlation_id`).

### XOS Control relationship

Authority semantics unchanged. Bridge helper
`manager.authority_request_for(node_id, action, resource)` returns
`actor=node_id`, so `AuthorityRequest.actor → grant binding → ExecutorAgent
Message.sender=node_id` holds end-to-end. Providers get no DB access to
`xos_control.db` and cannot approve their own requests. Authority layer
untouched.

### CWD / env safety

cwd must exist, be a dir, resolve absolute; `/` forbidden; symlink escape
outside `allowed_root` rejected. Env: inherit for v0 (documented),
`redact_env()` masks TOKEN/SECRET/PASSWORD/KEY/AUTH/COOKIE in logs/events;
secrets never persisted.

## Threat model

Fail closed on: shell/argv injection (argv arrays, executable allowlist via
PATH), arbitrary executable (validated), cwd traversal/symlink escape
(rejected), orphaning (process-group kill), PID reuse (stale-PID check in
`recover()`/`status()`), spoofing (sender from registry, spoof logged),
replay/duplicates (processed IDs + `.done`), loops (MAX_HOPS), unbounded
output (truncation), secret leakage (redaction), unsafe mailbox paths
(id validation, no `..`/`/`), unsafe JSON (validated schema), restart loops
(explicit `restart()` only, `check_unexpected_exits()` records `node.failed`).

Unresolved risks: MessageBus sender is not cryptographically authenticated
(next milestone: provider/node identity); single-node SQLite (no
distributed locking); PTY not yet implemented (interactive CLIs limited to
pipe mode).

## Known limitations

- OpenCode/Codex/Claude/Gemini real-model runs not executed in CI (network/
  subscription); adapters verified at CLI-syntax level only.
- No Git worktree orchestration (safe explicit cwd only).
- No auto-restart; heartbeat is PID/last_seen/exit_code only.

## Consequences

Proves: register one durable worker → launch → send work → trusted-identity
response → safe stop → restart → history recovered. Connecting more CLIs
becomes an adapter problem, not an architecture problem.
