"""Firecrawl-enhanced OSINT tool — structured scraping with fallback."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

FIRECRAWL_TIMEOUT = 20


@dataclass
class ScrapedPage:
    url: str
    title: str = ""
    markdown: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "httpx"
    success: bool = True
    error: str = ""


async def firecrawl_scrape(url: str, api_key: str = "") -> ScrapedPage:
    key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        return await httpx_scrape(url)

    try:
        async with httpx.AsyncClient(timeout=FIRECRAWL_TIMEOUT) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v1/scrape",
                json={
                    "url": url,
                    "formats": ["markdown", "text"],
                    "onlyMainContent": True,
                },
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})

            markdown = data.get("markdown", "")
            text = data.get("text", "")
            title = data.get("metadata", {}).get("title", "")
            links = [link.get("href", "") for link in data.get("links", []) if link.get("href")]

            return ScrapedPage(
                url=url,
                title=title,
                markdown=markdown,
                text=text[:8000],
                links=links[:50],
                metadata=data.get("metadata", {}),
                source="firecrawl",
            )
    except Exception as exc:
        logger.warning("Firecrawl scrape failed for %s: %s — falling back to httpx", url, exc)
        return await httpx_scrape(url)


async def httpx_scrape(url: str) -> ScrapedPage:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            title = soup.title.string.strip() if soup.title else ""
            text = soup.get_text(separator="\n", strip=True)[:5000]
            links = [a.get("href", "") for a in soup.find_all("a", href=True)[:50]]

            return ScrapedPage(
                url=url,
                title=title,
                text=text,
                links=links,
                source="httpx",
            )
    except Exception as exc:
        return ScrapedPage(url=url, success=False, error=str(exc), source="httpx")


async def firecrawl_search(query: str, api_key: str = "", limit: int = 10) -> list[dict]:
    key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
    if not key:
        return await _duckduckgo_search(query, limit)

    try:
        async with httpx.AsyncClient(timeout=FIRECRAWL_TIMEOUT) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v1/search",
                json={"query": query, "limit": limit, "scrapeOptions": {"formats": ["markdown"]}},
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            raw = resp.json().get("data", [])
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("description", ""),
                    "markdown": r.get("markdown", "")[:3000],
                    "source": "firecrawl",
                }
                for r in raw
            ]
    except Exception as exc:
        logger.warning("Firecrawl search failed: %s — falling back to DuckDuckGo", exc)
        return await _duckduckgo_search(query, limit)


async def _duckduckgo_search(query: str, limit: int = 10) -> list[dict]:
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


def format_report(query: str, search_results: list[dict], pages: list[ScrapedPage]) -> dict:
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
