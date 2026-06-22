"""Tests for session expiry and cleanup in Memory."""

import tempfile
from pathlib import Path
from datetime import datetime, timedelta

import pytest

from core.memory import Memory


@pytest.fixture
def memory():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    m = Memory(db_path=str(db_path))
    yield m


class TestSessionExpiry:
    def test_session_has_expires_at_column(self, memory):
        sid = memory.sessions.create(title="test", channel="cli")["id"]
        row = memory._conn.execute(
            "SELECT expires_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        assert row is not None

    def test_set_session_expiry(self, memory):
        sid = memory.sessions.create(title="test", channel="cli")["id"]
        memory.set_session_expiry(sid, hours=1)
        row = memory._conn.execute(
            "SELECT expires_at FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        assert row["expires_at"] is not None

    def test_cleanup_expired_sessions(self, memory):
        sid = memory.sessions.create(title="expired", channel="cli")["id"]
        past = (datetime.now() - timedelta(hours=2)).isoformat()
        memory._conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?", (past, sid)
        )
        memory._conn.commit()
        count = memory.cleanup_expired_sessions()
        assert count >= 1
        expired = memory.sessions.get(sid)
        assert expired is None

    def test_cleanup_does_not_remove_active(self, memory):
        sid = memory.sessions.create(title="active", channel="cli")["id"]
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        memory._conn.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?", (future, sid)
        )
        memory._conn.commit()
        memory.cleanup_expired_sessions()
        assert memory.sessions.get(sid) is not None

    def test_cleanup_no_expiry_set(self, memory):
        sid = memory.sessions.create(title="no-expiry", channel="cli")["id"]
        memory.cleanup_expired_sessions()
        assert memory.sessions.get(sid) is not None