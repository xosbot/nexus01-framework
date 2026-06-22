"""Email account enumeration using holehe.

Checks which platforms an email is registered on.
Requires: pip install holehe
Falls back to built-in checks if holehe is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EmailCheckResult:
    email: str
    accounts: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    source: str = "holehe"

    @property
    def account_count(self) -> int:
        return len(self.accounts)

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "accounts": self.accounts,
            "account_count": self.account_count,
            "source": self.source,
        }


async def check_email(email: str, timeout: int = 60) -> EmailCheckResult:
    """Check which platforms an email is registered on.

    Uses holehe if available, otherwise built-in HTTP checks.
    """
    holehe_path = shutil.which("holehe")
    if holehe_path:
        return await _run_holehe(email, timeout)

    logger.info("holehe not installed — using built-in email checks for %s", email)
    return await _builtin_email_check(email)


async def _run_holehe(email: str, timeout: int) -> EmailCheckResult:
    """Execute holehe as subprocess."""
    result = EmailCheckResult(email=email)
    try:
        proc = await asyncio.create_subprocess_exec(
            "holehe", email,
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if proc.returncode == 0 and stdout:
            import json
            try:
                data = json.loads(stdout.decode())
                for entry in data:
                    if entry.get("exists") or entry.get("status") == "exists":
                        result.accounts.append({
                            "site": entry.get("name", "unknown"),
                            "url": entry.get("url", ""),
                            "status": "exists",
                        })
            except json.JSONDecodeError:
                result.errors.append("Failed to parse holehe output")
        else:
            err = stderr.decode().strip()[:300]
            result.errors.append(err or "holehe returned non-zero")
    except FileNotFoundError:
        result.errors.append("holehe binary not found")
    except asyncio.TimeoutError:
        result.errors.append(f"holehe timed out after {timeout}s")
    except Exception as exc:
        result.errors.append(str(exc))

    return result


async def _builtin_email_check(email: str) -> EmailCheckResult:
    """Lightweight email checks against common platforms via HTTP."""
    import httpx

    result = EmailCheckResult(email=email, source="builtin")

    username = email.split("@")[0]

    platforms = [
        ("GitHub", f"https://api.github.com/search/users?q={username}"),
        ("Gravatar", f"https://en.gravatar.com/{username}.json"),
    ]

    async with httpx.AsyncClient(timeout=8.0) as client:
        for name, url in platforms:
            try:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if resp.status_code == 200:
                    data = resp.json()

                    if name == "GitHub":
                        items = data.get("items", [])
                        for item in items:
                            if item.get("email", "").lower() == email.lower():
                                result.accounts.append({
                                    "site": "GitHub",
                                    "url": item.get("html_url", ""),
                                    "status": "confirmed",
                                })
                                break

                    elif name == "Gravatar":
                        if data.get("entry"):
                            result.accounts.append({
                                "site": "Gravatar",
                                "url": f"https://gravatar.com/{username}",
                                "status": "exists",
                            })
            except Exception:
                pass

    return result


async def check_email_breach(email: str) -> dict:
    """Check HaveIBeenPwned for breaches (requires HIBP_API_KEY)."""
    import os
    import httpx

    api_key = os.environ.get("HIBP_API_KEY", "")
    if not api_key:
        return {"error": "HIBP_API_KEY not set", "breaches": []}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
                headers={
                    "hibp-api-key": api_key,
                    "user-agent": "NEXUS-01-OSINT",
                },
                params={"truncateResponse": "false"},
            )
            if resp.status_code == 200:
                breaches = resp.json()
                return {
                    "email": email,
                    "breach_count": len(breaches),
                    "breaches": [
                        {
                            "name": b.get("Name"),
                            "date": b.get("BreachDate"),
                            "data_classes": b.get("DataClasses", []),
                        }
                        for b in breaches
                    ],
                }
            elif resp.status_code == 404:
                return {"email": email, "breach_count": 0, "breaches": []}
            else:
                return {"error": f"HIBP returned {resp.status_code}", "breaches": []}
    except Exception as exc:
        return {"error": str(exc), "breaches": []}
