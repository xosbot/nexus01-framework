"""OSINT Agent — multi-tool intelligence gathering pipeline.

Routes queries to specialized tools:
- Web search + scraping: Crawl4AI (self-hosted) → httpx fallback
- Username enumeration: Sherlock (300+ platforms)
- Domain/email recon: theHarvester + crt.sh
- Email account checks: holehe + HaveIBeenPwned
- Dark web: OnionSearch (Phase 4 stub)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from agents.base import BaseAgent
from core.bus import Message

logger = logging.getLogger(__name__)


@dataclass
class OSINTReport:
    query: str = ""
    summary: str = ""
    key_findings: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    recommended_actions: list[str] = field(default_factory=list)
    raw_analysis: str = ""
    engines_used: list[str] = field(default_factory=list)
    sub_reports: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "summary": self.summary,
            "key_findings": self.key_findings,
            "sources": self.sources,
            "confidence": self.confidence,
            "recommended_actions": self.recommended_actions,
            "engines_used": self.engines_used,
            "sub_reports": {k: v for k, v in self.sub_reports.items() if isinstance(v, dict)},
            "status": "complete",
        }

    def format_telegram(self) -> str:
        lines = [f"\U0001f50d *OSINT Report: {self.query}*\n"]

        if self.key_findings:
            lines.append("*Key Findings:*")
            for i, f in enumerate(self.key_findings[:5], 1):
                lines.append(f"  {i}. {f}")
            lines.append("")

        if self.sources:
            lines.append(f"*Sources:* {len(self.sources)} pages analyzed")
            for s in self.sources[:3]:
                title = s.get("title", "Untitled")[:50]
                lines.append(f"  \u2022 [{title}]({s.get('url', '')})")
            lines.append("")

        lines.append(f"*Confidence:* {self.confidence:.0%}")
        lines.append(f"*Engines:* {', '.join(self.engines_used)}")

        if self.recommended_actions:
            lines.append("\n*Next Steps:*")
            for a in self.recommended_actions[:3]:
                lines.append(f"  \u2022 {a}")

        return "\n".join(lines)


SYNTHESIS_PROMPT = """Analyze these OSINT results about: {query}

Search results:
{search_text}

Scraped content:
{scraped_text}

Tool results:
{tool_text}

Return a structured report with these fields:
- summary: 2-3 sentence executive summary
- key_findings: list of 3-5 most important findings
- confidence: float 0-1 based on source quality and consistency
- recommended_actions: list of 2-3 next steps for deeper investigation

