from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChannelKind(str, Enum):
    CLI = "cli"
    WEB = "web"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    DISCORD = "discord"
    SLACK = "slack"
    SIGNAL = "signal"
    TEAMS = "teams"


@dataclass
class InboundMessage:
    channel: ChannelKind
    session_id: str
    text: str
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GatewayResponse:
    text: str
    requires_approval: bool = False
    approval_id: str = ""
    route: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.raw.get("status") not in ("error", "blocked")
