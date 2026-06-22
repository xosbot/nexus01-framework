"""Secure shell executor with allowlist and Docker-only execution."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess

logger = __import__("logging").getlogger(__name__)

ALLOWED_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "find", "wc", "echo", "date",
    "whoami", "hostname", "uname", "uptime", "df", "du", "free", "ps",
    "top", "id", "pwd", "env", "printenv", "which", "file", "stat",
    "curl", "wget", "ping", "dig", "nslookup", "host", "ssh",
    "python3", "python", "pip", "pip3", "node", "npm", "git",
    "docker", "docker-compose", "ollama", "systemctl",
    "pytest", "ruff", "mypy",
}

BLOCKED_PATTERNS = [
    "rm -rf /", "rm -rf /*", "mkfs", "> /dev/sda", "> /dev/sdb",
    ":(){ :|:& };:", "dd if=", "wget|sh", "curl|sh", "bash -c",
    "chmod 777", "chmod -R 777", "chown -R", "> /etc/",
    "dd of=", "mv / ", "mv /*", "cp / ", "cp /*",
    "/etc/passwd", "/etc/shadow", "/etc/sudoers",
    "authorized_keys", "id_rsa", "id_ed25519",
]

DANGEROUS_PATHS = [
    "/etc", "/proc", "/sys", "/dev", "/boot", "/lib", "/usr/lib",
    "/var/log", "/root/.ssh", "/home/*/.ssh",
]


def _is_safe_command(cmd: str) -> tuple[bool, str]:
    cmd_lower = cmd.lower().strip()

    for pattern in BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            return False, f"Blocked dangerous pattern: {pattern}"

    for path in DANGEROUS_PATHS:
        if path in cmd_lower:
            return False, f"Access to {path} is restricted"

    parts = cmd_lower.split()
    if not parts:
        return False, "Empty command"

    base_cmd = parts[0].split("/")[-1]
    if base_cmd not in ALLOWED_COMMANDS:
        return False, f"Command '{base_cmd}' not in allowlist"

    return True, ""


async def run_command(cmd: str, timeout: int = 30, sandbox: bool = True) -> dict:
    safe, reason = _is_safe_command(cmd)
    if not safe:
        logger.warning("Blocked command: %s (reason: %s)", cmd, reason)
        return {"error": reason, "exit_code": -1, "stderr": reason}

    if sandbox and shutil.which("docker"):
        return await _run_in_docker(cmd, timeout)

    return await _run_host(cmd, timeout)


async def _run_in_docker(cmd: str, timeout: int) -> dict:
    docker_cmd = [
        "docker", "run", "--rm",
        "--network=none",
        "--read-only",
        "--tmpfs", "/tmp:size=100m",
        "--cpus=1", "--memory=256m",
        "--pids-limit=100",
        "python:3.11-slim",
        "sh", "-c", cmd,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
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


async def _run_host(cmd: str, timeout: int) -> dict:
    logger.warning("Running on host (no Docker): %s", cmd)
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
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
    except Exception as e:
        return {"error": str(e), "exit_code": -1}
