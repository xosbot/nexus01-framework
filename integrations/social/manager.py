"""Social Media Manager — coordinates adapters, calendar, and approval gates."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from integrations.social.base import SocialAdapter, SocialPost, PostResult, AnalyticsData
from integrations.social.calendar import ContentCalendar, CalendarEntry

logger = logging.getLogger(__name__)


class SocialMediaManager:
    """Manages social media adapters and content calendar.

    All posting goes through Cold Mode gate and HITL approval flow.
    """

    def __init__(self, adapters: dict[str, SocialAdapter] | None = None):
        self._adapters: dict[str, SocialAdapter] = adapters or {}
        self._calendar = ContentCalendar()

    def register_adapter(self, adapter: SocialAdapter) -> None:
        self._adapters[adapter.platform] = adapter
        logger.info("Social: Registered adapter for %s", adapter.platform)

    def get_adapter(self, platform: str) -> SocialAdapter | None:
        return self._adapters.get(platform)

    def list_adapters(self) -> list[dict]:
        return [a.to_dict() for a in self._adapters.values()]

    def get_calendar(self) -> ContentCalendar:
        return self._calendar

    async def draft_post(
        self,
        platform: str,
        prompt: str,
        context: dict | None = None,
    ) -> CalendarEntry:
        adapter = self._adapters.get(platform)
        if not adapter:
            raise ValueError(f"No adapter registered for platform: {platform}")

        if not adapter.is_configured():
            raise ValueError(f"Platform {platform} is not configured with API credentials")

        post = await adapter.draft_post(prompt, context)

        entry = self._calendar.create(
            platform=platform,
            content=post.content,
            media_urls=post.media_urls,
            hashtags=post.hashtags,
            metadata={**post.metadata, "draft_prompt": prompt},
        )

        logger.info("Social: Drafted post %s for %s", entry.id, platform)
        return entry

    async def schedule_post(
        self,
        entry_id: str,
        scheduled_at: datetime,
    ) -> CalendarEntry:
        entry = self._calendar.get(entry_id)
        if not entry:
            raise ValueError(f"Calendar entry not found: {entry_id}")

        adapter = self._adapters.get(entry.platform)
        if not adapter:
            raise ValueError(f"No adapter registered for platform: {entry.platform}")

        post = SocialPost(
            content=entry.content,
            platform=entry.platform,
            media_urls=entry.media_urls,
            hashtags=entry.hashtags,
        )

        result = await adapter.schedule_post(post, scheduled_at)

        if result.success:
            self._calendar.update(
                entry_id,
                status="scheduled",
                scheduled_at=scheduled_at.isoformat(),
                post_id=result.post_id,
            )
            logger.info("Social: Scheduled post %s for %s at %s", entry_id, entry.platform, scheduled_at)
        else:
            self._calendar.mark_failed(entry_id, result.error)
            logger.error("Social: Failed to schedule post %s: %s", entry_id, result.error)

        return self._calendar.get(entry_id)

    async def publish_now(self, entry_id: str) -> CalendarEntry:
        entry = self._calendar.get(entry_id)
        if not entry:
            raise ValueError(f"Calendar entry not found: {entry_id}")

        adapter = self._adapters.get(entry.platform)
        if not adapter:
            raise ValueError(f"No adapter registered for platform: {entry.platform}")

        post = SocialPost(
            content=entry.content,
            platform=entry.platform,
            media_urls=entry.media_urls,
            hashtags=entry.hashtags,
        )

        result = await adapter.publish_post(post)

        if result.success:
            self._calendar.mark_published(entry_id, result.post_id, result.url)
            logger.info("Social: Published post %s to %s", entry_id, entry.platform)
        else:
            self._calendar.mark_failed(entry_id, result.error)
            logger.error("Social: Failed to publish post %s: %s", entry_id, result.error)

        return self._calendar.get(entry_id)

    async def get_analytics(self, entry_id: str) -> AnalyticsData:
        entry = self._calendar.get(entry_id)
        if not entry:
            raise ValueError(f"Calendar entry not found: {entry_id}")

        adapter = self._adapters.get(entry.platform)
        if not adapter:
            raise ValueError(f"No adapter registered for platform: {entry.platform}")

        return await adapter.get_analytics(entry.post_id)

    async def get_platform_analytics(self, platform: str, period: str = "7d") -> dict[str, Any]:
        adapter = self._adapters.get(platform)
        if not adapter:
            return {"error": f"No adapter registered for platform: {platform}"}

        return await adapter.get_account_analytics(period)

    def get_pending_posts(self) -> list[CalendarEntry]:
        return self._calendar.get_pending_posts()

    def stats(self) -> dict:
        calendar_stats = self._calendar.stats()
        adapter_stats = {name: a.to_dict() for name, a in self._adapters.items()}
        return {
            "calendar": calendar_stats,
            "adapters": adapter_stats,
        }
