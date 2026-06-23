"""Tool availability checks — verify OSINT tools are installed before routing to them."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ToolStatus:
    name: str
    available: bool
    install_command: str = ""
    error: str = ""


@dataclass
class ToolAvailability:
    tools: dict[str, ToolStatus] = field(default_factory=dict)

    def is_available(self, tool_name: str) -> bool:
        status = self.tools.get(tool_name)
        return status is not None and status.available

    def get_unavailable_tools(self) -> list[ToolStatus]:
        return [t for t in self.tools.values() if not t.available]

    def to_dict(self) -> dict:
        return {
            name: {
                "available": t.available,
                "install_command": t.install_command,
                "error": t.error,
            }
            for name, t in self.tools.items()
        }


def check_tool_availability() -> ToolAvailability:
    availability = ToolAvailability()

    tool_checks = [
        ("sherlock", "sherlock", "pip install sherlock-project"),
        ("holehe", "holehe", "pip install holehe"),
        ("theharvester", "theHarvester", "pip install theHarvester"),
        ("onionsearch", "onionsearch", "pip install onionsearch"),
    ]

    for tool_name, binary, install_cmd in tool_checks:
        path = shutil.which(binary)
        if path:
            availability.tools[tool_name] = ToolStatus(
                name=tool_name,
                available=True,
            )
            logger.info("Tool available: %s at %s", tool_name, path)
        else:
            availability.tools[tool_name] = ToolStatus(
                name=tool_name,
                available=False,
                install_command=install_cmd,
                error=f"{binary} not found in PATH",
            )
            logger.warning("Tool not available: %s (install with: %s)", tool_name, install_cmd)

    builtin_tools = ["web_search", "crt_sh", "hibp", "builtin_username", "builtin_email", "builtin_domain"]
    for tool_name in builtin_tools:
        availability.tools[tool_name] = ToolStatus(
            name=tool_name,
            available=True,
        )

    return availability


_tool_availability: ToolAvailability | None = None


def get_tool_availability() -> ToolAvailability:
    global _tool_availability
    if _tool_availability is None:
        _tool_availability = check_tool_availability()
    return _tool_availability


def refresh_tool_availability() -> ToolAvailability:
    global _tool_availability
    _tool_availability = check_tool_availability()
    return _tool_availability
