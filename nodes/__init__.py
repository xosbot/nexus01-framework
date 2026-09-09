"""XOS Nodes Runtime — durable workers around external AI CLIs.

External provider intelligence is replaceable.

XOS owns identity.
NEXUS owns coordination.
XOS Control owns authority.
NodeManager owns process lifecycle.
Evidence remains durable.
"""

from nodes.identity import NodeIdentity, NodeSession, NodeState
from nodes.manager import NodeManager
from nodes.registry import NodeRegistry

__all__ = ["NodeIdentity", "NodeManager", "NodeRegistry", "NodeSession", "NodeState"]
