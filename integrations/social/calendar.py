"""Content calendar store — SQLite-backed scheduled post persistence."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CalendarEntry:
    id: str
    platform: str
    content: str
    scheduled_at: str
    status: str  # draft, scheduled, published, failed, cancelled
    post_id: str = ""
    url: str = ""
    media_urls: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "content": self.content,
            "scheduled_at": self.scheduled_at,
            "status": self.status,
            "post_id": self.post_id,
            "url": self.url,
            "media_urls": self.media_urls,
            "hashtags": self.hashtags,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ContentCalendar:
    """SQLite-backed content calendar for scheduled posts."""

    def __init__(self, db_path: str = "./data/social_calendar.db"):
        self._db_path = db_path
        self._conn = None
        self._init_db()

    def _init_db(self) -> None:
        import os
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS calendar_entries (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                content TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                post_id TEXT DEFAULT '',
                url TEXT DEFAULT '',
                media_urls TEXT DEFAULT '[]',
                hashtags TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_calendar_status ON calendar_entries(status)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_calendar_scheduled ON calendar_entries(scheduled_at)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_calendar_platform ON calendar_entries(platform)
        """)
        self._conn.commit()

    def create(
        self,
        platform: str,
        content: str,
        scheduled_at: datetime | str | None = None,
        media_urls: list[str] | None = None,
        hashtags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CalendarEntry:
        entry_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        if isinstance(scheduled_at, datetime):
            scheduled_at = scheduled_at.isoformat()
        elif scheduled_at is None:
            scheduled_at = now

        entry = CalendarEntry(
            id=entry_id,
            platform=platform,
            content=content,
            scheduled_at=scheduled_at,
            status="draft",
            media_urls=media_urls or [],
            hashtags=hashtags or [],
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

        self._conn.execute(
            """INSERT INTO calendar_entries
               (id, platform, content, scheduled_at, status, post_id, url,
                media_urls, hashtags, metadata, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.platform,
                entry.content,
                entry.scheduled_at,
                entry.status,
                entry.post_id,
                entry.url,
                json.dumps(entry.media_urls),
                json.dumps(entry.hashtags),
                json.dumps(entry.metadata),
                entry.created_at,
                entry.updated_at,
            ),
        )
        self._conn.commit()
        logger.info("Calendar: Created entry %s for %s", entry_id, platform)
        return entry

    def get(self, entry_id: str) -> CalendarEntry | None:
        row = self._conn.execute(
            "SELECT * FROM calendar_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return self._row_to_entry(row) if row else None

    def list_entries(
        self,
        platform: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[CalendarEntry]:
        query = "SELECT * FROM calendar_entries WHERE 1=1"
        params: list[Any] = []

        if platform:
            query += " AND platform = ?"
            params.append(platform)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY scheduled_at ASC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def update(self, entry_id: str, **fields) -> CalendarEntry | None:
        entry = self.get(entry_id)
        if not entry:
            return None

        now = datetime.now(timezone.utc).isoformat()
        updates = []
        params: list[Any] = []

        for field_name in ("platform", "content", "scheduled_at", "status", "post_id", "url"):
            if field_name in fields:
                updates.append(f"{field_name} = ?")
                params.append(fields[field_name])

        for field_name in ("media_urls", "hashtags", "metadata"):
            if field_name in fields:
                updates.append(f"{field_name} = ?")
                params.append(json.dumps(fields[field_name]))

        if updates:
            updates.append("updated_at = ?")
            params.append(now)
            params.append(entry_id)
            self._conn.execute(
                f"UPDATE calendar_entries SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            self._conn.commit()

        return self.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM calendar_entries WHERE id = ?", (entry_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_pending_posts(self) -> list[CalendarEntry]:
        now = datetime.now(timezone.utc).isoformat()
        rows = self._conn.execute(
            """SELECT * FROM calendar_entries
               WHERE status = 'scheduled' AND scheduled_at <= ?
               ORDER BY scheduled_at ASC""",
            (now,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def mark_published(self, entry_id: str, post_id: str, url: str = "") -> CalendarEntry | None:
        return self.update(entry_id, status="published", post_id=post_id, url=url)

    def mark_failed(self, entry_id: str, error: str = "") -> CalendarEntry | None:
        return self.update(entry_id, status="failed", metadata={"error": error})

    def cancel(self, entry_id: str) -> CalendarEntry | None:
        return self.update(entry_id, status="cancelled")

    def stats(self) -> dict:
        row = self._conn.execute(
            """SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END) as drafts,
                SUM(CASE WHEN status = 'scheduled' THEN 1 ELSE 0 END) as scheduled,
                SUM(CASE WHEN status = 'published' THEN 1 ELSE 0 END) as published,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled
            FROM calendar_entries"""
        ).fetchone()
        return {
            "total": row[0] if row else 0,
            "drafts": row[1] if row else 0,
            "scheduled": row[2] if row else 0,
            "published": row[3] if row else 0,
            "failed": row[4] if row else 0,
            "cancelled": row[5] if row else 0,
        }

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> CalendarEntry:
        return CalendarEntry(
            id=row["id"],
            platform=row["platform"],
            content=row["content"],
            scheduled_at=row["scheduled_at"],
            status=row["status"],
            post_id=row["post_id"],
            url=row["url"],
            media_urls=json.loads(row["media_urls"] or "[]"),
            hashtags=json.loads(row["hashtags"] or "[]"),
            metadata=json.loads(row["metadata"] or "{}"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
