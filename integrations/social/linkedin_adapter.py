"""LinkedIn adapter — official Marketing API only."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from integrations.social.base import SocialAdapter, SocialPost, PostResult, AnalyticsData

logger = logging.getLogger(__name__)

LINKEDIN_API_BASE = "https://api.linkedin.com/v2"


class LinkedInAdapter(SocialAdapter):
    """LinkedIn adapter using official Marketing API.

    Required config:
        - access_token: OAuth2 access token
        - organization_id: LinkedIn organization ID (for org posts)
        - person_id: LinkedIn person URN (for personal posts)
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__("linkedin", config)
        self._access_token = config.get("access_token", "")
        self._person_id = config.get("person_id", "")
        self._org_id = config.get("organization_id", "")

    async def authenticate(self) -> bool:
        if not self._access_token:
            logger.warning("LinkedIn: No access token configured")
            return False

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{LINKEDIN_API_BASE}/userinfo",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    logger.info("LinkedIn: Authenticated as %s", data.get("name", "unknown"))
                    return True
                logger.warning("LinkedIn: Auth failed: %s", resp.status_code)
                return False
        except Exception as exc:
            logger.error("LinkedIn: Auth error: %s", exc)
            return False

    async def draft_post(self, prompt: str, context: dict | None = None) -> SocialPost:
        post = SocialPost(
            content=prompt[:3000],
            platform="linkedin",
            metadata={"draft_reason": "user_request", "original_prompt": prompt},
        )
        return post

    async def schedule_post(self, post: SocialPost, scheduled_at: datetime) -> PostResult:
        if not self._access_token:
            return PostResult(
                success=False,
                platform="linkedin",
                error="LinkedIn API credentials not configured",
            )

        try:
            author = f"urn:li:person:{self._person_id}" if self._person_id else f"urn:li:organization:{self._org_id}"

            payload = {
                "author": author,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": post.content},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            }

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{LINKEDIN_API_BASE}/ugcPosts",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                        "X-Restli-Protocol-Version": "2.0.0",
                    },
                    json=payload,
                    timeout=30.0,
                )

                if resp.status_code in (200, 201):
                    post_id = resp.headers.get("x-restli-id", resp.json().get("id", ""))
                    return PostResult(
                        success=True,
                        post_id=post_id,
                        platform="linkedin",
                        scheduled=True,
                        scheduled_at=scheduled_at,
                    )
                else:
                    error = resp.text[:200]
                    return PostResult(
                        success=False,
                        platform="linkedin",
                        error=f"Schedule failed: {error}",
                    )
        except Exception as exc:
            return PostResult(
                success=False,
                platform="linkedin",
                error=str(exc),
            )

    async def publish_post(self, post: SocialPost) -> PostResult:
        if not self._access_token:
            return PostResult(
                success=False,
                platform="linkedin",
                error="LinkedIn API credentials not configured",
            )

        try:
            author = f"urn:li:person:{self._person_id}" if self._person_id else f"urn:li:organization:{self._org_id}"

            payload = {
                "author": author,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": post.content},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            }

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{LINKEDIN_API_BASE}/ugcPosts",
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Content-Type": "application/json",
                        "X-Restli-Protocol-Version": "2.0.0",
                    },
                    json=payload,
                    timeout=30.0,
                )

                if resp.status_code in (200, 201):
                    post_id = resp.headers.get("x-restli-id", resp.json().get("id", ""))
                    return PostResult(
                        success=True,
                        post_id=post_id,
                        platform="linkedin",
                        url=f"https://www.linkedin.com/feed/update/{post_id}",
                    )
                else:
                    error = resp.text[:200]
                    return PostResult(
                        success=False,
                        platform="linkedin",
                        error=f"Publish failed: {error}",
                    )
        except Exception as exc:
            return PostResult(
                success=False,
                platform="linkedin",
                error=str(exc),
            )

    async def get_analytics(self, post_id: str) -> AnalyticsData:
        analytics = AnalyticsData(platform="linkedin", post_id=post_id)

        if not self._access_token:
            return analytics

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{LINKEDIN_API_BASE}/organizationalEntityShareStatistics",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    params={
                        "q": "organizationalEntity",
                        "shares": post_id,
                        "timeRange": "(timeRange:(start:0,end:0))",
                    },
                    timeout=10.0,
                )

                if resp.status_code == 200:
                    elements = resp.json().get("elements", [])
                    if elements:
                        metrics = elements[0].get("totalShareStatistics", {})
                        analytics.impressions = metrics.get("impressionCount", 0)
                        analytics.clicks = metrics.get("clickCount", 0)
                        analytics.likes = metrics.get("likeCount", 0)
                        analytics.comments = metrics.get("commentCount", 0)
                        analytics.shares = metrics.get("shareCount", 0)
                        analytics.engagements = (
                            analytics.likes + analytics.shares + analytics.comments + analytics.clicks
                        )
                        if analytics.impressions > 0:
                            analytics.engagement_rate = analytics.engagements / analytics.impressions
        except Exception as exc:
            logger.error("LinkedIn analytics error: %s", exc)

        return analytics

    async def get_account_analytics(self, period: str = "7d") -> dict[str, Any]:
        if not self._access_token:
            return {"error": "LinkedIn API credentials not configured"}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{LINKEDIN_API_BASE}/organizationalEntityFollowerStatistics",
                    headers={"Authorization": f"Bearer {self._access_token}"},
                    params={
                        "q": "organizationalEntity",
                        "organization": f"urn:li:organization:{self._org_id}" if self._org_id else "",
                    },
                    timeout=10.0,
                )

                if resp.status_code == 200:
                    elements = resp.json().get("elements", [])
                    if elements:
                        metrics = elements[0]
                        return {
                            "platform": "linkedin",
                            "followers": metrics.get("followerCount", 0),
                            "impressions": metrics.get("impressionCount", 0),
                            "clicks": metrics.get("clickCount", 0),
                        }
        except Exception as exc:
            logger.error("LinkedIn account analytics error: %s", exc)

        return {"platform": "linkedin", "error": "Failed to retrieve analytics"}
