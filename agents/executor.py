"""Executor agent — runs commands in Docker sandbox with security gates."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from agents.base import BaseAgent
from core.bus import Message
from core.cold_mode import ColdMode
from core.resilience import with_retry
from tools.shell_exec import run_command, _is_safe_command

logger = logging.getLogger(__name__)

RESTRICTED_PATHS = ["/etc", "/proc", "/sys", "/dev", "/boot", "/root/.ssh"]
WORKSPACE = Path(__file__).parent.parent / "workspace"


class ExecutorAgent(BaseAgent):
    PERMISSIONS = {"READ": 0, "WRITE": 1, "EXECUTE": 2, "ADMIN": 3}

    def __init__(self, llm, memory, cold_mode: ColdMode, rag=None, sandbox=None):
        super().__init__("executor", llm, memory, rag)
        self.cold_mode = cold_mode
        self._sandbox = sandbox
        self.tools = {
            "run_command": self._run_command,
            "read_file": self._read_file,
            "write_file": self._write_file,
        }
        WORKSPACE.mkdir(parents=True, exist_ok=True)

    async def on_message(self, message: Message) -> dict:
        action = message.payload.get("action", "")
        params = message.payload.get("params", {})
        permission_level = message.payload.get("permission", "READ")

        context = ColdMode.build_context(
            action=action,
            permission=permission_level,
            confidence=message.payload.get("confidence"),
            fallback_script=params.get("fallback"),
            numeric_values=message.payload.get("numeric_values", []),
        )

        if self.cold_mode.should_block(context):
            reasons = self.cold_mode.get_failure_reasons(context)
            return {"status": "blocked", "reasons": reasons, "action": action}

        self.memory.save_conversation(self.name, "user", f"Execute: {action}")

        result = await self.act(action, **params) if action in self.tools else {"error": f"Unknown action: {action}"}

        self.memory.save_conversation(self.name, "assistant", str(result))
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
