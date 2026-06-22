"""Browser automation tool using Playwright for OSINT and agent tasks.

Provides headless browser capabilities:
- Navigate, click, fill forms, extract rendered content
- Screenshot capture for visual evidence
- SPA/dynamic content rendering
- Session persistence for multi-step workflows

Requires: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

BROWSER_TIMEOUT = 30000
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class BrowserResult:
    url: str
    title: str = ""
    content: str = ""
    markdown: str = ""
    screenshot_path: str = ""
    links: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str = ""
    actions_taken: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "content_length": len(self.content),
            "markdown_length": len(self.markdown),
            "screenshot": self.screenshot_path,
            "links_found": len(self.links),
            "actions_taken": self.actions_taken,
            "success": self.success,
            "error": self.error,
        }


class BrowserTool:
    """Playwright-based browser automation for OSINT and agent tasks."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._available = False

    async def _ensure_browser(self) -> bool:
        if self._browser and self._available:
            return True
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-extensions",
                ],
            )
            self._available = True
            return True
        except Exception as exc:
            logger.warning("Playwright not available: %s", exc)
            self._available = False
            return False

    async def navigate(
        self,
        url: str,
        wait_for: str = "domcontentloaded",
        timeout: int = BROWSER_TIMEOUT,
    ) -> BrowserResult:
        """Navigate to a URL and extract rendered content."""
        if not await self._ensure_browser():
            return BrowserResult(url=url, success=False, error="Playwright not installed")

        result = BrowserResult(url=url)
        try:
            context = await self._browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                java_script_enabled=True,
            )
            page = await context.new_page()

            response = await page.goto(url, wait_until=wait_for, timeout=timeout)
            if response:
                result.metadata["status"] = response.status

            result.title = await page.title()
            result.content = await page.content()

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(result.content, "html.parser")

            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            result.markdown = soup.get_text(separator="\n", strip=True)[:10000]

            result.links = list({
                a.get("href", "")
                for a in soup.find_all("a", href=True)
                if a.get("href", "").startswith("http")
            })[:50]

            await context.close()
        except Exception as exc:
            result.success = False
            result.error = str(exc)[:500]
            logger.warning("Browser navigate failed for %s: %s", url, exc)

        return result

    async def scrape_with_actions(
        self,
        url: str,
        actions: list[dict[str, Any]] | None = None,
        extract_selector: str | None = None,
        screenshot: bool = False,
    ) -> BrowserResult:
        """Navigate, perform actions, then extract content.

        actions: list of {"type": "click"|"fill"|"wait"|"scroll", "selector": "...", "value": "..."}
        extract_selector: CSS selector to extract specific content
        screenshot: capture screenshot to temp file
        """
        if not await self._ensure_browser():
            return BrowserResult(url=url, success=False, error="Playwright not installed")

        result = BrowserResult(url=url)
        try:
            context = await self._browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
            result.title = await page.title()

            for action in (actions or []):
                action_type = action.get("type", "")
                selector = action.get("selector", "")
                value = action.get("value", "")
                try:
                    if action_type == "click" and selector:
                        await page.click(selector, timeout=5000)
                        result.actions_taken.append(f"click:{selector}")
                    elif action_type == "fill" and selector:
                        await page.fill(selector, value, timeout=5000)
                        result.actions_taken.append(f"fill:{selector}")
                    elif action_type == "wait" and selector:
                        await page.wait_for_selector(selector, timeout=10000)
                        result.actions_taken.append(f"wait:{selector}")
                    elif action_type == "scroll":
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        result.actions_taken.append("scroll:bottom")
                    elif action_type == "wait_time":
                        await page.wait_for_timeout(int(value) if value else 2000)
                        result.actions_taken.append(f"wait:{value}ms")
                except Exception as exc:
                    result.actions_taken.append(f"error:{action_type}:{exc}")

            if extract_selector:
                elements = await page.query_selector_all(extract_selector)
                texts = []
                for el in elements[:20]:
                    text = await el.inner_text()
                    if text.strip():
                        texts.append(text.strip())
                result.markdown = "\n---\n".join(texts)[:10000]
            else:
                content = await page.content()
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(content, "html.parser")
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                result.markdown = soup.get_text(separator="\n", strip=True)[:10000]

            result.content = await page.content()
            result.links = list({
                a.get("href", "")
                for a in (await page.query_selector_all("a[href]"))
                if a
            })[:50]

            if screenshot:
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                await page.screenshot(path=tmp.name, full_page=False)
                result.screenshot_path = tmp.name
                result.actions_taken.append(f"screenshot:{tmp.name}")

            await context.close()
        except Exception as exc:
            result.success = False
            result.error = str(exc)[:500]

        return result

    async def extract_text(self, url: str, selector: str = "body") -> str:
        """Quick text extraction from a URL."""
        result = await self.navigate(url)
        if not result.success:
            return f"Error: {result.error}"
        if selector != "body":
            try:
                context = await self._browser.new_context()
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
                elements = await page.query_selector_all(selector)
                texts = [await el.inner_text() for el in elements[:10]]
                await context.close()
                return "\n".join(t.strip() for t in texts if t.strip())[:8000]
            except Exception:
                pass
        return result.markdown[:8000]

    async def screenshot_page(self, url: str, path: str = "") -> str:
        """Capture a screenshot of a page."""
        result = await self.scrape_with_actions(url, screenshot=True, actions=[
            {"type": "wait_time", "value": "3000"}
        ])
        if result.screenshot_path:
            if path:
                import shutil
                shutil.move(result.screenshot_path, path)
                return path
            return result.screenshot_path
        return ""

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._available = False


_browser_tool: BrowserTool | None = None


def get_browser_tool() -> BrowserTool:
    global _browser_tool
    if _browser_tool is None:
        _browser_tool = BrowserTool()
    return _browser_tool


async def browser_navigate(url: str) -> str:
    tool = get_browser_tool()
    result = await tool.navigate(url)
    return result.markdown[:6000] if result.success else f"Error: {result.error}"


async def browser_scrape(url: str, selector: str = "body") -> str:
    tool = get_browser_tool()
    return await tool.extract_text(url, selector)


async def browser_interact(
    url: str,
    actions: str = "[]",
    extract: str = "",
) -> str:
    import json
    tool = get_browser_tool()
    action_list = json.loads(actions) if actions else []
    result = await tool.scrape_with_actions(url, actions=action_list, extract_selector=extract or None)
    if result.success:
        output = f"Title: {result.title}\n\n"
        if result.markdown:
            output += result.markdown[:5000]
        if result.actions_taken:
            output += f"\n\nActions: {', '.join(result.actions_taken)}"
        return output
    return f"Error: {result.error}"


async def browser_screenshot(url: str) -> str:
    tool = get_browser_tool()
    path = await tool.screenshot_page(url)
    return f"Screenshot saved: {path}" if path else "Screenshot failed"
