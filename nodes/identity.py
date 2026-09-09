"""XOS Node domain — identity, session, state.

NodeIdentity = persistent definition (owned by XOS, survives restart).
NodeSession  = one runtime process/session.
NodeState    = current runtime status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class NodeState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    IDLE = "IDLE"
    BUSY = "BUSY"
    WAITING = "WAITING"
    ERROR = "ERROR"
    STOPPING = "STOPPING"


_NODE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{2,63}$")


def validate_node_id(node_id: str) -> str:
    """Validate a node ID. XOS generates/validates IDs; providers never choose trusted IDs."""
    if not isinstance(node_id, str) or not _NODE_ID_RE.match(node_id):
        raise ValueError(
            f"Invalid node_id {node_id!r}: must match [a-z0-9_], 3-64 chars, start alnum"
        )
    return node_id


def generate_node_id(prefix: str = "node", suffix: str = "") -> str:
    """Generate a node ID stub (caller should ensure uniqueness via registry)."""
    import uuid

    base = f"{prefix}_{suffix}_" if suffix else f"{prefix}_"
    candidate = f"{base}{uuid.uuid4().hex[:8]}"
    return validate_node_id(candidate)


@dataclass(frozen=True)
class NodeIdentity:
    node_id: str
    name: str
    provider: str
    role: str
    capabilities: list[str] = field(default_factory=list)
    working_directory: str = ""
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "provider": self.provider,
            "role": self.role,
            "capabilities": list(self.capabilities),
            "working_directory": self.working_directory,
            "created_at": self.created_at,
        }


@dataclass
class NodeSession:
    session_id: str
    node_id: str
    pid: int | None
    state: NodeState
    started_at: str
    ended_at: str | None = None
    exit_code: int | None = None
    last_seen_at: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "node_id": self.node_id,
            "pid": self.pid,
            "state": self.state.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "last_seen_at": self.last_seen_at,
        }
