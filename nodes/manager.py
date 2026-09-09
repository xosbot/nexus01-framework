"""NodeManager — runtime facade over registry + providers + processes + mailbox.

Trust model: provider output is NEVER trusted for identity. NodeManager
constructs bus Messages with sender=node_id from NodeRegistry. v0 identity
is local runtime identity, not cryptographic remote identity.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from nodes.identity import NodeState, validate_node_id
from nodes.mailbox import (
    MAX_HOPS,
    build_message,
    ensure_mailbox,
    list_done,
    list_pending,
    mark_done,
    write_message_atomic,
)
from nodes.process import (
    MAX_OUTPUT_BYTES,
    ProcessBackend,
    SubprocessBackend,
    build_child_env,
    is_pid_alive,
    kill_process_tree,
    redact_env,
    validate_cwd,
)
from nodes.providers import ProviderAdapter, get_adapter
from nodes.registry import DuplicateNode, NodeNotFound, NodeRegistry

logger = logging.getLogger(__name__)


@dataclass
class _Runtime:
    proc: asyncio.subprocess.Process | None = None
    session_id: str | None = None
    processed_ids: set[str] = field(default_factory=set)
    last_seen: float = 0.0


class NodeManager:
    """Owns node identity -> provider process -> session -> mailbox -> events."""

    def __init__(
        self,
        registry: NodeRegistry,
        mailbox_base: str | Path = "data/nodes",
        backend: ProcessBackend | None = None,
        bus: object | None = None,
        allowed_root: str | None = None,
    ) -> None:
        self.registry = registry
        self.mailbox_base = Path(mailbox_base)
        self.mailbox_base.mkdir(parents=True, exist_ok=True)
        self.backend = backend or SubprocessBackend()
        self.bus = bus
        self.allowed_root = allowed_root
        self._procs: dict[str, _Runtime] = {}
        self._lock = asyncio.Lock()

    def set_bus(self, bus: object) -> None:
        self.bus = bus

    # -- registration --

    def register_node(
        self,
        *,
        node_id: str,
        name: str,
        provider: str,
        role: str = "coder",
        capabilities: list[str] | None = None,
        working_directory: str = "",
    ) -> dict:
        validate_node_id(node_id)
        if working_directory:
            working_directory = validate_cwd(working_directory, self.allowed_root)
        else:
            working_directory = os.getcwd()
        try:
            identity = self.registry.register_node(
                node_id=node_id,
                name=name,
                provider=provider,
                role=role,
                capabilities=capabilities,
                working_directory=working_directory,
            )
        except DuplicateNode:
            raise
        ensure_mailbox(self.mailbox_base, node_id)
        return identity.to_dict()

    # -- lifecycle --

    async def start(self, node_id: str, prompt: str = "") -> dict:
        validate_node_id(node_id)
        try:
            node = self.registry.get_node(node_id)
        except NodeNotFound as exc:
            raise ValueError(f"Unknown node {node_id}") from exc
        async with self._lock:
            rt = self._procs.get(node_id)
            if rt and rt.proc and rt.proc.returncode is None:
                return self.status(node_id)
            self.registry.update_state(node_id, NodeState.STARTING)
            self.registry.append_event(
                node_id=node_id,
                event_type="node.starting",
                provider=node.provider,
                data={"provider": node.provider},
            )
            adapter: ProviderAdapter = get_adapter(node.provider)
            if not adapter.available():
                self.registry.update_state(node_id, NodeState.ERROR)
                self.registry.append_event(
                    node_id=node_id,
                    event_type="node.failed",
                    provider=node.provider,
                    data={"reason": "provider unavailable"},
                )
                raise RuntimeError(f"Provider {node.provider} unavailable")
            argv = adapter.build_command(prompt, node.working_directory)
            if not argv or not isinstance(argv, list):
                raise RuntimeError("Provider returned invalid argv")
            env = build_child_env()
            # never log full environment; log redacted keys only
            logger.info(
                "node.start %s provider=%s env=%s",
                node_id,
                node.provider,
                sorted(redact_env(env).keys())[:10],
            )
            try:
                proc = await self.backend.spawn(argv, node.working_directory, env)
            except Exception as exc:
                self.registry.update_state(node_id, NodeState.ERROR)
                self.registry.append_event(
                    node_id=node_id,
                    event_type="node.failed",
                    provider=node.provider,
                    data={"reason": str(exc)[:500]},
                )
                raise
            session = self.registry.start_session(node_id, proc.pid)
            self._procs[node_id] = _Runtime(
                proc=proc, session_id=session.session_id, last_seen=time.monotonic()
            )
            self.registry.update_state(node_id, NodeState.RUNNING)
            self.registry.append_event(
                node_id=node_id,
                event_type="node.started",
                session_id=session.session_id,
                provider=node.provider,
                data={"pid": proc.pid},
            )
            ensure_mailbox(self.mailbox_base, node_id)
            # Best-effort READY wait for mock provider (non-fatal for others)
            if node.provider == "mock":
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=10.0)
                    text = line.decode(errors="replace").strip()[:500]
                    if text == "XOS_NODE_READY":
                        self.registry.append_event(
                            node_id=node_id,
                            event_type="node.ready",
                            session_id=session.session_id,
                            provider=node.provider,
                            data={},
                        )
                except asyncio.TimeoutError:
                    logger.warning("mock node %s READY timeout", node_id)
            self._procs[node_id].last_seen = time.monotonic()
            return self.status(node_id)

    def status(self, node_id: str) -> dict:
        node = self.registry.get_node(node_id)
        rt = self._procs.get(node_id)
        pid = rt.proc.pid if rt and rt.proc else None
        alive = rt is not None and rt.proc is not None and rt.proc.returncode is None
        # stale PID must not be treated as active: verify liveness
        if pid and not alive:
            alive = False
            if is_pid_alive(pid):
                # PID reused by another process — treat as not ours
                pid_info = {"pid": pid, "stale": True}
            else:
                pid_info = {"pid": pid, "stale": False}
        else:
            pid_info = {"pid": pid, "stale": False}
        try:
            state = self.registry.get_state(node_id).value
        except NodeNotFound:
            state = "UNKNOWN"
        sessions = [s.to_dict() for s in self.registry.list_sessions(node_id)]
        return {
            "node_id": node_id,
            "provider": node.provider,
            "state": state,
            "alive": alive,
            "pid": pid_info["pid"],
            "pid_stale": pid_info["stale"],
            "session_id": rt.session_id if rt else None,
            "sessions": len(sessions),
            "last_seen": rt.last_seen if rt else 0.0,
        }

    async def stop(self, node_id: str) -> dict:
        validate_node_id(node_id)
        node = self.registry.get_node(node_id)
        async with self._lock:
            rt = self._procs.get(node_id)
            self.registry.update_state(node_id, NodeState.STOPPING)
            self.registry.append_event(
                node_id=node_id,
                event_type="node.stopping",
                session_id=rt.session_id if rt else None,
                provider=node.provider,
                data={},
            )
            exit_code: int | None = None
            if rt and rt.proc:
                proc = rt.proc
                try:
                    await self.backend.terminate(proc)
                    exit_code = proc.returncode
                except Exception:
                    try:
                        if proc.pid:
                            kill_process_tree(proc.pid)
                    except Exception:
                        pass
                if rt.session_id:
                    try:
                        self.registry.end_session(
                            rt.session_id, exit_code=exit_code, state="STOPPED"
                        )
                    except Exception:
                        pass
            self._procs.pop(node_id, None)
            self.registry.update_state(node_id, NodeState.STOPPED)
            self.registry.append_event(
                node_id=node_id,
                event_type="node.stopped",
                provider=node.provider,
                data={"exit_code": exit_code},
            )
            return self.status(node_id)

    async def restart(self, node_id: str, prompt: str = "") -> dict:
        try:
            await self.stop(node_id)
        except Exception:
            pass
        return await self.start(node_id, prompt)

    async def interrupt(self, node_id: str) -> dict:
        rt = self._procs.get(node_id)
        if not rt or not rt.proc or rt.proc.returncode is not None:
            raise ValueError(f"Node {node_id} has no running process")
        try:
            await self.backend.terminate(rt.proc)
        except Exception as exc:
            raise RuntimeError(f"Interrupt failed: {exc}") from exc
        node = self.registry.get_node(node_id)
        self.registry.append_event(
            node_id=node_id,
            event_type="node.interrupted",
            session_id=rt.session_id,
            provider=node.provider,
            data={},
        )
        return self.status(node_id)

    # -- messaging --

    async def send(
        self,
        node_id: str,
        message: str,
        *,
        correlation_id: str | None = None,
        act: str = "request",
        timeout: float = 30.0,
    ) -> dict:
        """Queue durable message, deliver to process stdin, await one reply line.

        Returns dict with message_id, correlation_id, response, trusted_sender.
        Provider output identity is ignored; trusted sender is always node_id.
        """
        validate_node_id(node_id)
        node = self.registry.get_node(node_id)
        rt = self._procs.get(node_id)
        if not rt or not rt.proc or rt.proc.returncode is not None:
            # mark failure if process died unexpectedly
            self.registry.update_state(node_id, NodeState.ERROR)
            self.registry.append_event(
                node_id=node_id,
                event_type="node.failed",
                session_id=rt.session_id if rt else None,
                provider=node.provider,
                data={"reason": "process not running"},
            )
            raise RuntimeError(f"Node {node_id} process not running")
        msg = build_message(
            to=node_id, body=message, sender="nexus", act=act, correlation_id=correlation_id
        )
        if int(msg.get("hops", 0)) > MAX_HOPS:
            self.registry.append_event(
                node_id=node_id,
                event_type="node.message.rejected",
                session_id=rt.session_id,
                correlation_id=msg["correlation_id"],
                provider=node.provider,
                data={"reason": "hops exceeded"},
            )
            raise ValueError("hops exceeds MAX_HOPS")
        if msg["id"] in rt.processed_ids:
            raise ValueError(f"Duplicate message {msg['id']}")
        dirs = ensure_mailbox(self.mailbox_base, node_id)
        write_message_atomic(dirs["inbox"], msg)
        self.registry.append_event(
            node_id=node_id,
            event_type="node.message.queued",
            session_id=rt.session_id,
            correlation_id=msg["correlation_id"],
            provider=node.provider,
            data={"message_id": msg["id"][:32]},
        )
        self.registry.update_state(node_id, NodeState.BUSY)
        self.registry.append_event(
            node_id=node_id,
            event_type="node.busy",
            session_id=rt.session_id,
            provider=node.provider,
            data={},
        )
        self.registry.append_event(
            node_id=node_id,
            event_type="node.message.sent",
            session_id=rt.session_id,
            correlation_id=msg["correlation_id"],
            provider=node.provider,
            data={"message_id": msg["id"][:32]},
        )
        proc = rt.proc
        assert proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write((message + "\n").encode()[:MAX_OUTPUT_BYTES])
            await proc.stdin.drain()
        except Exception as exc:
            raise RuntimeError(f"Failed to write to node stdin: {exc}") from exc
        try:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"No reply from node {node_id} within {timeout}s") from exc
        if len(raw) > MAX_OUTPUT_BYTES:
            raw = raw[:MAX_OUTPUT_BYTES]
        # stderr drained best-effort (bounded) to avoid pipe blocking
        try:
            if proc.stderr and not proc.stderr.at_eof():
                await asyncio.wait_for(proc.stderr.read(4096), timeout=0.2)
        except Exception:
            pass
        response = raw.decode(errors="replace").strip()[:4000]
        rt.processed_ids.add(msg["id"])
        mark_done(dirs["inbox"], msg["id"])
        self.registry.append_event(
            node_id=node_id,
            event_type="node.message.received",
            session_id=rt.session_id,
            correlation_id=msg["correlation_id"],
            provider=node.provider,
            data={"message_id": msg["id"][:32], "bytes": len(response)},
        )
        self.registry.append_event(
            node_id=node_id,
            event_type="node.message.processed",
            session_id=rt.session_id,
            correlation_id=msg["correlation_id"],
            provider=node.provider,
            data={"message_id": msg["id"][:32]},
        )
        self.registry.update_state(node_id, NodeState.IDLE)
        self.registry.append_event(
            node_id=node_id,
            event_type="node.idle",
            session_id=rt.session_id,
            provider=node.provider,
            data={},
        )
        rt.last_seen = time.monotonic()
        try:
            self.registry.touch_session(rt.session_id or "")
        except Exception:
            pass
        trusted = self.build_trusted_message(
            node_id=node_id,
            correlation_id=msg["correlation_id"],
            body=response,
            raw_provider_output=response,
        )
        if self.bus is not None:
            try:
                await self.bus.publish(trusted)
            except Exception:
                pass
        return {
            "message_id": msg["id"],
            "correlation_id": msg["correlation_id"],
            "response": response,
            "trusted_sender": node_id,
            "message": trusted,
        }

    def build_trusted_message(
        self,
        *,
        node_id: str,
        correlation_id: str,
        body: str,
        raw_provider_output: str = "",
    ) -> object:
        """Construct trusted bus message. Provider-supplied sender fields are ignored.

        Even if raw_provider_output contains {"sender": "navigator"}, the
        trusted sender remains node_id from NodeRegistry.
        """
        validate_node_id(node_id)
        # Attempt to detect spoof payloads for event logging, but never honor them
        spoof = False
        try:
            parsed = json.loads(raw_provider_output) if raw_provider_output.startswith("{") else None
            if isinstance(parsed, dict) and parsed.get("sender") and parsed.get("sender") != node_id:
                spoof = True
        except Exception:
            spoof = False
        if spoof:
            try:
                self.registry.append_event(
                    node_id=node_id,
                    event_type="node.spoof.blocked",
                    correlation_id=correlation_id,
                    provider="",
                    data={"note": "provider sender override ignored"},
                )
            except Exception:
                pass
        from core.bus import Message

        return Message(
            sender=node_id,
            recipient="nexus",
            type="response",
            payload={
                "data": body,
                "correlation_id": correlation_id,
                "_correlation_id": correlation_id,
            },
        )

    # -- health --

    def health(self, node_id: str) -> dict:
        st = self.status(node_id)
        rt = self._procs.get(node_id)
        return {
            "node_id": node_id,
            "alive": st["alive"],
            "pid": st["pid"],
            "state": st["state"],
            "session_id": st["session_id"],
            "last_seen_age_s": round(time.monotonic() - rt.last_seen, 2) if rt else -1,
            "exit_code": rt.proc.returncode if rt and rt.proc else None,
        }

    async def check_unexpected_exits(self) -> list[str]:
        """Detect dead processes and record node.failed. Explicit restart required (no auto-restart)."""
        failed: list[str] = []
        for node_id, rt in list(self._procs.items()):
            if rt.proc and rt.proc.returncode is not None:
                try:
                    node = self.registry.get_node(node_id)
                except Exception:
                    continue
                self.registry.update_state(node_id, NodeState.ERROR)
                self.registry.append_event(
                    node_id=node_id,
                    event_type="node.failed",
                    session_id=rt.session_id,
                    provider=node.provider,
                    data={"exit_code": rt.proc.returncode},
                )
                failed.append(node_id)
        return failed

    # -- authority bridge --

    def authority_request_for(
        self, node_id: str, *, action: str, resource: str, correlation_id: str = ""
    ) -> dict:
        """Build AuthorityRequest fields with actor=node_id (registered identity).

        Providers never choose actor; this helper enforces grant actor == execution actor.
        """
        node = self.registry.get_node(node_id)
        return {
            "actor": node.node_id,
            "principal": "navigator",
            "action": action,
            "resource": resource,
            "correlation_id": correlation_id,
            "environment": "local",
        }

    # -- recovery --

    def recover(self) -> dict:
        """Restart recovery: identities/history retained; stale PIDs not treated as alive."""
        nodes = self.registry.list_nodes()
        out = {"nodes": len(nodes), "recovered": [], "stale": []}
        for n in nodes:
            sessions = self.registry.list_sessions(n.node_id)
            # stale: last session has pid but no live runtime in this process
            last = sessions[-1] if sessions else None
            if last and last.pid and is_pid_alive(last.pid) and last.ended_at is None:
                # PID alive but not our child (restart) — treat as stale, not active
                out["stale"].append({"node_id": n.node_id, "pid": last.pid})
            pending = list_pending(self.mailbox_base / n.node_id / "inbox")
            done = list_done(self.mailbox_base / n.node_id / "inbox")
            events = self.registry.list_events(n.node_id, limit=1000)
            out["recovered"].append(
                {
                    "node_id": n.node_id,
                    "sessions": len(sessions),
                    "pending": len(pending),
                    "processed": len(done),
                    "events": len(events),
                }
            )
        return out
