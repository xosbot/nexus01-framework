"""Twitter/X adapter — official API v2 only."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from integrations.social.base import SocialAdapter, SocialPost, PostResult, AnalyticsData

logger = logging.getLogger(__name__)

TWITTER_API_BASE = "https://api.twitter.com/2"
TWITTER_UPLOAD_BASE = "https://upload.twitter.com/1.1"


class TwitterAdapter(SocialAdapter):
    """Twitter/X adapter using official API v2.

    Required config:
        - api_key: Twitter API key
        - api_secret: Twitter API secret
        - access_token: OAuth access token
        - access_token_secret: OAuth access token secret
        - bearer_token: Bearer token for app-only auth
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__("twitter", config)
        self._bearer_token = config.get("bearer_token", "")
        self._client = None

    async def authenticate(self) -> bool:
        if not self._bearer_token:
            logger.warning("Twitter: No bearer token configured")
            return False

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{TWITTER_API_BASE}/users/me",
                    headers={"Authorization": f"Bearer {self._bearer_token}"},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    logger.info("Twitter: Authenticated as @%s", data.get("username", "unknown"))
                    return True
                logger.warning("Twitter: Auth failed: %s", resp.status_code)
                return False
        except Exception as exc:
            logger.error("Twitter: Auth error: %s", exc)
            return False

    async def draft_post(self, prompt: str, context: dict | None = None) -> SocialPost:
        post = SocialPost(
            content=prompt[:280],
            platform="twitter",
            metadata={"draft_reason": "user_request", "original_prompt": prompt},
        )
        return post

    async def schedule_post(self, post: SocialPost, scheduled_at: datetime) -> PostResult:
        if not self._bearer_token:
            return PostResult(
                success=False,
                platform="twitter",
                error="Twitter API credentials not configured",
            )

        try:
            payload = {
                "text": post.content,
                "scheduled_at": scheduled_at.isoformat(),
            }

            if post.media_urls:
                payload["media"] = {"media_ids": []}

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TWITTER_API_BASE}/tweets",
                    headers={
                        "Authorization": f"Bearer {self._bearer_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=30.0,
                )

                if resp.status_code in (200, 201):
                    data = resp.json().get("data", {})
                    return PostResult(
                        success=True,
                        post_id=data.get("id", ""),
                        platform="twitter",
                        scheduled=True,
                        scheduled_at=scheduled_at,
                    )
                else:
                    error = resp.json().get("detail", resp.text[:200])
                    return PostResult(
                        success=False,
                        platform="twitter",
                        error=f"Schedule failed: {error}",
                    )
        except Exception as exc:
            return PostResult(
                success=False,
                platform="twitter",
                error=str(exc),
            )

    async def publish_post(self, post: SocialPost) -> PostResult:
        if not self._bearer_token:
            return PostResult(
                success=False,
                platform="twitter",
                error="Twitter API credentials not configured",
            )

        try:
            payload = {"text": post.content}

            if post.media_urls:
                payload["media"] = {"media_ids": []}

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TWITTER_API_BASE}/tweets",
                    headers={
                        "Authorization": f"Bearer {self._bearer_token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=30.0,
                )

                if resp.status_code in (200, 201):
                    data = resp.json().get("data", {})
                    post_id = data.get("id", "")
                    return PostResult(
                        success=True,
                        post_id=post_id,
                        platform="twitter",
                        url=f"https://twitter.com/i/status/{post_id}",
                    )
                else:
                    error = resp.json().get("detail", resp.text[:200])
                    return PostResult(
                        success=False,
                        platform="twitter",
                        error=f"Publish failed: {error}",
                    )
        except Exception as exc:
            return PostResult(
                success=False,
                platform="twitter",
                error=str(exc),
            )

    async def get_analytics(self, post_id: str) -> AnalyticsData:
        analytics = AnalyticsData(platform="twitter", post_id=post_id)

        if not self._bearer_token:
            return analytics

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{TWITTER_API_BASE}/tweets/{post_id}",
                    headers={"Authorization": f"Bearer {self._bearer_token}"},
                    params={"tweet.fields": "public_metrics"},
                    timeout=10.0,
                )

                if resp.status_code == 200:
                    metrics = resp.json().get("data", {}).get("public_metrics", {})
                    analytics.impressions = metrics.get("impression_count", 0)
                    analytics.likes = metrics.get("like_count", 0)
                    analytics.shares = metrics.get("retweet_count", 0) + metrics.get("quote_count", 0)
                    analytics.comments = metrics.get("reply_count", 0)
                    analytics.clicks = metrics.get("url_link_clicks", 0)
                    analytics.engagements = (
                        analytics.likes + analytics.shares + analytics.comments + analytics.clicks
                    )
                    if analytics.impressions > 0:
                        analytics.engagement_rate = analytics.engagements / analytics.impressions
        except Exception as exc:
            logger.error("Twitter analytics error: %s", exc)

        return analytics

    async def get_account_analytics(self, period: str = "7d") -> dict[str, Any]:
        if not self._bearer_token:
            return {"error": "Twitter API credentials not configured"}

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{TWITTER_API_BASE}/users/me",
                    headers={"Authorization": f"Bearer {self._bearer_token}"},
                    params={"user.fields": "public_metrics"},
                    timeout=10.0,
                )

                if resp.status_code == 200:
                    metrics = resp.json().get("data", {}).get("public_metrics", {})
                    return {
                        "platform": "twitter",
                        "followers": metrics.get("followers_count", 0),
                        "following": metrics.get("following_count", 0),
                        "tweets": metrics.get("tweet_count", 0),
                        "listed": metrics.get("listed_count", 0),
                    }
        except Exception as exc:
            logger.error("Twitter account analytics error: %s", exc)

        return {"platform": "twitter", "error": "Failed to retrieve analytics"}
