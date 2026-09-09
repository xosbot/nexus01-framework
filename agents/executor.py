"""Executor agent — runs commands in Docker sandbox with security gates."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from core.bus import Message
from core.cold_mode import ColdMode
from core.resilience import with_retry
from tools.shell_exec import _is_safe_command, run_command

from agents.base import BaseAgent

logger = logging.getLogger(__name__)

RESTRICTED_PATHS = ["/etc", "/proc", "/sys", "/dev", "/boot", "/root/.ssh"]
WORKSPACE = Path(__file__).parent.parent / "workspace"


class ExecutorAgent(BaseAgent):
    PERMISSIONS = {"READ": 0, "WRITE": 1, "EXECUTE": 2, "ADMIN": 3}

    def __init__(self, llm, memory, cold_mode: ColdMode, rag=None, sandbox=None, authority=None):
        super().__init__("executor", llm, memory, rag)
        self.cold_mode = cold_mode
        self._sandbox = sandbox
        self.authority = authority
        self.tools = {
            "run_command": self._run_command,
            "read_file": self._read_file,
            "write_file": self._write_file,
        }
        WORKSPACE.mkdir(parents=True, exist_ok=True)

    async def on_message(self, message: Message) -> dict:
        import time
        action = message.payload.get("action", "")
        params = message.payload.get("params", {})
        permission_level = message.payload.get("permission", "READ")
        grant_id = message.payload.get("grant_id") or message.payload.get("authority_grant_id") or ""
        request_id = message.payload.get("request_id") or message.payload.get("authority_request_id") or ""

        consequential = action in {"run_command", "write_file", "delete", "exec"}
        # XOS enabled: every consequential action requires a valid grant — do NOT key on permission
        # Trust source: message.sender is runtime actor; principal from grant's request (not payload)
        if self.authority is not None and consequential:
            if not grant_id:
                return {"status": "blocked", "reasons": ["XOS grant required: no grant_id"], "action": action}

            # Trust source for actor is message.sender (runtime), NOT payload actor
            # Documented: MessageBus sender is current trust source; payload actor must not override
            expected_actor = message.sender
            # Principal must be derived from the grant's backing request, not caller payload (prevent widening)
            try:
                g = self.authority.get_grant(grant_id)
                req = self.authority.get_request(g.request_id)
                expected_principal = req.principal
                # Also enforce that request's actor matches message.sender — stolen grant fails
                if req.actor != expected_actor:
                    return {"status": "blocked", "reasons": [f"XOS grant actor mismatch: grant actor {req.actor} vs sender {expected_actor}"], "action": action}
            except Exception as exc:
                return {"status": "blocked", "reasons": [f"XOS grant lookup failed: {exc}"], "action": action}

            # Resolve resource for scope check
            raw_resource = params.get("path") or params.get("cmd") or params.get("resource") or ""
            candidates = [raw_resource, f"shell:{raw_resource}"] if raw_resource else [""]
            matched_resource = None
            last_reason = ""
            for cand in candidates:
                ok, reason = self.authority.verify_grant(grant_id, action, cand, actor=expected_actor, principal=expected_principal)
                if ok:
                    matched_resource = cand
                    break
                last_reason = reason
            if matched_resource is None:
                return {"status": "blocked", "reasons": [f"XOS grant invalid: {last_reason}"], "action": action}

            # ColdMode must pass BEFORE consumption (canonical lifecycle)
            fallback_script = params.get("fallback") or params.get("fallback_script") or message.payload.get("fallback_script") or message.payload.get("fallback")
            context = ColdMode.build_context(
                action=action,
                permission=permission_level,
                confidence=message.payload.get("confidence"),
                fallback_script=fallback_script,
                numeric_values=message.payload.get("numeric_values", []),
            )
            if self.cold_mode.should_block(context):
                reasons = self.cold_mode.get_failure_reasons(context)
                return {"status": "blocked", "reasons": reasons, "action": action}

            # Canonical execution: atomic begin_execution (consume+grant.consumed+execution.started) -> tool -> succeeded/failed
            clean_params = {k: v for k, v in params.items() if k not in {"fallback", "fallback_script", "resource", "actor", "principal", "actor_id"}}
            async def _tool_executor():
                return await self.act(action, **clean_params) if action in self.tools else {"error": f"Unknown action: {action}"}

            start_mono = time.monotonic()
            try:
                result = await self.authority.execute_with_grant(
                    grant_id,
                    action=action,
                    resource=matched_resource,
                    executor=_tool_executor,
                    actor=expected_actor,
                    principal=expected_principal,
                )
            except Exception as exc:
                msg = str(exc)
                # AuthorityBusy or grant failures → blocked (fail closed)
                if "Grant" in msg or "grant" in msg or "Scope" in msg or "Expired" in msg or "Consumed" in msg or "Busy" in msg or "busy" in msg:
                    return {"status": "blocked", "reasons": [f"XOS grant failed: {exc}"], "action": action}
                logger.error("execution failed for grant %s: %s", grant_id, exc)
                return {"status": "error", "error": str(exc), "action": action, "evidence_status": "FAILED"}
            duration_ms = int((time.monotonic() - start_mono) * 1000)

            self.memory.save_conversation(self.name, "user", f"Execute: {action}")
            self.memory.save_conversation(self.name, "assistant", str(result))
            return result

        # Non-consequential or no authority: fallback to original ColdMode + act
        fallback_script = params.get("fallback") or params.get("fallback_script") or message.payload.get("fallback_script") or message.payload.get("fallback")
        context = ColdMode.build_context(
            action=action,
            permission=permission_level,
            confidence=message.payload.get("confidence"),
            fallback_script=fallback_script,
            numeric_values=message.payload.get("numeric_values", []),
        )
        if self.cold_mode.should_block(context):
            reasons = self.cold_mode.get_failure_reasons(context)
            return {"status": "blocked", "reasons": reasons, "action": action}

        self.memory.save_conversation(self.name, "user", f"Execute: {action}")
        start = time.monotonic()
        clean_params = {k: v for k, v in params.items() if k not in {"fallback", "fallback_script", "resource", "actor", "principal"}}
        result = await self.act(action, **clean_params) if action in self.tools else {"error": f"Unknown action: {action}"}
        duration_ms = int((time.monotonic() - start) * 1000)
        self.memory.save_conversation(self.name, "assistant", str(result))
        # Non-XOS evidence (best effort)
        if self.authority is not None and consequential:
            try:
                success = not (isinstance(result, dict) and result.get("error"))
                outcome = str(result)[:2000] if success else str(result.get("error", ""))[:2000]
                self.authority.record_evidence(
                    request_id=request_id or grant_id or "direct",
                    grant_id=grant_id,
                    actor_id=expected_actor or message.payload.get("user_id") or "executor",
                    action=action,
                    resource=params.get("path") or params.get("cmd") or "",
                    input_data=params,
                    outcome=outcome,
                    success=success,
                    duration_ms=duration_ms,
                )
            except Exception as exc:
                logger.warning("evidence persistence failed (reconciliation required) for %s: %s", request_id, exc)

        return result

    async def _run_command(self, cmd: str, timeout: int = 30) -> dict:
        safe, reason = _is_safe_command(cmd)
        if not safe:
            return {"error": reason, "exit_code": -1}

        if self._sandbox:
            try:
                async def _sandbox_call():
                    return await self._sandbox.run_command(cmd)
                result = await asyncio.wait_for(
                    with_retry(_sandbox_call, max_attempts=2, base_delay=0.5),
                    timeout=timeout,
                )
                return result.to_dict()
            except asyncio.TimeoutError:
                logger.warning("Sandbox exec timed out: %s", cmd[:80])
                return {"error": "Command timed out", "exit_code": -124, "cmd": cmd}
            except Exception as exc:
                logger.warning("Sandbox failed, falling back: %s", exc)
                return await run_command(cmd, timeout=timeout, sandbox=False)

        return await run_command(cmd, timeout=timeout, sandbox=True)

    def _validate_path(self, path: str) -> tuple[bool, str]:
        try:
            p = Path(path).resolve()
        except Exception:
            return False, "Invalid path"

        for restricted in RESTRICTED_PATHS:
            if str(p).startswith(restricted):
                return False, f"Access to {restricted} is restricted"

        return True, ""

    async def _read_file(self, path: str) -> dict:
        safe, reason = self._validate_path(path)
        if not safe:
            return {"error": reason}
        try:
            content = Path(path).read_text(encoding="utf-8")
            return {"content": content[:10000], "path": path}
        except Exception as e:
            return {"error": str(e)}

    async def _write_file(self, path: str, content: str) -> dict:
        safe, reason = self._validate_path(path)
        if not safe:
            return {"error": reason}
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                backup = p.with_suffix(p.suffix + ".bak")
                backup.write_text(p.read_text())
            p.write_text(content, encoding="utf-8")
            return {"status": "written", "path": path}
        except Exception as e:
            return {"error": str(e)}
