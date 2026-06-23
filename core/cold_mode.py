import statistics
from dataclasses import dataclass

READ_ACTIONS = frozenset({"read_file", "list", "query"})
EXECUTE_ACTIONS = frozenset({"run_command", "write_file", "delete", "social_post", "social_schedule"})
HIGH_RISK_PERMISSIONS = frozenset({"EXECUTE", "ADMIN"})

@dataclass
class CheckResult:
    passed: bool
    check_name: str
    reason: str

class ColdMode:
    CONFIDENCE_THRESHOLD = 0.75

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    @staticmethod
    def build_context(
        action: str = "",
        permission: str = "READ",
        confidence: float | None = None,
        source_reliability: float | None = None,
        numeric_values: list | None = None,
        fallback_script: str | None = None,
        reversible: bool | None = None,
    ) -> dict:
        requires_fallback = permission in HIGH_RISK_PERMISSIONS or action in EXECUTE_ACTIONS
        if confidence is None:
            confidence = 0.95 if permission == "READ" else 0.5
        if reversible is None:
            if fallback_script and action in EXECUTE_ACTIONS:
                reversible = True
            else:
                reversible = action not in {"delete", "run_command"} or permission == "READ"
        return {
            "action": action,
            "permission": permission,
            "confidence": confidence,
            "source_reliability": source_reliability if source_reliability is not None else 0.8,
            "numeric_values": numeric_values or [],
            "fallback_script": fallback_script,
            "requires_fallback": requires_fallback,
            "reversible": reversible,
        }

    def evaluate(self, context: dict) -> list[CheckResult]:
        if not self.enabled:
            return [CheckResult(True, "cold_mode_disabled", "Cold mode is disabled")]
        return [
            self._check_data_verified(context),
            self._check_parameters(context),
            self._check_confidence(context),
            self._check_risk(context),
            self._check_fallback(context),
        ]

    def _check_data_verified(self, ctx: dict) -> CheckResult:
        source = ctx.get("source_reliability", 0)
        if source < 0.5:
            return CheckResult(False, "data_verified", f"Source reliability too low: {source:.2f}")
        return CheckResult(True, "data_verified", "Source verified")

    def _check_parameters(self, ctx: dict) -> CheckResult:
        values = ctx.get("numeric_values", [])
        if not values:
            return CheckResult(True, "parameters_in_range", "No numeric parameters to check")
        try:
            z_scores = [(v - statistics.mean(values)) / (statistics.stdev(values) or 1) for v in values]
            outliers = [abs(z) > 3 for z in z_scores]
            if any(outliers):
                return CheckResult(False, "parameters_in_range", f"Found {sum(outliers)} outlier(s)")
        except statistics.StatisticsError:
            pass
        return CheckResult(True, "parameters_in_range", "Parameters within range")

    def _check_confidence(self, ctx: dict) -> CheckResult:
        confidence = ctx.get("confidence", 0)
        if confidence < self.CONFIDENCE_THRESHOLD:
            return CheckResult(False, "confidence", f"Confidence too low: {confidence:.2f}")
        return CheckResult(True, "confidence", f"Confidence adequate: {confidence:.2f}")

    def _check_risk(self, ctx: dict) -> CheckResult:
        reversible = ctx.get("reversible", True)
        if not reversible:
            return CheckResult(False, "risk", "Action is not reversible")
        return CheckResult(True, "risk", "Action is reversible")

    def _check_fallback(self, ctx: dict) -> CheckResult:
        if not ctx.get("requires_fallback", False):
            return CheckResult(True, "fallback", "Fallback not required for this action")
        has_fallback = ctx.get("fallback_script") is not None
        if not has_fallback:
            return CheckResult(False, "fallback", "No fallback script available")
        return CheckResult(True, "fallback", "Fallback script available")

    def should_block(self, context: dict) -> bool:
        if not self.enabled:
            return False
        return not all(r.passed for r in self.evaluate(context))

    def get_failure_reasons(self, context: dict) -> list[str]:
        return [r.reason for r in self.evaluate(context) if not r.passed]
