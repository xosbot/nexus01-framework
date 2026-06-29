"""Tests for core/cost_dashboard.py and the cost_tracker user_id column."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.cost_dashboard import CostDashboard
from core.cost_tracker import CostTracker, UsageRecord


@pytest.fixture
def tracker(tmp_path: Path) -> CostTracker:
    return CostTracker(db_path=tmp_path / "cost.db")


def _rec(provider="ollama", model="qwen3:8b", tier="cheap",
         prompt=100, completion=50, cost=0.001,
         session="s1", agent="chat_stream", user_id="user_alice"):
    return UsageRecord(
        provider=provider, model=model, tier=tier,
        prompt_tokens=prompt, completion_tokens=completion,
        cost_usd=cost, session_id=session, agent=agent, user_id=user_id,
    )


# ── Schema migration ─────────────────────────────────────────────────


def test_cost_tracker_has_user_id_column(tracker: CostTracker) -> None:
    cols = {r[1] for r in tracker._conn.execute("PRAGMA table_info(llm_usage)").fetchall()}
    assert "user_id" in cols


def test_cost_tracker_user_id_index_exists(tracker: CostTracker) -> None:
    indexes = {
        r[0]
        for r in tracker._conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    assert "idx_llm_usage_user" in indexes


def test_record_stores_user_id(tracker: CostTracker) -> None:
    tracker.record(_rec(user_id="user_alice"))
    row = tracker._conn.execute("SELECT user_id FROM llm_usage").fetchone()
    assert row["user_id"] == "user_alice"


def test_record_defaults_to_legacy_when_user_id_blank(tracker: CostTracker) -> None:
    tracker.record(UsageRecord(
        provider="ollama", model="m", tier="cheap",
        prompt_tokens=10, completion_tokens=5, cost_usd=0.0,
        user_id="",  # falsy → legacy
    ))
    row = tracker._conn.execute("SELECT user_id FROM llm_usage").fetchone()
    assert row["user_id"] == "user_legacy"


# ── Dashboard aggregations ───────────────────────────────────────────


def test_dashboard_totals(tracker: CostTracker) -> None:
    tracker.record(_rec(prompt=100, completion=50, cost=0.5))
    tracker.record(_rec(prompt=200, completion=100, cost=1.5))
    d = CostDashboard(tracker).build(days=1)
    assert d["totals"]["requests"] == 2
    assert d["totals"]["tokens"] == 450
    assert d["totals"]["cost_usd"] == 2.0


def test_dashboard_daily_series_fills_gaps(tracker: CostTracker) -> None:
    """Even with no records, daily_series should return 30 buckets (one per day)."""
    d = CostDashboard(tracker).build(days=30)
    assert len(d["daily_series"]) == 30
    # Each entry has date, requests, tokens, cost_usd
    for entry in d["daily_series"]:
        assert "date" in entry
        assert "requests" in entry
        assert "tokens" in entry
        assert "cost_usd" in entry


def test_dashboard_by_provider(tracker: CostTracker) -> None:
    tracker.record(_rec(provider="ollama", cost=1.0))
    tracker.record(_rec(provider="ollama", cost=0.5))
    tracker.record(_rec(provider="groq", cost=2.0))
    d = CostDashboard(tracker).build(days=1)
    by = {p["provider"]: p for p in d["by_provider"]}
    assert by["ollama"]["requests"] == 2
    assert by["ollama"]["cost_usd"] == 1.5
    assert by["groq"]["requests"] == 1
    assert by["groq"]["cost_usd"] == 2.0
    # Sorted by cost desc
    assert d["by_provider"][0]["provider"] == "groq"


def test_dashboard_by_agent(tracker: CostTracker) -> None:
    tracker.record(_rec(agent="orchestrator", cost=1.0))
    tracker.record(_rec(agent="osint", cost=2.0))
    tracker.record(_rec(agent="orchestrator", cost=0.5))
    d = CostDashboard(tracker).build(days=1)
    by = {a["agent"]: a for a in d["by_agent"]}
    assert by["orchestrator"]["requests"] == 2
    assert by["osint"]["requests"] == 1
    # Sorted by cost desc → osint first
    assert d["by_agent"][0]["agent"] == "osint"


def test_dashboard_by_user_only_with_include_all(tracker: CostTracker) -> None:
    tracker.record(_rec(user_id="user_alice"))
    tracker.record(_rec(user_id="user_bob"))
    # by_user is empty when scoped to a single user
    scoped = CostDashboard(tracker).build(days=1, user_id="user_alice")
    assert scoped["by_user"] == []
    # ...and populated with include_all=True
    all_users = CostDashboard(tracker).build(days=1, include_all=True)
    by = {u["user_id"]: u for u in all_users["by_user"]}
    assert "user_alice" in by
    assert "user_bob" in by


def test_dashboard_top_sessions(tracker: CostTracker) -> None:
    tracker.record(_rec(session="s1", cost=1.0))
    tracker.record(_rec(session="s1", cost=0.5))
    tracker.record(_rec(session="s2", cost=5.0))
    d = CostDashboard(tracker).build(days=1)
    assert len(d["top_sessions"]) == 2
    # s2 has more cost, so first
    assert d["top_sessions"][0]["session_id"] == "s2"
    assert d["top_sessions"][0]["cost_usd"] == 5.0


def test_dashboard_recent_capped_at_20(tracker: CostTracker) -> None:
    for _ in range(25):
        tracker.record(_rec(cost=0.01))
    d = CostDashboard(tracker).build(days=1)
    assert len(d["recent"]) == 20


# ── Per-user isolation ────────────────────────────────────────────────


def test_dashboard_filters_by_user(tracker: CostTracker) -> None:
    tracker.record(_rec(user_id="user_alice", cost=1.0))
    tracker.record(_rec(user_id="user_bob", cost=2.0))
    alice = CostDashboard(tracker).build(days=1, user_id="user_alice")
    assert alice["totals"]["requests"] == 1
    assert alice["totals"]["cost_usd"] == 1.0
    bob = CostDashboard(tracker).build(days=1, user_id="user_bob")
    assert bob["totals"]["requests"] == 1
    assert bob["totals"]["cost_usd"] == 2.0


def test_dashboard_period_days_filter(tracker: CostTracker) -> None:
    """Records older than the window should be excluded."""
    # Backdate one record to 100 days ago
    tracker.record(_rec(cost=1.0, user_id="user_alice"))
    old_ts = (datetime.now() - timedelta(days=100)).isoformat()
    tracker._conn.execute(
        "UPDATE llm_usage SET timestamp = ? WHERE user_id = 'user_alice'",
        (old_ts,),
    )
    tracker._conn.commit()
    d = CostDashboard(tracker).build(days=30, user_id="user_alice")
    assert d["totals"]["requests"] == 0  # only the 100-day-old record, excluded
    # And the 100-day-old one shows up with days=200
    d2 = CostDashboard(tracker).build(days=200, user_id="user_alice")
    assert d2["totals"]["requests"] == 1


def test_dashboard_empty_window(tracker: CostTracker) -> None:
    d = CostDashboard(tracker).build(days=7)
    assert d["totals"] == {"requests": 0, "tokens": 0, "cost_usd": 0}
    assert d["by_provider"] == []
    assert d["by_agent"] == []
    assert d["by_user"] == []
    assert d["top_sessions"] == []
    assert d["recent"] == []
    # daily_series is filled with zero buckets
    assert len(d["daily_series"]) == 7


def test_dashboard_filters_dict_includes_user_id(tracker: CostTracker) -> None:
    d = CostDashboard(tracker).build(days=30, user_id="user_alice")
    assert d["filters"]["user_id"] == "user_alice"
    assert d["filters"]["include_all"] is False


def test_dashboard_includes_legacy_bucket(tracker: CostTracker) -> None:
    """Rows without user_id (legacy) should appear in the by_user breakdown."""
    tracker.record(_rec(user_id="user_legacy", cost=0.5))
    tracker.record(_rec(user_id="user_alice", cost=1.0))
    d = CostDashboard(tracker).build(days=1, include_all=True)
    by = {u["user_id"]: u for u in d["by_user"]}
    assert "user_legacy" in by
    assert by["user_legacy"]["cost_usd"] == 0.5
