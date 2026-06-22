import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class UsageRecord:
    provider: str
    model: str
    tier: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    session_id: str = ""
    agent: str = ""


class CostTracker:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                tier TEXT,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                session_id TEXT,
                agent TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def record(self, rec: UsageRecord) -> None:
        self._conn.execute(
            """INSERT INTO llm_usage
               (provider, model, tier, prompt_tokens, completion_tokens, cost_usd, session_id, agent, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.provider, rec.model, rec.tier,
                rec.prompt_tokens, rec.completion_tokens, rec.cost_usd,
                rec.session_id, rec.agent, datetime.now().isoformat(),
            ),
        )
        self._conn.commit()

    def summary(self, days: int = 30) -> dict:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM llm_usage WHERE timestamp >= ? ORDER BY timestamp DESC",
            (since,),
        ).fetchall()
        total_cost = sum(r["cost_usd"] for r in rows)
        total_tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows)
        by_provider: dict[str, dict] = {}
        for r in rows:
            key = r["provider"]
            if key not in by_provider:
                by_provider[key] = {"requests": 0, "tokens": 0, "cost_usd": 0.0}
            by_provider[key]["requests"] += 1
            by_provider[key]["tokens"] += r["prompt_tokens"] + r["completion_tokens"]
            by_provider[key]["cost_usd"] += r["cost_usd"]
        recent = [
            {
                "provider": r["provider"],
                "model": r["model"],
                "tier": r["tier"],
                "tokens": r["prompt_tokens"] + r["completion_tokens"],
                "cost_usd": round(r["cost_usd"], 6),
                "timestamp": r["timestamp"],
                "agent": r["agent"],
            }
            for r in rows[:20]
        ]
        return {
            "period_days": days,
            "total_requests": len(rows),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "by_provider": by_provider,
            "recent": recent,
        }
