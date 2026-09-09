"""Provider adapters — NodeManager depends on this abstraction, never on if/provider chains."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProviderInfo:
    name: str
    available: bool
    version: str | None
    executable: str | None
    automation_supported: bool
    reason: str = ""


class ProviderAdapter:
    """Generic provider adapter. Provider-specific behavior lives in subclasses."""

    name: str = "base"

    def available(self) -> bool:
        return False

    def version(self) -> str | None:
        return None

    def executable(self) -> str | None:
        return None

    def build_command(self, prompt: str, workdir: str) -> list[str]:
        raise NotImplementedError

    def describe(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name,
            available=self.available(),
            version=self.version(),
            executable=self.executable(),
            automation_supported=False,
            reason="base adapter",
        )


def _run_version(exe: str, args: list[str], timeout: int = 10) -> str | None:
    try:
        out = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        text = (out.stdout or out.stderr or "").strip().splitlines()
        return text[0][:120] if text else None
    except Exception:
        return None


def _default_mock_script() -> str:
    from pathlib import Path as _Path

    return str(_Path(__file__).resolve().parent.parent / "scripts" / "xos_mock_node.py")


class MockProvider(ProviderAdapter):
    """Deterministic test worker — scripts/xos_mock_node.py. No network, no subscription."""

    name = "mock"

    def __init__(self, script_path: str | None = None) -> None:
        self.script_path = script_path or _default_mock_script()

    def available(self) -> bool:
        from pathlib import Path

        return Path(self.script_path).exists()

    def version(self) -> str | None:
        return "mock-0.1.0"

    def executable(self) -> str | None:
        import sys

        return sys.executable

    def build_command(self, prompt: str, workdir: str) -> list[str]:  # noqa: ARG002
        import sys

        return [sys.executable, self.script_path]

    def describe(self) -> ProviderInfo:
        return ProviderInfo(
            name=self.name,
            available=self.available(),
            version=self.version(),
            executable=self.executable(),
            automation_supported=True,
            reason="deterministic mock worker",
        )


class OpenCodeProvider(ProviderAdapter):
    """OpenCode CLI — verified: `opencode run [message..]` with --format json."""

    name = "opencode"

    def available(self) -> bool:
        return shutil.which("opencode") is not None

    def version(self) -> str | None:
        exe = shutil.which("opencode")
        if not exe:
            return None
        return _run_version(exe, ["--version"])

    def executable(self) -> str | None:
        return shutil.which("opencode")

    def build_command(self, prompt: str, workdir: str) -> list[str]:
        exe = self.executable()
        if not exe:
            raise RuntimeError("opencode executable not found")
        # Verified flags: run [message..] --format json --dir <dir>
        return [exe, "run", prompt, "--format", "json", "--dir", workdir]

    def describe(self) -> ProviderInfo:
        avail = self.available()
        return ProviderInfo(
            name=self.name,
            available=avail,
            version=self.version(),
            executable=self.executable(),
            automation_supported=avail,
            reason="opencode run --format json" if avail else "opencode not installed",
        )


class CodexProvider(ProviderAdapter):
    """OpenAI Codex CLI skeleton — only enabled if verified locally."""

    name = "codex"

    def available(self) -> bool:
        return shutil.which("codex") is not None

    def version(self) -> str | None:
        exe = shutil.which("codex")
        if not exe:
            return None
        return _run_version(exe, ["--version"])

    def executable(self) -> str | None:
        return shutil.which("codex")

    def build_command(self, prompt: str, workdir: str) -> list[str]:  # noqa: ARG002
        exe = self.executable()
        if not exe:
            raise RuntimeError("codex executable not found")
        return [exe, "--help"]

    def describe(self) -> ProviderInfo:
        avail = self.available()
        return ProviderInfo(
            name=self.name,
            available=avail,
            version=self.version(),
            executable=self.executable(),
            automation_supported=False,
            reason="skeleton: automation not yet verified" if avail else "codex not installed",
        )


class ClaudeProvider(ProviderAdapter):
    """Claude Code CLI — verified: -p/--print for non-interactive output."""

    name = "claude"

    def available(self) -> bool:
        return shutil.which("claude") is not None

    def version(self) -> str | None:
        exe = shutil.which("claude")
        if not exe:
            return None
        return _run_version(exe, ["--version"])

    def executable(self) -> str | None:
        return shutil.which("claude")

    def build_command(self, prompt: str, workdir: str) -> list[str]:  # noqa: ARG002
        exe = self.executable()
        if not exe:
            raise RuntimeError("claude executable not found")
        return [exe, "-p", prompt]

    def describe(self) -> ProviderInfo:
        avail = self.available()
        return ProviderInfo(
            name=self.name,
            available=avail,
            version=self.version(),
            executable=self.executable(),
            automation_supported=avail,
            reason="claude -p verified" if avail else "claude not installed",
        )


class GeminiProvider(ProviderAdapter):
    """Gemini CLI skeleton — only enabled if verified locally."""

    name = "gemini"

    def available(self) -> bool:
        return shutil.which("gemini") is not None

    def version(self) -> str | None:
        exe = shutil.which("gemini")
        if not exe:
            return None
        return _run_version(exe, ["--version"])

    def executable(self) -> str | None:
        return shutil.which("gemini")

    def build_command(self, prompt: str, workdir: str) -> list[str]:  # noqa: ARG002
        exe = self.executable()
        if not exe:
            raise RuntimeError("gemini executable not found")
        return [exe, "--help"]

    def describe(self) -> ProviderInfo:
        avail = self.available()
        return ProviderInfo(
            name=self.name,
            available=avail,
            version=self.version(),
            executable=self.executable(),
            automation_supported=False,
            reason="skeleton: automation not yet verified" if avail else "gemini not installed",
        )


def discover_providers() -> dict[str, ProviderInfo]:
    """Detect installed providers via shutil.which + safe --version. No secrets persisted."""
    adapters: list[ProviderAdapter] = [
        OpenCodeProvider(),
        CodexProvider(),
        ClaudeProvider(),
        GeminiProvider(),
        MockProvider(),
    ]
    return {a.name: a.describe() for a in adapters}


def get_adapter(name: str, mock_script: str | None = None) -> ProviderAdapter:
    mapping = {
        "mock": MockProvider(mock_script or _default_mock_script()),
        "opencode": OpenCodeProvider(),
        "codex": CodexProvider(),
        "claude": ClaudeProvider(),
        "gemini": GeminiProvider(),
    }
    if name not in mapping:
        raise ValueError(f"Unknown provider {name!r}")
    return mapping[name]
