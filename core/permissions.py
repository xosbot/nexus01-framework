"""Per-session permission modes — Ask Me vs Allow All.

IVA runs in two permission modes per session:
  - "ask"   (default): cold mode gate is enforced, destructive actions need
                       explicit approval via the dashboard or reply YES/NO.
  - "allow":           the operator has opted in to running destructive
                       actions without prompting for this session. Cold mode
                       still blocks catastrophic actions (rm -rf, drop table).

Modes are stored in the events DB (events table with kind="permission")
so they survive restarts. The dashboard surfaces the current mode and
provides a one-click toggle.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import sqlite3
import threading

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / "data" / "events.db"
_lock = threading.Lock()
Mode = Literal["ask", "allow"]


@dataclass
class Permission:
    session_id: str
    mode: Mode
    set_at: float
    set_by: str  # "user", "default", or operator handle

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "set_at": self.set_at,
            "set_by": self.set_by,
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.set_at)),
        }


def _conn():
    c = sqlite3.connect(str(_DB_PATH), timeout=5.0)
    c.row_factory = sqlite3.Row
    return c


def _ensure(c: sqlite3.Connection) -> None:
    c.execute("""
        CREATE TABLE IF NOT EXISTS permissions (
            session_id TEXT PRIMARY KEY,
            mode TEXT NOT NULL,
            set_at REAL NOT NULL,
            set_by TEXT NOT NULL DEFAULT 'user'
        )
    """)


def get(session_id: str) -> Permission:
    with _lock:
        c = _conn()
        try:
            _ensure(c)
            r = c.execute(
                "SELECT * FROM permissions WHERE session_id = ?", (session_id,)
            ).fetchone()
        finally:
            c.close()
    if r:
        return Permission(session_id=r["session_id"], mode=r["mode"], set_at=r["set_at"], set_by=r["set_by"])
    return Permission(session_id=session_id, mode="ask", set_at=time.time(), set_by="default")


def set_mode(session_id: str, mode: Mode, set_by: str = "user") -> Permission:
    if mode not in ("ask", "allow"):
        raise ValueError(f"Invalid mode: {mode}")
    ts = time.time()
    with _lock:
        c = _conn()
        try:
            _ensure(c)
            c.execute(
                "INSERT OR REPLACE INTO permissions (session_id, mode, set_at, set_by) VALUES (?,?,?,?)",
                (session_id, mode, ts, set_by),
            )
            c.commit()
            from core.events import emit
            emit("slash_command", f"permission set: {mode}", session_id=session_id, agent="permissions", data={"mode": mode, "set_by": set_by})
        finally:
            c.close()
    return Permission(session_id=session_id, mode=mode, set_at=ts, set_by=set_by)


def is_allowed(session_id: str, action: str = "exec") -> bool:
    """Returns True if the action can run without further approval for this session."""
    perm = get(session_id)
    if perm.mode == "allow":
        return True
    return False


def list_all() -> list[dict]:
    with _lock:
        c = _conn()
        try:
            _ensure(c)
            rows = c.execute("SELECT * FROM permissions ORDER BY set_at DESC LIMIT 200").fetchall()
        finally:
            c.close()
    return [
        {
            "session_id": r["session_id"],
            "mode": r["mode"],
            "set_at": r["set_at"],
            "set_by": r["set_by"],
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["set_at"])),
        }
        for r in rows
    ]
