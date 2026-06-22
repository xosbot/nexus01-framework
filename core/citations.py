"""Citation engine for structured source attribution in OSINT results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Citation:
    source: str
    url: str = ""
    date_accessed: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: str = "medium"
    notes: str = ""

    def to_inline(self) -> str:
        parts = [f"Source: {self.source}"]
        if self.url:
            parts.append(f"URL: {self.url}")
        parts.append(f"Confidence: {self.confidence}")
        return f"[{', '.join(parts)}]"

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "url": self.url,
            "date_accessed": self.date_accessed,
            "confidence": self.confidence,
            "notes": self.notes,
        }


@dataclass
class Finding:
    content: str
    citations: list[Citation] = field(default_factory=list)
    confidence: str = "medium"
    category: str = "general"

    def to_markdown(self) -> str:
        lines = [self.content]
        for cite in self.citations:
            lines.append(f"  {cite.to_inline()}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "citations": [c.to_dict() for c in self.citations],
            "confidence": self.confidence,
            "category": self.category,
        }


@dataclass
class Report:
    title: str
    target: str
    report_type: str = "osint"
    findings: list[Finding] = field(default_factory=list)
    summary: str = ""
    recommendations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_finding(self, content: str, source: str, url: str = "",
                    confidence: str = "medium", category: str = "general") -> Finding:
        cite = Citation(source=source, url=url, confidence=confidence)
        finding = Finding(content=content, citations=[cite], confidence=confidence, category=category)
        self.findings.append(finding)
        return finding

    def to_markdown(self) -> str:
        lines = [
            f"# {self.title}",
            "",
            f"**Target**: {self.target}",
            f"**Date**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"**Type**: {self.report_type}",
            f"**Confidence**: {self._overall_confidence()}",
            "",
            "## Findings",
            "",
        ]

        for i, finding in enumerate(self.findings, 1):
            lines.append(f"### {i}. {finding.category.title()}")
            lines.append(finding.to_markdown())
            lines.append("")

        if self.summary:
            lines.extend(["## Summary", "", self.summary, ""])

        if self.recommendations:
            lines.append("## Recommendations")
            lines.append("")
            for rec in self.recommendations:
                lines.append(f"- {rec}")
            lines.append("")

        all_sources = self._all_sources()
        if all_sources:
            lines.append("## Sources")
            lines.append("")
            for source in all_sources:
                lines.append(f"- {source}")
            lines.append("")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "target": self.target,
            "report_type": self.report_type,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "recommendations": self.recommendations,
            "metadata": self.metadata,
            "confidence": self._overall_confidence(),
            "sources": self._all_sources(),
        }

    def _overall_confidence(self) -> str:
        if not self.findings:
            return "none"
        confidences = [f.confidence for f in self.findings]
        if "low" in confidences:
            return "low"
        if all(c == "high" for c in confidences):
            return "high"
        return "medium"

    def _all_sources(self) -> list[str]:
        seen = set()
        sources = []
        for finding in self.findings:
            for cite in finding.citations:
                key = cite.source
                if key not in seen:
                    seen.add(key)
                    parts = [cite.source]
                    if cite.url:
                        parts.append(f"({cite.url})")
                    sources.append(" ".join(parts))
        return sources


def citation_from_osint(platform: str, result: dict) -> Citation:
    url = result.get("url", result.get("link", ""))
    return Citation(
        source=platform,
        url=url,
        confidence="high" if result.get("found") else "medium",
    )


def format_findings_table(findings: list[dict]) -> str:
    if not findings:
        return "No findings."

    lines = ["| Platform | Status | Evidence | Source |", "|----------|--------|----------|--------|"]
    for f in findings:
        platform = f.get("platform", f.get("source", "Unknown"))
        status = "Found" if f.get("found", f.get("exists")) else "Not Found"
        evidence = f.get("evidence", f.get("url", "-"))[:50]
        source = f"[Source: {platform}]"
        lines.append(f"| {platform} | {status} | {evidence} | {source} |")

    return "\n".join(lines)
