"""XOS Policy engine — pure evaluation, no IO.

Policy decides whether an AuthorityRequest requires human approval,
is auto-allowed, or is denied. Keep this deterministic and testable;
no LLM calls here.

v0 rules:
- READ actions are auto-allowed (no human gate).
- EXECUTE / WRITE / destructive actions require approval unless a
  valid scoped grant is presented (checked by AuthorityService).
- CONFIRM mode forces approval for everything beyond READ.
"""

from __future__ import annotations

from dataclasses import dataclass

READ_ACTIONS = frozenset({"read_file", "list", "query", "rag_query", "search", "read"})
EXECUTE_ACTIONS = frozenset({
    "run_command", "write_file", "delete", "exec", "social_post",
    "social_schedule", "publish", "deploy", "install",
})


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    require_approval: bool
    deny: bool
    reason: str
    risk: str  # low | medium | high


class Policy:
    """Deterministic policy evaluator."""

    def __init__(self, confirm_mode: bool = False) -> None:
        self.confirm_mode = confirm_mode

    def evaluate(self, action: str, resource: str = "", actor_id: str = "") -> PolicyDecision:
        action_l = (action or "").strip().lower()

        # Deny empty intent — force registration
        if not action_l:
            return PolicyDecision(
                allow=False, require_approval=False, deny=True,
                reason="empty action", risk="high",
            )

        # READ path
        if action_l in READ_ACTIONS:
            if self.confirm_mode:
                return PolicyDecision(
                    allow=False, require_approval=True, deny=False,
                    reason="confirm mode: even reads require approval", risk="low",
                )
            return PolicyDecision(
                allow=True, require_approval=False, deny=False,
                reason="read action auto-allowed", risk="low",
            )

        # EXECUTE path — always needs approval in v0
        if action_l in EXECUTE_ACTIONS:
            return PolicyDecision(
                allow=False, require_approval=True, deny=False,
                reason=f"execute action '{action_l}' requires approval", risk="high",
            )

        # Unknown action: conservative — require approval
        return PolicyDecision(
            allow=False, require_approval=True, deny=False,
            reason=f"unknown action '{action_l}' requires approval", risk="medium",
        )
