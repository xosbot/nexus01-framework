"""Executor agent — runs commands in Docker sandbox with security gates."""

from __future__ import annotations

from pathlib import Path
from agents.base import BaseAgent
from core.bus import Message
from core.cold_mode import ColdMode
from tools.shell_exec import run_command, _is_safe_command

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
        if self._sandbox:
            try:
                result = await self._sandbox.run_command(cmd)
                return result.to_dict()
            except Exception as exc:
                return {"error": f"Sandbox error: {exc}", "exit_code": -1}

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
