"""Docker sandbox for executor agent — isolated, resource-limited command execution."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "python:3.12-slim"
DEFAULT_CPU_LIMIT = 0.5
DEFAULT_MEMORY_LIMIT = "256m"
DEFAULT_TIMEOUT = 30
DEFAULT_TMP_SIZE = "50m"


@dataclass
class SandboxConfig:
    image: str = DEFAULT_IMAGE
    cpu_limit: float = DEFAULT_CPU_LIMIT
    memory_limit: str = DEFAULT_MEMORY_LIMIT
    timeout_seconds: int = DEFAULT_TIMEOUT
    network_disabled: bool = True
    read_only_root: bool = True
    tmp_size: str = DEFAULT_TMP_SIZE
    max_output_chars: int = 10_000


@dataclass
class SandboxResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    container_id: str = ""
    duration_ms: int = 0

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "stdout": self.stdout[:10000],
            "stderr": self.stderr[:10000],
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "success": self.success,
        }


class DockerSandbox:
    """Manages isolated Docker containers for agent code execution.

    Each execution spins up a disposable container with strict resource limits.
    Network is disabled, filesystem is read-only (except /tmp), and a hard
    timeout kills the container if execution hangs.
    """

    def __init__(self, config: SandboxConfig | None = None):
        self.config = config or SandboxConfig()
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import docker
                self._client = docker.from_env()
                self._client.ping()
            except Exception as exc:
                raise RuntimeError(f"Docker not available: {exc}") from exc
        return self._client

    async def execute(self, code: str, language: str = "python") -> SandboxResult:
        if language not in ("python", "bash"):
            return SandboxResult(stderr=f"Unsupported language: {language}", exit_code=-1)

        cmd = ["python3", "-c", code] if language == "python" else ["bash", "-c", code]
        return await self._run_container(cmd)

    async def run_command(self, command: str) -> SandboxResult:
        return await self._run_container(["bash", "-c", command])

    async def _run_container(self, cmd: list[str]) -> SandboxResult:
        start = time.monotonic()
        container = None
        client = self._get_client()

        try:
            nano_cpus = int(self.config.cpu_limit * 1e9)
            tmpfs = {"/tmp": f"size={self.config.tmp_size}"}

            container = await asyncio.to_thread(
                client.containers.run,
                image=self.config.image,
                command=cmd,
                detach=True,
                nano_cpus=nano_cpus,
                mem_limit=self.config.memory_limit,
                network_disabled=self.config.network_disabled,
                read_only=self.config.read_only_root,
                tmpfs=tmpfs,
                remove=False,
            )

            try:
                result = await asyncio.to_thread(
                    container.wait, timeout=self.config.timeout_seconds
                )
                exit_code = result.get("StatusCode", -1)
            except Exception:
                exit_code = -124
                try:
                    await asyncio.to_thread(container.kill)
                except Exception:
                    pass

            logs = await asyncio.to_thread(container.logs)
            stdout = logs.decode("utf-8", errors="replace")[:self.config.max_output_chars]

            duration = int((time.monotonic() - start) * 1000)
            timed_out = exit_code == -124

            logger.info("Sandbox exec: exit=%d, timeout=%s, %dms", exit_code, timed_out, duration)

            return SandboxResult(
                stdout=stdout if exit_code == 0 else "",
                stderr=stdout if exit_code != 0 else "",
                exit_code=exit_code,
                timed_out=timed_out,
                container_id=container.id[:12] if container else "",
                duration_ms=duration,
            )

        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            logger.error("Sandbox error: %s", exc)
            return SandboxResult(stderr=str(exc), exit_code=-1, duration_ms=duration)

        finally:
            if container:
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except Exception:
                    pass

    def is_available(self) -> bool:
        try:
            client = self._get_client()
            return client is not None
        except Exception:
            return False
