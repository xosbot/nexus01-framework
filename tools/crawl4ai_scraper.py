"""Self-hosted LLM-friendly web scraper using Crawl4AI.

Replaces Firecrawl dependency for OSINT scraping. Runs on the SSD Node server.
Falls back to httpx + BeautifulSoup if Crawl4AI is unavailable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CRAWL4AI_TIMEOUT = 30
CRAWL4AI_URL = os.environ.get("CRAWL4AI_URL", "http://localhost:11235")


@dataclass
class ScrapeResult:
    url: str
    title: str = ""
    markdown: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "httpx"
    success: bool = True
    error: str = ""


async def crawl4ai_scrape(url: str) -> ScrapeResult:
    """Scrape a single URL via Crawl4AI local API, fallback to httpx."""
    try:
        async with httpx.AsyncClient(timeout=CRAWL4AI_TIMEOUT) as client:
            resp = await client.post(
                f"{CRAWL4AI_URL}/v1/scrape",
                json={"url": url, "formats": ["markdown", "text"], "only_main_content": True},
            )
            resp.raise_for_status()
            data = resp.json()

            return ScrapeResult(
                url=url,
                title=data.get("title", ""),
                markdown=data.get("markdown", ""),
                text=data.get("text", "")[:8000],
                links=data.get("links", [])[:50],
                metadata=data.get("metadata", {}),
                source="crawl4ai",
            )
    except Exception as exc:
        logger.debug("Crawl4AI unavailable for %s: %s — falling back to httpx", url, exc)
        return await httpx_fallback_scrape(url)


async def crawl4ai_batch_scrape(urls: list[str]) -> list[ScrapeResult]:
    """Scrape multiple URLs concurrently."""
    import asyncio
    tasks = [crawl4ai_scrape(url) for url in urls[:8]]
    return list(await asyncio.gather(*tasks))


async def httpx_fallback_scrape(url: str) -> ScrapeResult:
    """Lightweight fallback scraper using httpx + BeautifulSoup."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; NEXUS-01 OSINT)"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            title = soup.title.string.strip() if soup.title else ""
            text = soup.get_text(separator="\n", strip=True)[:5000]
            links = [a.get("href", "") for a in soup.find_all("a", href=True)[:50]]

            return ScrapeResult(url=url, title=title, text=text, links=links, source="httpx")
    except Exception as exc:
        return ScrapeResult(url=url, success=False, error=str(exc), source="httpx")


async def crawl4ai_search(query: str, limit: int = 10) -> list[dict]:
    """Search via Crawl4AI or DuckDuckGo fallback."""
    try:
        async with httpx.AsyncClient(timeout=CRAWL4AI_TIMEOUT) as client:
            resp = await client.post(
                f"{CRAWL4AI_URL}/v1/search",
                json={"query": query, "limit": limit},
            )
            resp.raise_for_status()
            raw = resp.json().get("data", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("description", ""),
                    "source": "crawl4ai",
                }
                for r in raw
            ]
    except Exception:
        return await duckduckgo_search(query, limit)


async def duckduckgo_search(query: str, limit: int = 10) -> list[dict]:
    """DuckDuckGo HTML search fallback."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for r in soup.select(".result")[:limit]:
                title_el = r.select_one(".result__title")
                snippet_el = r.select_one(".result__snippet")
                link_el = r.select_one(".result__url")
                if title_el:
                    results.append({
                        "title": title_el.get_text(strip=True),
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                        "url": link_el.get_text(strip=True) if link_el else "",
                        "source": "duckduckgo",
                    })
            return results
    except Exception as exc:
        return [{"error": str(exc)}]


def format_osint_report(query: str, search_results: list[dict], pages: list[ScrapeResult]) -> dict:
    """Format scraped data into a structured OSINT report."""
    successful = [p for p in pages if p.success]
    sources = []
    for p in successful:
        sources.append({
            "url": p.url,
            "title": p.title,
            "source_engine": p.source,
            "content_length": len(p.markdown or p.text),
        })

    return {
        "query": query,
        "search_results_count": len(search_results),
        "pages_scraped": len(successful),
        "sources": sources,
        "engines_used": list({r.get("source", "unknown") for r in search_results} | {p.source for p in successful}),
    }
