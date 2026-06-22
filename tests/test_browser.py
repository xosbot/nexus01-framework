"""Tests for browser automation tool."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from tools.browser import BrowserTool, BrowserResult


class TestBrowserResult:
    def test_to_dict(self):
        r = BrowserResult(url="https://example.com", title="Test", success=True)
        d = r.to_dict()
        assert d["url"] == "https://example.com"
        assert d["title"] == "Test"
        assert d["success"] is True

    def test_error_result(self):
        r = BrowserResult(url="https://fail.test", success=False, error="timeout")
        d = r.to_dict()
        assert d["success"] is False
        assert "timeout" in d["error"]


class TestBrowserTool:
    @pytest.mark.asyncio
    async def test_navigate_playwright_unavailable(self):
        tool = BrowserTool()
        with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
            result = await tool.navigate("https://example.com")
            assert result.success is False
            assert "not installed" in result.error.lower() or "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_extract_text_playwright_unavailable(self):
        tool = BrowserTool()
        with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
            result = await tool.extract_text("https://example.com")
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_screenshot_playwright_unavailable(self):
        tool = BrowserTool()
        with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
            result = await tool.screenshot_page("https://example.com")
            assert result == ""

    @pytest.mark.asyncio
    async def test_close_when_not_initialized(self):
        tool = BrowserTool()
        await tool.close()
        assert tool._available is False


class TestBrowserFunctions:
    @pytest.mark.asyncio
    async def test_browser_navigate_error(self):
        with patch("tools.browser.get_browser_tool") as mock_get:
            mock_tool = AsyncMock()
            mock_tool.navigate.return_value = BrowserResult(
                url="https://fail.test", success=False, error="connection refused"
            )
            mock_get.return_value = mock_tool
            from tools.browser import browser_navigate
            result = await browser_navigate("https://fail.test")
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_browser_scrape_error(self):
        with patch("tools.browser.get_browser_tool") as mock_get:
            mock_tool = AsyncMock()
            mock_tool.extract_text.return_value = "Error: timeout"
            mock_get.return_value = mock_tool
            from tools.browser import browser_scrape
            result = await browser_scrape("https://fail.test")
            assert "Error" in result

    @pytest.mark.asyncio
    async def test_browser_screenshot_error(self):
        with patch("tools.browser.get_browser_tool") as mock_get:
            mock_tool = AsyncMock()
            mock_tool.screenshot_page.return_value = ""
            mock_get.return_value = mock_tool
            from tools.browser import browser_screenshot
            result = await browser_screenshot("https://fail.test")
            assert "failed" in result.lower()
