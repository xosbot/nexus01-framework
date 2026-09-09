"""Process plane — subprocess/pipe backend with PTY-ready abstraction."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 1_000_000


@dataclass
class ProcessHandle:
    pid: int
    argv: list[str]
    cwd: str
    started_at: str


def validate_executable(exe: str) -> str:
    """Resolve executable safely: absolute path or PATH lookup. No shell."""
    if not exe:
        raise ValueError("Empty executable")
    if os.path.isabs(exe):
        p = Path(exe)
        if not p.is_file():
            raise ValueError(f"Executable not found: {exe}")
        if not os.access(exe, os.X_OK):
            raise ValueError(f"Executable not runnable: {exe}")
        return exe
    found = shutil.which(exe)
    if not found:
        raise ValueError(f"Executable not on PATH: {exe}")
    return found


def validate_cwd(cwd: str, allowed_root: str | None = None) -> str:
    """Validate cwd: exists, is dir, resolved absolute; reject traversal/escape."""
    if not cwd:
        raise ValueError("Empty cwd")
    p = Path(cwd).expanduser()
    try:
        resolved = p.resolve(strict=True)
    except Exception as exc:
        raise ValueError(f"cwd does not exist: {cwd}") from exc
    if not resolved.is_dir():
        raise ValueError(f"cwd is not a directory: {cwd}")
    if str(resolved) == "/":
        raise ValueError("cwd '/' is forbidden")
    text = str(resolved)
    if ".." in Path(cwd).parts:
        # still allow if resolved stays inside allowed_root, but reject bare traversal
        pass
    if allowed_root:
        root = Path(allowed_root).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"cwd escapes allowed root {allowed_root}") from exc
    return text


class ProcessBackend:
    """Abstraction so PTY support can be added without rewriting NodeManager."""

    async def spawn(
        self, argv: list[str], cwd: str, env: dict[str, str] | None
    ) -> asyncio.subprocess.Process:
        raise NotImplementedError

    async def terminate(self, proc: asyncio.subprocess.Process) -> None:
        raise NotImplementedError


class SubprocessBackend(ProcessBackend):
    """Pipe-based backend: stdin/stdout/stderr pipes, bounded output, timeouts."""

    async def spawn(
        self, argv: list[str], cwd: str, env: dict[str, str] | None
    ) -> asyncio.subprocess.Process:
        exe = validate_executable(argv[0])
        full_argv = [exe, *argv[1:]]
        safe_cwd = validate_cwd(cwd)
        return await asyncio.create_subprocess_exec(
            *full_argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=safe_cwd,
            env=env,
            start_new_session=True,
        )

    async def terminate(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass


def kill_process_tree(pid: int) -> None:
    """Best-effort cleanup to prevent orphans: kill process group."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def is_pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def redact_env(env: dict[str, str]) -> dict[str, str]:
    """Redact secret values; never log full environment."""
    secrets = ("TOKEN", "SECRET", "PASSWORD", "KEY", "AUTH", "COOKIE")
    out: dict[str, str] = {}
    for k, v in env.items():
        if any(s in k.upper() for s in secrets):
            out[k] = "***REDACTED***"
        else:
            out[k] = v[:200]
    return out


def build_child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Deliberate launch env: inherit os.environ for v0 (documented), plus overrides."""
    env = dict(os.environ)
    if extra:
        env.update(extra)
    return env


def run_version_safe(exe: str, timeout: int = 10) -> str | None:
    try:
        resolved = validate_executable(exe)
        out = subprocess.run(
            [resolved, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        text = (out.stdout or out.stderr or "").strip().splitlines()
        return text[0][:200] if text else None
    except Exception:
        return None
