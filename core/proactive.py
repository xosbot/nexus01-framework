"""IVA Proactive Intelligence — Monitoring, alerts, and learning.

IVA doesn't wait for commands. It:
- Monitors tracked entities for changes
- Detects threats and opportunities
- Learns from interactions
- Suggests actions proactively
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from typing import Any, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MonitorType(Enum):
    DOMAIN = "domain"
    IP = "ip"
    KEYWORD = "keyword"
    CVE = "cve"
    CERTIFICATE = "certificate"
    CUSTOM = "custom"


@dataclass
class Alert:
    id: str
    severity: AlertSeverity
    title: str
    description: str
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    acknowledged: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "source": self.source,
            "data": self.data,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
        }


@dataclass
class Monitor:
    id: str
    name: str
    type: MonitorType
    target: str
    interval: int = 3600
    last_check: str | None = None
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "target": self.target,
            "interval": self.interval,
            "last_check": self.last_check,
            "enabled": self.enabled,
            "config": self.config,
        }


@dataclass
class LearningEntry:
    id: str
    pattern: str
    confidence: float
    examples: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used: str | None = None
    use_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pattern": self.pattern,
            "confidence": self.confidence,
            "examples_count": len(self.examples),
            "created_at": self.created_at,
            "last_used": self.last_used,
            "use_count": self.use_count,
        }


class ProactiveIntelligence:
    """IVA's proactive intelligence system."""

    def __init__(self, memory=None, brain=None):
        self.memory = memory
        self.brain = brain
        self.monitors: dict[str, Monitor] = {}
        self.alerts: list[Alert] = []
        self.learnings: list[LearningEntry] = []
        self._check_callbacks: list[Callable] = []
        self._alert_callbacks: list[Callable] = []

    def register_monitor(self, name: str, monitor_type: MonitorType,
                          target: str, interval: int = 3600,
                          config: dict = None) -> Monitor:
        monitor = Monitor(
            id=f"mon_{name}_{int(time.time())}",
            name=name,
            type=monitor_type,
            target=target,
            interval=interval,
            config=config or {},
        )
        self.monitors[monitor.id] = monitor
        logger.info(f"Registered monitor: {name} ({monitor_type.value})")
        return monitor

    def unregister_monitor(self, monitor_id: str) -> bool:
        if monitor_id in self.monitors:
            del self.monitors[monitor_id]
            return True
        return False

    def list_monitors(self) -> list[dict]:
        return [m.to_dict() for m in self.monitors.values()]

    async def check_monitors(self) -> list[Alert]:
        new_alerts = []
        now = time.time()

        for monitor in self.monitors.values():
            if not monitor.enabled:
                continue

            last_check = 0
            if monitor.last_check:
                try:
                    last_check = datetime.fromisoformat(monitor.last_check).timestamp()
                except Exception:
                    pass

            if now - last_check < monitor.interval:
                continue

            for callback in self._check_callbacks:
                try:
                    await callback(monitor)
                except Exception as e:
                    logger.error(f"Check callback error: {e}")

            try:
                alerts = await self._check_monitor(monitor)
                new_alerts.extend(alerts)
                monitor.last_check = datetime.now(timezone.utc).isoformat()
            except Exception as e:
                logger.error(f"Monitor check failed: {monitor.name} — {e}")

        self.alerts.extend(new_alerts)

        for alert in new_alerts:
            for callback in self._alert_callbacks:
                try:
                    await callback(alert)
                except Exception as e:
                    logger.error(f"Alert callback error: {e}")

        return new_alerts

    async def _check_monitor(self, monitor: Monitor) -> list[Alert]:
        if monitor.type == MonitorType.DOMAIN:
            return await self._check_domain(monitor)
        elif monitor.type == MonitorType.IP:
            return await self._check_ip(monitor)
        elif monitor.type == MonitorType.KEYWORD:
            return await self._check_keyword(monitor)
        elif monitor.type == MonitorType.CVE:
            return await self._check_cve(monitor)
        elif monitor.type == MonitorType.CERTIFICATE:
            return await self._check_certificate(monitor)
        return []

    async def _check_domain(self, monitor: Monitor) -> list[Alert]:
        alerts = []
        domain = monitor.target
        prev_state = monitor.state

        current_state = {
            "domain": domain,
            "checked": datetime.now(timezone.utc).isoformat(),
            "records": {},
        }

        try:
            import socket
            try:
                ip = socket.gethostbyname(domain)
                current_state["records"]["a"] = ip
            except Exception:
                current_state["records"]["a"] = None
        except Exception:
            pass

        if prev_state:
            prev_ip = prev_state.get("records", {}).get("a")
            curr_ip = current_state.get("records", {}).get("a")
            if prev_ip and curr_ip and prev_ip != curr_ip:
                alerts.append(Alert(
                    id=f"alert_{int(time.time())}",
                    severity=AlertSeverity.HIGH,
                    title=f"DNS change detected: {domain}",
                    description=f"IP changed from {prev_ip} to {curr_ip}",
                    source=monitor.name,
                    data={"domain": domain, "prev_ip": prev_ip, "new_ip": curr_ip},
                ))

        monitor.state = current_state
        return alerts

    async def _check_ip(self, monitor: Monitor) -> list[Alert]:
        return []

    async def _check_keyword(self, monitor: Monitor) -> list[Alert]:
        return []

    async def _check_cve(self, monitor: Monitor) -> list[Alert]:
        return []

    async def _check_certificate(self, monitor: Monitor) -> list[Alert]:
        return []

    def create_alert(self, severity: AlertSeverity, title: str,
                      description: str, source: str = "system",
                      data: dict = None) -> Alert:
        alert = Alert(
            id=f"alert_{int(time.time())}",
            severity=severity,
            title=title,
            description=description,
            source=source,
            data=data or {},
        )
        self.alerts.append(alert)
        return alert

    def get_alerts(self, limit: int = 50, unacknowledged_only: bool = False) -> list[dict]:
        alerts = self.alerts
        if unacknowledged_only:
            alerts = [a for a in alerts if not a.acknowledged]
        return [a.to_dict() for a in alerts[-limit:]]

    def acknowledge_alert(self, alert_id: str) -> bool:
        for alert in self.alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def on_alert(self, callback: Callable) -> None:
        self._alert_callbacks.append(callback)

    def on_check(self, callback: Callable) -> None:
        self._check_callbacks.append(callback)

    def learn(self, pattern: str, example: dict, confidence: float = 0.5) -> None:
        existing = next((l for l in self.learnings if l.pattern == pattern), None)
        if existing:
            existing.examples.append(example)
            if len(existing.examples) > 10:
                existing.examples = existing.examples[-10:]
            existing.confidence = min(1.0, existing.confidence + 0.1)
            existing.use_count += 1
            existing.last_used = datetime.now(timezone.utc).isoformat()
        else:
            entry = LearningEntry(
                id=f"learn_{int(time.time())}",
                pattern=pattern,
                confidence=confidence,
                examples=[example],
            )
            self.learnings.append(entry)

    def suggest(self, context: str) -> list[dict]:
        suggestions = []
        context_lower = context.lower()

        for learning in self.learnings:
            if learning.confidence > 0.6:
                if any(word in context_lower for word in learning.pattern.split()):
                    suggestions.append({
                        "pattern": learning.pattern,
                        "confidence": learning.confidence,
                        "example": learning.examples[-1] if learning.examples else None,
                    })

        return sorted(suggestions, key=lambda x: x["confidence"], reverse=True)[:5]

    def get_stats(self) -> dict:
        return {
            "monitors": len(self.monitors),
            "active_monitors": sum(1 for m in self.monitors.values() if m.enabled),
            "alerts": len(self.alerts),
            "unacknowledged": sum(1 for a in self.alerts if not a.acknowledged),
            "learnings": len(self.learnings),
        }
