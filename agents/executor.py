import subprocess
import asyncio
from pathlib import Path
from agents.base import BaseAgent, AgentStatus
from core.bus import Message
from core.cold_mode import ColdMode
from core.memory import Memory
from core.llm import OllamaClient

class ExecutorAgent(BaseAgent):
    PERMISSIONS = {"READ": 0, "WRITE": 1, "EXECUTE": 2, "ADMIN": 3}

    def __init__(self, llm: OllamaClient, memory: Memory, cold_mode: ColdMode):
        super().__init__("executor", llm, memory)
        self.cold_mode = cold_mode
        self.tools = {
            "run_command": self._run_command,
            "read_file": self._read_file,
            "write_file": self._write_file,
        }

    async def on_message(self, message: Message) -> dict:
        action = message.payload.get("action", "")
        params = message.payload.get("params", {})
        permission_level = message.payload.get("permission", "READ")
        required_level = self.PERMISSIONS.get(permission_level, 0)

        context = {
            "confidence": message.payload.get("confidence", 0.8),
            "reversible": action != "delete",
            "source_reliability": 0.8,
            "fallback_script": params.get("fallback"),
            "numeric_values": [],
        }

        if self.cold_mode.should_block(context):
            reasons = self.cold_mode.get_failure_reasons(context)
            return {"status": "blocked", "reasons": reasons, "action": action}

        self.memory.save_conversation(self.name, "user", f"Execute: {action}")

        result = await self.act(action, **params) if action in self.tools else {"error": f"Unknown action: {action}"}

        self.memory.save_conversation(self.name, "assistant", str(result))
        return result

    async def _run_command(self, cmd: str, timeout: int = 30) -> dict:
        dangerous = ["rm -rf /", "chmod 777", "mkfs", "> /dev/sda", ":(){ :|:& };:"]
        if any(d in cmd for d in dangerous):
            return {"error": "Command blocked for safety", "exit_code": -1}
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return {
                "stdout": stdout.decode(),
                "stderr": stderr.decode(),
                "exit_code": proc.returncode
            }
        except asyncio.TimeoutError:
            return {"error": "Command timed out", "exit_code": -1}

    async def _read_file(self, path: str) -> dict:
        try:
            content = Path(path).read_text(encoding="utf-8")
            return {"content": content, "path": path}
        except Exception as e:
            return {"error": str(e)}

    async def _write_file(self, path: str, content: str) -> dict:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                backup = p.with_suffix(p.suffix + ".bak")
                backup.write_text(p.read_text())
            p.write_text(content, encoding="utf-8")
            return {"status": "written", "path": path, "backup": str(backup) if p.exists() else None}
        except Exception as e:
            return {"error": str(e)}
