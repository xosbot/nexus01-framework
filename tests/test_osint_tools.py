"""Tests for OSINT tools — crawl4ai, sherlock, theharvester, holehe, darkweb."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from tools.crawl4ai_scraper import (
    crawl4ai_scrape, crawl4ai_search, duckduckgo_search,
    httpx_fallback_scrape, format_osint_report, ScrapeResult,
)
from tools.sherlock_scanner import scan_username, UsernameResult
from tools.theharvester import harvest_domain, _parse_harvester_output, HarvestResult
from tools.holehe_checker import check_email, EmailCheckResult
from tools.darkweb_monitor import search_darkweb, DarkWebResult


class TestCrawl4AIScraper:
    @pytest.mark.asyncio
    async def test_scrape_fallback_to_httpx(self):
        with patch("httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "<html><head><title>Test</title></head><body><p>Hello</p></body></html>"
            mock_resp.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            result = await crawl4ai_scrape("https://example.com")
            assert result.success is True
            assert result.title == "Test"
            assert result.source == "httpx"

    @pytest.mark.asyncio
    async def test_search_fallback_to_duckduckgo(self):
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(side_effect=Exception("Connection refused"))

            mock_resp = MagicMock()
            mock_resp.text = """
            <html><body>
            <div class="result">
                <a class="result__title">Test Result</a>
                <a class="result__snippet">A test snippet</a>
                <a class="result__url">https://example.com</a>
            </div>
            </body></html>
            """
            mock_client.return_value.get = AsyncMock(return_value=mock_resp)

            results = await crawl4ai_search("test query")
            assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_scrape_error_returns_failed(self):
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value.post = AsyncMock(side_effect=Exception("timeout"))
            mock_client.return_value.get = AsyncMock(side_effect=Exception("timeout"))

            result = await crawl4ai_scrape("https://invalid.test")
            assert result.success is False
            assert "timeout" in result.error

    def test_format_osint_report(self):
        pages = [ScrapeResult(url="https://a.com", title="A", success=True, source="httpx")]
        report = format_osint_report("test", [{"source": "ddg"}], pages)
        assert report["query"] == "test"
        assert report["pages_scraped"] == 1
        assert "httpx" in report["engines_used"]


class TestSherlockScanner:
    @pytest.mark.asyncio
    async def test_builtin_scan_finds_github(self):
        with patch("tools.sherlock_scanner.shutil.which", return_value=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
                mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value.get = AsyncMock(return_value=mock_resp)

                result = await scan_username("testuser")
                assert isinstance(result, UsernameResult)
                assert result.username == "testuser"
                assert result.total_checked > 0

    @pytest.mark.asyncio
    async def test_builtin_scan_404_not_found(self):
        with patch("tools.sherlock_scanner.shutil.which", return_value=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
                mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value.get = AsyncMock(return_value=mock_resp)

                result = await scan_username("zzznonexistentuser99999")
                assert result.found_count == 0

    def test_username_result_to_dict(self):
        r = UsernameResult(username="test", total_checked=5)
        d = r.to_dict()
        assert d["username"] == "test"
        assert d["total_checked"] == 5


class TestTheHarvester:
    def test_parse_harvester_output(self):
        output = """
        --------------------
        Emails found:
        --------------------
        admin@example.com
        info@example.com

        --------------------
        Hosts found:
        --------------------
        mail.example.com
        www.example.com
        api.example.com

        --------------------
        Ips found:
        --------------------
        1.2.3.4
        5.6.7.8
        """
        result = _parse_harvester_output("example.com", output)
        assert "admin@example.com" in result.emails
        assert len(result.subdomains) == 3
        assert "1.2.3.4" in result.ips

    @pytest.mark.asyncio
    async def test_builtin_domain_recon_crtsh(self):
        with patch("tools.theharvester.shutil.which", return_value=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = [
                {"name_value": "www.example.com\nadmin@example.com"},
                {"name_value": "mail.example.com"},
            ]
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
                mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value.get = AsyncMock(return_value=mock_resp)

                result = await harvest_domain("example.com")
                assert "crt.sh" in result.sources_used
                assert "www.example.com" in result.subdomains

    def test_harvest_result_to_dict(self):
        r = HarvestResult(query="example.com", emails=["a@b.com"], subdomains=["x.a.com"])
        d = r.to_dict()
        assert d["query"] == "example.com"
        assert d["summary"]["emails_found"] == 1


class TestHoleheChecker:
    @pytest.mark.asyncio
    async def test_builtin_email_check(self):
        with patch("tools.holehe_checker.shutil.which", return_value=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"items": []}
            with patch("httpx.AsyncClient") as mock_client:
                mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
                mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value.get = AsyncMock(return_value=mock_resp)

                result = await check_email("test@example.com")
                assert isinstance(result, EmailCheckResult)
                assert result.email == "test@example.com"

    def test_email_check_result_to_dict(self):
        r = EmailCheckResult(email="a@b.com", accounts=[{"site": "GitHub"}])
        d = r.to_dict()
        assert d["account_count"] == 1


class TestDarkwebMonitor:
    @pytest.mark.asyncio
    async def test_stub_when_disabled(self):
        with patch.dict("os.environ", {"DARKWEB_ENABLED": ""}, clear=False):
            result = await search_darkweb("test")
            assert result.is_stub is True
            assert "disabled" in result.errors[0].lower()

    def test_darkweb_result_to_dict(self):
        r = DarkWebResult(query="test")
        d = r.to_dict()
        assert d["is_stub"] is True
        assert "Phase 4" in d["note"]
