"""Base adapter for social media platforms — official API only."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SocialPost:
    content: str
    platform: str
    media_urls: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    scheduled_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PostResult:
    success: bool
    post_id: str = ""
    platform: str = ""
    url: str = ""
    error: str = ""
    scheduled: bool = False
    scheduled_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "post_id": self.post_id,
            "platform": self.platform,
            "url": self.url,
            "error": self.error,
            "scheduled": self.scheduled,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "metadata": self.metadata,
        }


@dataclass
class AnalyticsData:
    platform: str
    post_id: str = ""
    impressions: int = 0
    engagements: int = 0
    likes: int = 0
    shares: int = 0
    comments: int = 0
    clicks: int = 0
    reach: int = 0
    engagement_rate: float = 0.0
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "post_id": self.post_id,
            "impressions": self.impressions,
            "engagements": self.engagements,
            "likes": self.likes,
            "shares": self.shares,
            "comments": self.comments,
            "clicks": self.clicks,
            "reach": self.reach,
            "engagement_rate": self.engagement_rate,
            "retrieved_at": self.retrieved_at.isoformat(),
            "metadata": self.metadata,
        }


class SocialAdapter(ABC):
    """Base class for social media platform adapters.

    All adapters use official APIs only — no engagement automation,
    no follow/unfollow bots, no anything that mimics human interaction.
    """

    def __init__(self, platform: str, config: dict[str, Any]):
        self.platform = platform
        self.config = config
        self._client = None

    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with the platform API. Returns True if successful."""
        ...

    @abstractmethod
    async def draft_post(self, prompt: str, context: dict | None = None) -> SocialPost:
        """Draft a post from a prompt. Returns a SocialPost ready for review."""
        ...

    @abstractmethod
    async def schedule_post(self, post: SocialPost, scheduled_at: datetime) -> PostResult:
        """Schedule a post for later. Returns PostResult with schedule confirmation."""
        ...

    @abstractmethod
    async def publish_post(self, post: SocialPost) -> PostResult:
        """Immediately publish a post. Returns PostResult with publish confirmation."""
        ...

    @abstractmethod
    async def get_analytics(self, post_id: str) -> AnalyticsData:
        """Retrieve analytics for a published post."""
        ...

    @abstractmethod
    async def get_account_analytics(self, period: str = "7d") -> dict[str, Any]:
        """Retrieve account-level analytics for the specified period."""
        ...

    def is_configured(self) -> bool:
        """Check if the adapter has required credentials."""
        return bool(self.config.get("api_key") or self.config.get("access_token"))

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "configured": self.is_configured(),
        }
