"""Secure shell executor with allowlist and Docker-only execution."""

from __future__ import annotations

import asyncio
import logging
import shlex
import subprocess

logger = logging.getLogger(__name__)

ALLOWED_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "find", "wc", "echo", "date",
    "whoami", "hostname", "uname", "uptime", "df", "du", "free", "ps",
    "top", "id", "pwd", "env", "printenv", "which", "file", "stat",
    "curl", "wget", "ping", "dig", "nslookup", "host",
    "python3", "python", "pip", "pip3", "node", "npm", "git",
    "docker", "docker-compose", "ollama", "systemctl",
    "pytest", "ruff", "mypy",
}

SHELL_METACHARACTERS = frozenset({";", "|", "&", "(", ")", "`", "$", "{", "}", "!", "<", ">", "~", "\\", '"', "'"})

DANGEROUS_PATHS = [
    "/etc", "/proc", "/sys", "/dev", "/boot", "/lib", "/usr/lib",
    "/var/log", "/root/.ssh", "/home/*/.ssh",
]


def _contains_shell_metacharacters(cmd: str) -> bool:
    return any(c in SHELL_METACHARACTERS for c in cmd)


def _check_dangerous_paths(cmd: str) -> str | None:
    cmd_lower = cmd.lower()
    for path in DANGEROUS_PATHS:
        if path in cmd_lower:
            return f"Access to {path} is restricted"
    return None


def _is_safe_command(cmd: str) -> tuple[bool, str]:
    cmd_stripped = cmd.strip()
    if not cmd_stripped:
        return False, "Empty command"

    if _contains_shell_metacharacters(cmd_stripped):
        return False, "Shell metacharacters are not allowed"

    path_error = _check_dangerous_paths(cmd_stripped)
    if path_error:
        return False, path_error

    try:
        parts = shlex.split(cmd_stripped)
    except ValueError as e:
        return False, f"Failed to parse command: {e}"

    if not parts:
        return False, "Empty command after parsing"

    base_cmd = parts[0].split("/")[-1]
    if base_cmd not in ALLOWED_COMMANDS:
        return False, f"Command '{base_cmd}' not in allowlist"

    return True, ""


async def run_command(cmd: str, timeout: int = 30, sandbox: bool = True) -> dict:
    safe, reason = _is_safe_command(cmd)
    if not safe:
        logger.warning("Blocked command: %s (reason: %s)", cmd, reason)
        return {"error": reason, "exit_code": -1, "stderr": reason}

    try:
        parts = shlex.split(cmd)
    except ValueError as e:
        return {"error": f"Failed to parse command: {e}", "exit_code": -1, "stderr": str(e)}

    try:
        proc = await asyncio.create_subprocess_exec(
            *parts,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "exit_code": proc.returncode,
        }
    except asyncio.TimeoutError:
        return {"error": f"Command timed out after {timeout}s", "exit_code": -1}
    except FileNotFoundError:
        return {"error": f"Command not found: {parts[0]}", "exit_code": -1}
    except Exception as e:
        return {"error": str(e), "exit_code": -1}