Be specific. Cite URLs when referencing findings."""


def _classify_query(query: str) -> list[str]:
    """Classify a query into OSINT tool categories."""
    import re
    q = query.lower()
    tools = []

    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    if re.search(email_pattern, q):
        tools.append("email")
        if "breach" in q or "pwned" in q or "leaked" in q:
            tools.append("breach")

    username_pattern = r'@\w{3,}'
    if re.search(username_pattern, q) or "username" in q or "user profile" in q or "social media" in q:
        tools.append("username")

    domain_pattern = r'\b\w+\.\w{2,}\b'
    if re.search(domain_pattern, q) and any(w in q for w in ["domain", "site", "website", "subdomain", "dns", "whois", "recon"]):
        tools.append("domain")

    if any(w in q for w in ["domain", "site", "website", "subdomain", "dns", "whois", "recon", "company", "organization"]):
        tools.append("domain")

    if any(w in q for w in ["breach", "leak", "pwned", "compromised", "exposed"]):
        tools.append("breach")

    if any(w in q for w in ["dark", "onion", "tor", "deep web"]):
        tools.append("darkweb")

    if any(w in q for w in ["search", "find", "research", "look up", "investigate", "report", "summary"]):
        tools.append("web")

    if not tools:
        tools.append("web")
        tools.append("username")
        tools.append("domain")

    return list(set(tools))


class OSINTAgent(BaseAgent):
    def __init__(self, llm, memory, rag=None):
        super().__init__("osint", llm, memory, rag)

    async def on_message(self, message: Message) -> dict:
        task = message.payload.get("task", "")
        query = message.payload.get("query", task)
        session_id = message.payload.get("session_id")

        self.memory.save_conversation(self.name, "user", task, session_id)

        tool_cats = _classify_query(query)
        logger.info("OSINT query classified as: %s", tool_cats)

        sub_results = {}

        parallel_tasks = []

        if "web" in tool_cats:
            parallel_tasks.append(("web", self._run_web_search(query)))
        if "username" in tool_cats:
            usernames = _extract_usernames(query)
            if usernames:
                parallel_tasks.append(("username", self._run_username_scan(usernames[0])))
        if "domain" in tool_cats:
            domains = _extract_domains(query)
            if domains:
                parallel_tasks.append(("domain", self._run_domain_recon(domains[0])))
        if "email" in tool_cats:
            emails = _extract_emails(query)
            if emails:
                parallel_tasks.append(("email", self._run_email_check(emails[0])))
        if "breach" in tool_cats:
            emails = _extract_emails(query)
            if emails:
                parallel_tasks.append(("breach", self._run_breach_check(emails[0])))
        if "darkweb" in tool_cats:
            parallel_tasks.append(("darkweb", self._run_darkweb_search(query)))

        if parallel_tasks:
            labels = [t[0] for t in parallel_tasks]
            coros = [t[1] for t in parallel_tasks]
            results = await asyncio.gather(*coros, return_exceptions=True)
            for label, res in zip(labels, results):
                if isinstance(res, Exception):
                    sub_results[label] = {"error": str(res)}
                elif isinstance(res, dict):
                    sub_results[label] = res
                elif hasattr(res, "to_dict"):
                    sub_results[label] = res.to_dict()
                else:
                    sub_results[label] = {"result": str(res)}

        search_text = _format_web_results(sub_results.get("web", {}))
        scraped_text = ""
        if sub_results.get("web", {}).get("pages"):
            pages = sub_results["web"]["pages"]
            scraped_text = "\n\n".join(
                f"[{p.get('url', '')}]\n{p.get('markdown', p.get('text', ''))[:2000]}"
                for p in pages[:4] if p.get("success", True)
            )

        tool_text = ""
        for cat in ["username", "domain", "email", "breach", "darkweb"]:
            if cat in sub_results:
                tool_text += f"\n### {cat.upper()} Results\n"
                tool_text += _summarize_subreport(cat, sub_results[cat])

        synthesis_prompt = SYNTHESIS_PROMPT.format(
            query=query,
            search_text=search_text or "(no search results)",
            scraped_text=scraped_text or "(no scraped content)",
            tool_text=tool_text or "(no additional tool results)",
        )

        analysis = await self.think(synthesis_prompt, session_id=session_id)

        report = OSINTReport(
            query=query,
            raw_analysis=analysis,
            sub_reports=sub_results,
        )

        if "web" in sub_results:
            report.sources = sub_results["web"].get("sources", [])

        all_engines = set()
        for cat, data in sub_results.items():
            if isinstance(data, dict):
                all_engines.add(cat)
        report.engines_used = sorted(all_engines)

        report.summary = analysis[:500]
        lines = analysis.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.")):
                cleaned = stripped.lstrip("-*1234567890. ").strip()
                if cleaned:
                    report.key_findings.append(cleaned)
            if "confidence" in stripped.lower() and any(c.isdigit() for c in stripped):
                for word in stripped.split():
                    try:
                        val = float(word.strip("%"))
                        if val <= 1:
                            report.confidence = val
                        elif val <= 100:
                            report.confidence = val / 100
                    except ValueError:
                        pass

        self.memory.save_conversation(self.name, "assistant", analysis, session_id)
        self.memory.save_knowledge(f"osint_{query}", str(report.to_dict()), {"agent": self.name})

        result = report.to_dict()
        result["report"] = report
        return result

    async def _run_web_search(self, query: str) -> dict:
        from tools.crawl4ai_scraper import crawl4ai_search, crawl4ai_scrape, format_osint_report

        search_results = await crawl4ai_search(query, limit=8)
        pages = []
        for r in search_results[:4]:
            url = r.get("url", "")
            if url:
                try:
                    page = await crawl4ai_scrape(url)
                    pages.append(page)
                except Exception:
                    continue

        report_meta = format_osint_report(query, search_results, pages)
        return {
            "results": search_results[:8],
            "pages": [
                {"url": p.url, "title": p.title, "source": p.source, "success": p.success}
                for p in pages
            ],
            "report": report_meta,
        }

    async def _run_username_scan(self, username: str) -> dict:
        from tools.sherlock_scanner import scan_username
        result = await scan_username(username)
        return result.to_dict()

    async def _run_domain_recon(self, domain: str) -> dict:
        from tools.theharvester import harvest_domain
        result = await harvest_domain(domain)
        return result.to_dict()

    async def _run_email_check(self, email: str) -> dict:
        from tools.holehe_checker import check_email
        result = await check_email(email)
        return result.to_dict()

    async def _run_breach_check(self, email: str) -> dict:
        from tools.holehe_checker import check_email_breach
        return await check_email_breach(email)

    async def _run_darkweb_search(self, query: str) -> dict:
        from tools.darkweb_monitor import search_darkweb
        result = await search_darkweb(query)
        return result.to_dict()


def _extract_usernames(query: str) -> list[str]:
    import re
    matches = re.findall(r'@(\w{3,})', query)
    if matches:
        return list(set(matches))
    import re
    words = re.findall(r'\b(\w{4,})\b', query)
    skip_words = {"check", "scan", "find", "search", "look", "query", "user", "username", "profile", "social", "media", "across", "platforms", "test", "random", "text"}
    for w in words:
        if w.lower() not in skip_words and w.isalnum():
            return [w]
    return []


def _extract_domains(query: str) -> list[str]:
    import re
    matches = re.findall(r'\b([a-zA-Z0-9-]+\.[a-zA-Z]{2,})\b', query)
    skip = {"com", "org", "net", "io", "co", "gov", "edu", "the", "and", "for", "are"}
    return list(set(m for m in matches if m.split(".")[0] not in skip))


def _extract_emails(query: str) -> list[str]:
    import re
    return list(set(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', query)))


def _format_web_results(web_data: dict) -> str:
    if not web_data or "results" not in web_data:
        return ""
    results = web_data["results"]
    return "\n".join(
        f"- {r.get('title', '')}: {r.get('snippet', '')} ({r.get('url', '')})"
        for r in results[:5]
    )


def _summarize_subreport(category: str, data: dict) -> str:
    if "error" in data:
        return f"Error: {data['error']}\n"

    if category == "username":
        found = data.get("found", [])
        if found:
            lines = [f"Found on {len(found)} platforms:"]
            for f in found[:10]:
                lines.append(f"  - {f.get('site', '?')}: {f.get('url', '')}")
            return "\n".join(lines)
        return f"Checked {data.get('total_checked', 0)} platforms — no matches"

    elif category == "domain":
        emails = data.get("emails", [])
        subdomains = data.get("subdomains", [])
        ips = data.get("ips", [])
        lines = []
        if emails:
            lines.append(f"Emails: {', '.join(emails[:5])}")
        if subdomains:
            lines.append(f"Subdomains ({len(subdomains)}): {', '.join(subdomains[:10])}")
        if ips:
            lines.append(f"IPs: {', '.join(ips[:5])}")
        return "\n".join(lines) or "No domain recon results"

    elif category == "email":
        accounts = data.get("accounts", [])
        if accounts:
            return f"Registered on {len(accounts)} platforms: {', '.join(a.get('site', '?') for a in accounts[:10])}"
        return "No accounts found"

    elif category == "breach":
        breaches = data.get("breaches", [])
        if breaches:
            return f"Found in {len(breaches)} breaches: {', '.join(b.get('name', '?') for b in breaches[:5])}"
        if data.get("error"):
            return f"Breach check: {data['error']}"
        return "No breaches found"

    elif category == "darkweb":
        results = data.get("results", [])
        if results:
            return f"Found {len(results)} dark web results"
        note = data.get("note", "")
        return note or "No dark web results"

    return str(data)
