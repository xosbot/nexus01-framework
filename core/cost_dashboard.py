"""Cost dashboard — daily / provider / agent / user aggregates over llm_usage.

Built on top of CostTracker. Provides the data the admin Costs tab needs:
  - daily_series:    list[{date, requests, tokens, cost_usd}]  for chart
  - by_provider:     list[{provider, requests, tokens, cost_usd}]  for pie
  - by_agent:        list[{agent, requests, tokens, cost_usd}]      for table
  - by_user:         list[{user_id, requests, tokens, cost_usd}]    for table
  - top_sessions:    list[{session_id, requests, cost_usd}]        for table
  - recent:          list[dict]   last 20 records (mirrors tracker.summary)

All aggregations are time-bounded by `days` (default 30). Optional `user_id`
filter scopes the result to a single user; admins can pass `include_all=True`
to bypass.

The shape of the data is JSON-friendly (lists, primitives) so the frontend
can render charts directly with Chart.js without further transformation.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from core.cost_tracker import CostTracker
from core.users import LEGACY_USER_ID


class CostDashboard:
    """Read-only aggregator over llm_usage."""

    def __init__(self, tracker: CostTracker) -> None:
        self._tracker = tracker

    def _query(
        self, days: int, user_id: str | None = None, include_all: bool = False,
    ) -> list[sqlite3.Row]:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        sql = "SELECT * FROM llm_usage WHERE timestamp >= ?"
        params: list[Any] = [since]
        if user_id is not None and not include_all:
            sql += " AND user_id = ?"
            params.append(user_id)
        sql += " ORDER BY timestamp DESC"
        return self._tracker._conn.execute(sql, params).fetchall()

    def build(
        self, days: int = 30, *,
        user_id: str | None = None, include_all: bool = False,
    ) -> dict:
        """Return the full dashboard payload for a time window + optional user filter."""
        rows = self._query(days, user_id=user_id, include_all=include_all)
        return {
            "period_days": days,
            "filters": {
                "user_id": user_id,
                "include_all": include_all,
            },
            "totals": self._totals(rows),
            "daily_series": self._daily_series(rows, days),
            "by_provider": self._by_provider(rows),
            "by_agent": self._by_agent(rows),
            "by_user": self._by_user(rows) if include_all or user_id is None else [],
            "top_sessions": self._top_sessions(rows, n=10),
            "recent": self._recent(rows, n=20),
        }

    # ── Aggregations ────────────────────────────────────────────────────

    @staticmethod
    def _totals(rows: list[sqlite3.Row]) -> dict:
        cost = sum(r["cost_usd"] for r in rows)
        tokens = sum((r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0) for r in rows)
        return {
            "requests": len(rows),
            "tokens": tokens,
            "cost_usd": round(cost, 4),
        }

    @staticmethod
    def _daily_series(rows: list[sqlite3.Row], days: int) -> list[dict]:
        """One bucket per day, oldest first (chart-friendly)."""
        buckets: dict[str, dict] = defaultdict(
            lambda: {"requests": 0, "tokens": 0, "cost_usd": 0.0}
        )
        for r in rows:
            day = (r["timestamp"] or "")[:10]  # YYYY-MM-DD
            if not day:
                continue
            buckets[day]["requests"] += 1
            buckets[day]["tokens"] += (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)
            buckets[day]["cost_usd"] += r["cost_usd"] or 0
        # Fill in empty days so the chart has no gaps
        today = datetime.now().date()
        out: list[dict] = []
        for i in range(days - 1, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            b = buckets.get(d, {"requests": 0, "tokens": 0, "cost_usd": 0.0})
            out.append({
                "date": d,
                "requests": b["requests"],
                "tokens": b["tokens"],
                "cost_usd": round(b["cost_usd"], 4),
            })
        return out

    @staticmethod
    def _by_provider(rows: list[sqlite3.Row]) -> list[dict]:
        agg: dict[str, dict] = defaultdict(
            lambda: {"requests": 0, "tokens": 0, "cost_usd": 0.0}
        )
        for r in rows:
            key = r["provider"] or "unknown"
            agg[key]["requests"] += 1
            agg[key]["tokens"] += (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)
            agg[key]["cost_usd"] += r["cost_usd"] or 0
        out = []
        for provider, d in agg.items():
            out.append({
                "provider": provider,
                "requests": d["requests"],
                "tokens": d["tokens"],
                "cost_usd": round(d["cost_usd"], 4),
            })
        return sorted(out, key=lambda x: -x["cost_usd"])

    @staticmethod
    def _by_agent(rows: list[sqlite3.Row]) -> list[dict]:
        agg: dict[str, dict] = defaultdict(
            lambda: {"requests": 0, "tokens": 0, "cost_usd": 0.0}
        )
        for r in rows:
            key = r["agent"] or "(none)"
            agg[key]["requests"] += 1
            agg[key]["tokens"] += (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)
            agg[key]["cost_usd"] += r["cost_usd"] or 0
        out = []
        for agent, d in agg.items():
            out.append({
                "agent": agent,
                "requests": d["requests"],
                "tokens": d["tokens"],
                "cost_usd": round(d["cost_usd"], 4),
            })
        return sorted(out, key=lambda x: -x["cost_usd"])

    @staticmethod
    def _by_user(rows: list[sqlite3.Row]) -> list[dict]:
        """Per-user cost breakdown. Includes the legacy user bucket for system traffic."""
        agg: dict[str, dict] = defaultdict(
            lambda: {"requests": 0, "tokens": 0, "cost_usd": 0.0}
        )
        for r in rows:
            key = r["user_id"] or LEGACY_USER_ID
            agg[key]["requests"] += 1
            agg[key]["tokens"] += (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)
            agg[key]["cost_usd"] += r["cost_usd"] or 0
        out = []
        for uid, d in agg.items():
            out.append({
                "user_id": uid,
                "requests": d["requests"],
                "tokens": d["tokens"],
                "cost_usd": round(d["cost_usd"], 4),
            })
        return sorted(out, key=lambda x: -x["cost_usd"])

    @staticmethod
    def _top_sessions(rows: list[sqlite3.Row], n: int = 10) -> list[dict]:
        agg: dict[str, dict] = defaultdict(
            lambda: {"requests": 0, "tokens": 0, "cost_usd": 0.0}
        )
        for r in rows:
            sid = r["session_id"] or ""
            if not sid:
                continue
            agg[sid]["requests"] += 1
            agg[sid]["tokens"] += (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)
            agg[sid]["cost_usd"] += r["cost_usd"] or 0
        out = []
        for sid, d in agg.items():
            out.append({
                "session_id": sid,
                "requests": d["requests"],
                "tokens": d["tokens"],
                "cost_usd": round(d["cost_usd"], 4),
            })
        out.sort(key=lambda x: -x["cost_usd"])
        return out[:n]

    @staticmethod
    def _recent(rows: list[sqlite3.Row], n: int = 20) -> list[dict]:
        out = []
        for r in rows[:n]:
            out.append({
                "provider": r["provider"],
                "model": r["model"],
                "tier": r["tier"],
                "tokens": (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0),
                "cost_usd": round(r["cost_usd"] or 0, 6),
                "timestamp": r["timestamp"],
                "agent": r["agent"],
                "user_id": r["user_id"],
                "session_id": r["session_id"],
            })
        return out
