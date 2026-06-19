from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agents.base import BaseAgent
from core.bus import Message
from tools.firecrawl_scraper import (
    firecrawl_scrape,
    firecrawl_search,
    format_report,
)

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

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "summary": self.summary,
            "key_findings": self.key_findings,
            "sources": self.sources,
            "confidence": self.confidence,
            "recommended_actions": self.recommended_actions,
            "engines_used": self.engines_used,
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

Return a JSON-like structured report with these fields (use plain text, not actual JSON):
- summary: 2-3 sentence executive summary
- key_findings: list of 3-5 most important findings
- confidence: float 0-1 based on source quality and consistency
- recommended_actions: list of 2-3 next steps for deeper investigation

Be specific. Cite URLs when referencing findings."""


class OSINTAgent(BaseAgent):
    def __init__(self, llm, memory, rag=None):
        super().__init__("osint", llm, memory, rag)

    async def on_message(self, message: Message) -> dict:
        task = message.payload.get("task", "")
        query = message.payload.get("query", task)
        session_id = message.payload.get("session_id")

        self.memory.save_conversation(self.name, "user", task, session_id)

        search_results = await firecrawl_search(query, limit=8)

        pages = []
        for result in search_results[:4]:
            url = result.get("url", "")
            if url:
                try:
                    page = await firecrawl_scrape(url)
                    pages.append(page)
                except Exception:
                    continue

        search_text = "\n".join(
            f"- {r.get('title', '')}: {r.get('snippet', '')} ({r.get('url', '')})"
            for r in search_results[:5]
        )
        scraped_text = "\n\n".join(
            f"[{p.url}]\n{p.markdown or p.text[:2000]}"
            for p in pages if p.success
        )

        synthesis_prompt = SYNTHESIS_PROMPT.format(
            query=query,
            search_text=search_text or "(no search results)",
            scraped_text=scraped_text or "(no scraped content)",
        )

        analysis = await self.think(synthesis_prompt, session_id=session_id)

        report_meta = format_report(query, search_results, pages)

        report = OSINTReport(
            query=query,
            raw_analysis=analysis,
            sources=report_meta["sources"],
            engines_used=report_meta["engines_used"],
        )

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
