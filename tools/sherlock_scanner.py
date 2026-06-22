"""Username enumeration across 300+ platforms using Sherlock.

Requires: pip install sherlock-project
Runs as subprocess — no API keys needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class UsernameResult:
    username: str
    found: list[dict] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_checked: int = 0

    @property
    def found_count(self) -> int:
        return len(self.found)

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "found": self.found,
            "found_count": self.found_count,
            "total_checked": self.total_checked,
        }


async def scan_username(username: str, timeout: int = 120) -> UsernameResult:
    """Scan a username across 300+ platforms using Sherlock.

    Falls back to a simple HTTP check if sherlock is not installed.
    """
    sherlock_path = shutil.which("sherlock")
    if sherlock_path:
        return await _run_sherlock(username, timeout)

    logger.info("Sherlock not found — using built-in scanner for %s", username)
    return await _builtin_username_scan(username)


async def _run_sherlock(username: str, timeout: int) -> UsernameResult:
    """Execute sherlock as subprocess."""
    result = UsernameResult(username=username)
    try:
        proc = await asyncio.create_subprocess_exec(
            "sherlock", username,
            "--json", "-",
            "--timeout", str(timeout),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 10)

        if proc.returncode == 0 and stdout:
            try:
                data = json.loads(stdout.decode())
                for site, info in data.items():
                    if info.get("status") == "Claimed":
                        result.found.append({
                            "site": site,
                            "url": info.get("url_user", ""),
                            "status": "claimed",
                        })
                    else:
                        result.not_found.append(site)
                result.total_checked = len(result.found) + len(result.not_found)
            except json.JSONDecodeError:
                result.errors.append("Failed to parse sherlock output")
        else:
            err = stderr.decode().strip()[:500]
            result.errors.append(err or "sherlock returned non-zero")
    except FileNotFoundError:
        result.errors.append("sherlock binary not found")
    except asyncio.TimeoutError:
        result.errors.append(f"sherlock timed out after {timeout}s")
    except Exception as exc:
        result.errors.append(str(exc))

    return result


async def _builtin_username_scan(username: str) -> UsernameResult:
    """Lightweight username check against popular sites without sherlock."""
    import httpx

    result = UsernameResult(username=username)

    sites = {
        "github": f"https://github.com/{username}",
        "twitter": f"https://x.com/{username}",
        "instagram": f"https://www.instagram.com/{username}/",
        "linkedin": f"https://www.linkedin.com/in/{username}/",
        "reddit": f"https://www.reddit.com/user/{username}",
        "youtube": f"https://www.youtube.com/@{username}",
        "tiktok": f"https://www.tiktok.com/@{username}",
        "pinterest": f"https://www.pinterest.com/{username}/",
        "medium": f"https://medium.com/@{username}",
        "devto": f"https://dev.to/{username}",
        "gitlab": f"https://gitlab.com/{username}",
        "hackernews": f"https://news.ycombinator.com/user?id={username}",
        "keybase": f"https://keybase.io/{username}",
        "twitch": f"https://www.twitch.tv/{username}",
        "telegram": f"https://t.me/{username}",
    }

    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        for site, url in sites.items():
            try:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    result.found.append({"site": site, "url": url, "status": "claimed"})
                else:
                    result.not_found.append(site)
            except Exception:
                result.errors.append(f"{site}: timeout")

    result.total_checked = len(result.found) + len(result.not_found)
    return result
