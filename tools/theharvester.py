"""Domain and email recon using theHarvester.

Requires: pip install theHarvester
Runs as subprocess — uses public sources (Bing, DuckDuckGo, crt.sh, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class HarvestResult:
    query: str
    query_type: str = "domain"
    emails: list[str] = field(default_factory=list)
    subdomains: list[str] = field(default_factory=list)
    ips: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "query_type": self.query_type,
            "emails": self.emails,
            "subdomains": self.subdomains,
            "ips": self.ips,
            "hosts": self.hosts,
            "sources_used": self.sources_used,
            "summary": {
                "emails_found": len(self.emails),
                "subdomains_found": len(self.subdomains),
                "ips_found": len(self.ips),
            },
        }


async def harvest_domain(domain: str, source: str = "all") -> HarvestResult:
    """Run theHarvester against a domain.

    Sources: bing, google, duckduckgo, crtsh, virustotal, urlscan, etc.
    """
    result = HarvestResult(query=domain, query_type="domain")

    harvester_path = shutil.which("theHarvester")
    if not harvester_path:
        logger.info("theHarvester not installed — using built-in domain recon for %s", domain)
        return await _builtin_domain_recon(domain)

    try:
        proc = await asyncio.create_subprocess_exec(
            "theHarvester",
            "-d", domain,
            "-b", source,
            "-f", "/dev/stdout",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = stdout.decode(errors="replace")

        result = _parse_harvester_output(domain, output)
        if stderr.decode().strip():
            result.errors.append(stderr.decode().strip()[:300])
    except FileNotFoundError:
        result.errors.append("theHarvester binary not found")
    except asyncio.TimeoutError:
        result.errors.append("theHarvester timed out after 60s")
    except Exception as exc:
        result.errors.append(str(exc))

    return result


def _parse_harvester_output(domain: str, output: str) -> HarvestResult:
    """Parse theHarvester text output."""
    result = HarvestResult(query=domain, query_type="domain")
    section = None

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        if "Emails" in line or "emails found" in line.lower():
            section = "emails"
            continue
        elif "Hosts" in line or "hosts found" in line.lower():
            section = "hosts"
            continue
        elif "Ips" in line or "IPs found" in line.lower():
            section = "ips"
            continue

        if section == "emails" and "@" in line:
            result.emails.append(line)
        elif section == "hosts" and line:
            result.hosts.append(line)
        elif section == "ips" and line:
            result.ips.append(line)

    result.emails = list(set(result.emails))
    result.hosts = list(set(result.hosts))
    result.ips = list(set(result.ips))
    result.subdomains = [h for h in result.hosts if domain in h]

    return result


async def _builtin_domain_recon(domain: str) -> HarvestResult:
    """Built-in domain recon without theHarvester — crt.sh + DNS."""
    import httpx

    result = HarvestResult(query=domain, query_type="domain")

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(
                "https://crt.sh/",
                params={"q": f"%.{domain}", "output": "json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                subdomains = set()
                emails = set()
                for entry in data:
                    name = entry.get("name_value", "")
                    for line in name.split("\n"):
                        line = line.strip().lower()
                        if line.endswith(f".{domain}") or line == domain:
                            subdomains.add(line)
                        elif "@" in line:
                            emails.add(line)
                result.subdomains = sorted(subdomains)
                result.emails = sorted(emails)
                result.sources_used.append("crt.sh")
        except Exception as exc:
            result.errors.append(f"crt.sh failed: {exc}")

    try:
        import socket
        ips = socket.getaddrinfo(domain, None)
        unique_ips = list({addr[4][0] for addr in ips})
        result.ips = unique_ips
        result.sources_used.append("dns")
    except Exception as exc:
        result.errors.append(f"DNS lookup failed: {exc}")

    return result
