"""Social Media Automation — Official API adapters for scheduling and analytics.

Supports:
- Twitter/X API v2
- LinkedIn Marketing API
- Content calendar management
- Analytics retrieval

All posting goes through Cold Mode gate and HITL approval flow.
"""

from __future__ import annotations

from integrations.social.base import SocialAdapter, SocialPost, PostResult, AnalyticsData
from integrations.social.twitter_adapter import TwitterAdapter
from integrations.social.linkedin_adapter import LinkedInAdapter
from integrations.social.calendar import ContentCalendar, CalendarEntry

__all__ = [
    "SocialAdapter",
    "SocialPost",
    "PostResult",
    "AnalyticsData",
    "TwitterAdapter",
    "LinkedInAdapter",
    "ContentCalendar",
    "CalendarEntry",
]
