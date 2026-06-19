"""Structured JSON logging for NEXUS-01 production use."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON for structured log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }

        for key in ("agent", "session_id", "provider", "model", "tier", "action", "duration_ms", "exit_code"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_entry["extra"] = record.extra_data

        return json.dumps(log_entry, default=str)


class HumanReadableFormatter(logging.Formatter):
    """Compact colored formatter for terminal use."""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[1;31m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        ts = datetime.now().strftime("%H:%M:%S")
        return f"{color}{ts} [{record.levelname:7s}] {record.name}: {record.getMessage()}{self.RESET}"


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    if json_output:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(HumanReadableFormatter())

    root.addHandler(handler)


def log_structured(
    logger_instance: logging.Logger,
    level: str,
    message: str,
    **kwargs: Any,
) -> None:
    record = logger_instance.makeRecord(
        logger_instance.name, getattr(logging, level.upper()),
        "(structured)", 0, message, (), None,
    )
    for k, v in kwargs.items():
        setattr(record, k, v)
    logger_instance.handle(record)
