"""Tests for Social Media Automation module."""

import pytest
import tempfile
import os
from datetime import datetime, timezone

from integrations.social.base import SocialPost, PostResult, AnalyticsData
from integrations.social.calendar import ContentCalendar, CalendarEntry
from integrations.social.manager import SocialMediaManager


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_calendar.db")
        yield db_path


@pytest.fixture
def calendar(temp_db):
    return ContentCalendar(db_path=temp_db)


@pytest.fixture
def manager():
    return SocialMediaManager()


class TestCalendarEntry:
    def test_create_entry(self, calendar):
        entry = calendar.create(
            platform="twitter",
            content="Test post content",
        )
        assert entry.id
        assert entry.platform == "twitter"
        assert entry.content == "Test post content"
        assert entry.status == "draft"

    def test_get_entry(self, calendar):
        entry = calendar.create(platform="twitter", content="Test")
        retrieved = calendar.get(entry.id)
        assert retrieved is not None
        assert retrieved.id == entry.id
        assert retrieved.content == "Test"

    def test_list_entries(self, calendar):
        calendar.create(platform="twitter", content="Post 1")
        calendar.create(platform="linkedin", content="Post 2")
        calendar.create(platform="twitter", content="Post 3")

        all_entries = calendar.list_entries()
        assert len(all_entries) == 3

        twitter_only = calendar.list_entries(platform="twitter")
        assert len(twitter_only) == 2

    def test_update_entry(self, calendar):
        entry = calendar.create(platform="twitter", content="Original")
        updated = calendar.update(entry.id, content="Updated")
        assert updated.content == "Updated"

    def test_delete_entry(self, calendar):
        entry = calendar.create(platform="twitter", content="To delete")
        assert calendar.delete(entry.id) is True
        assert calendar.get(entry.id) is None

    def test_mark_published(self, calendar):
        entry = calendar.create(platform="twitter", content="To publish")
        published = calendar.mark_published(entry.id, post_id="12345", url="https://twitter.com/12345")
        assert published.status == "published"
        assert published.post_id == "12345"

    def test_mark_failed(self, calendar):
        entry = calendar.create(platform="twitter", content="To fail")
        failed = calendar.mark_failed(entry.id, error="API error")
        assert failed.status == "failed"
        assert failed.metadata.get("error") == "API error"

    def test_cancel_entry(self, calendar):
        entry = calendar.create(platform="twitter", content="To cancel")
        cancelled = calendar.cancel(entry.id)
        assert cancelled.status == "cancelled"

    def test_stats(self, calendar):
        calendar.create(platform="twitter", content="Draft")
        e1 = calendar.create(platform="twitter", content="Scheduled")
        calendar.update(e1.id, status="scheduled")
        e2 = calendar.create(platform="twitter", content="Published")
        calendar.mark_published(e2.id, "123")

        stats = calendar.stats()
        assert stats["total"] == 3
        assert stats["drafts"] == 1
        assert stats["scheduled"] == 1
        assert stats["published"] == 1


class TestSocialPost:
    def test_post_creation(self):
        post = SocialPost(
            content="Hello world",
            platform="twitter",
            hashtags=["test", "demo"],
        )
        assert post.content == "Hello world"
        assert post.platform == "twitter"
        assert len(post.hashtags) == 2

    def test_post_result(self):
        result = PostResult(
            success=True,
            post_id="12345",
            platform="twitter",
            url="https://twitter.com/12345",
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["post_id"] == "12345"

    def test_analytics_data(self):
        analytics = AnalyticsData(
            platform="twitter",
            post_id="12345",
            impressions=1000,
            likes=50,
            shares=10,
            comments=5,
        )
        analytics.engagement_rate = (analytics.likes + analytics.shares + analytics.comments) / analytics.impressions
        d = analytics.to_dict()
        assert d["impressions"] == 1000
        assert d["engagement_rate"] == 0.065


class TestSocialMediaManager:
    def test_register_adapter(self, manager):
        from integrations.social.base import SocialAdapter

        class MockAdapter(SocialAdapter):
            async def authenticate(self):
                return True

            async def draft_post(self, prompt, context=None):
                return SocialPost(content=prompt, platform="mock")

            async def schedule_post(self, post, scheduled_at):
                return PostResult(success=True, platform="mock")

            async def publish_post(self, post):
                return PostResult(success=True, platform="mock")

            async def get_analytics(self, post_id):
                return AnalyticsData(platform="mock", post_id=post_id)

            async def get_account_analytics(self, period="7d"):
                return {"platform": "mock"}

        adapter = MockAdapter(platform="mock", config={})
        manager.register_adapter(adapter)

        assert manager.get_adapter("mock") is not None
        assert len(manager.list_adapters()) == 1

    def test_stats(self, manager):
        stats = manager.stats()
        assert "calendar" in stats
        assert "adapters" in stats


class TestColdModeIntegration:
    def test_social_post_is_execute_action(self):
        from core.cold_mode import EXECUTE_ACTIONS
        assert "social_post" in EXECUTE_ACTIONS
        assert "social_schedule" in EXECUTE_ACTIONS

    def test_social_post_requires_approval(self):
        from core.cold_mode import ColdMode
        cold = ColdMode(enabled=True)
        ctx = ColdMode.build_context(
            action="social_post",
            permission="EXECUTE",
            confidence=0.8,
            fallback_script="echo rollback",
        )
        results = cold.evaluate(ctx)
        passed_checks = [r for r in results if r.passed]
        failed_checks = [r for r in results if not r.passed]
        assert len(passed_checks) >= 3


class TestOrchestratorIntent:
    def test_market_research_intent_exists(self):
        from agents.orchestrator import INTENT_PATTERNS
        assert "market_research" in INTENT_PATTERNS

    def test_market_research_routes_to_analyst(self):
        from agents.orchestrator import INTENT_PATTERNS
        import re

        patterns = INTENT_PATTERNS["market_research"]
        test_query = "analyze competitor landscape for AI startups"
        matched = any(re.search(p, test_query, re.I) for p in patterns)
        assert matched
