---
name: report-generation
category: intelligence
tags: [report, document, summary, briefing, executive, intelligence, writeup, deliverable]
triggers: [report, write report, generate report, summary, briefing, executive summary, writeup, deliverable, document]
version: 1.0
---

# Intelligence Report Generation Skill

## When to Use

When the operator requests a structured intelligence report, executive summary, briefing document, or formal writeup of findings. Use for any deliverable that requires professional formatting, citations, and structured presentation of intelligence or analysis results.

## Report Types

| Type | Audience | Length | Focus |
|------|----------|--------|-------|
| Executive Summary | Leadership, decision-makers | 1-2 pages | Key findings, risk, recommendations |
| Intelligence Brief | Analysts, operators | 2-5 pages | Detailed findings with evidence |
| Technical Report | Engineers, security teams | 5+ pages | Full technical detail, IOCs, remediation |
| Situation Report | All stakeholders | 1-3 pages | Current status, changes, outlook |
| Assessment | Decision-makers | 3-5 pages | Analysis, probabilities, implications |

## Workflow

1. **Determine** report type and target audience
2. **Aggregate** findings from prior analysis, tools, and intelligence
3. **Structure** content according to the appropriate template
4. **Cite** all sources with confidence levels
5. **Summarize** key points for the intended audience
6. **Review** for accuracy, completeness, and classification

## Report Templates

### Executive Summary

```markdown
# [Title] — Executive Summary

**Date**: [date]
**Classification**: [level]
**Prepared by**: [author/system]

## Key Findings
1. [Most critical finding — one sentence]
2. [Second finding — one sentence]
3. [Third finding — one sentence]

## Risk Assessment
**Overall Risk**: [CRITICAL / HIGH / MEDIUM / LOW]
[Brief justification — 2-3 sentences]

## Recommendations
1. [Most urgent action]
2. [Second action]
3. [Third action]

## Outlook
[Brief forward-looking statement — what to watch for]
```

### Intelligence Brief

```markdown
# [Title] — Intelligence Brief

**Date**: [date]
**Classification**: [level]
**Subject**: [target/subject]
**Analyst**: [author/system]

## Summary
[3-5 sentence overview of the intelligence]

## Background
[Context necessary to understand the findings]

## Findings

### [Finding Category]
**Observation**: [what was found]
**Evidence**: [supporting data]
**Source**: [tool/platform/method]
**Confidence**: [high/medium/low]
**Assessment**: [what this means]

## Analysis
[Interpretation connecting findings into a coherent picture]

## Gaps and Limitations
[What we don't know, data limitations, collection gaps]

## Recommendations
[Prioritized actions based on findings]

## Sources
[Numbered list of all sources cited]
```

### Technical Report

```markdown
# [Title] — Technical Report

**Date**: [date]
**Classification**: [level]
**Subject**: [target/system]
**Analyst**: [author/system]

## Executive Summary
[Condensed version for leadership — 3-5 sentences]

## Scope and Methodology
[What was analyzed, tools used, time period covered]

## Findings

### [SEVERITY] [Finding Title]
- **Category**: [vulnerability/misconfiguration/exposure/etc.]
- **Location**: [affected system/file/endpoint]
- **Description**: [detailed technical description]
- **Evidence**: [screenshots, logs, data excerpts]
- **Impact**: [what an adversary could do]
- **Remediation**: [specific steps to fix]
- **References**: [CVEs, advisories, documentation]

## Indicators of Compromise
| Type | Value | Context | Confidence |
|------|-------|---------|------------|

## Timeline
| Time (UTC) | Event | Source |
|------------|-------|--------|

## Recommendations
[Prioritized by severity and effort]

## Appendices
[Raw data, full tool output, detailed scan results]
```

## Citation Standards

Every factual claim must be backed by a source:

```
[1] Source Name, "Document Title", URL (accessed YYYY-MM-DD)
[2] Tool Name, scan results, YYYY-MM-DD HH:MM UTC
[3] Internal analysis, correlation of findings #1 and #3
```

### Confidence Levels
- **High** — Confirmed by multiple independent sources
- **Medium** — Single reliable source or strong circumstantial evidence
- **Low** — Unverified, single source, or speculative
- **Unconfirmed** — Raw intelligence, not yet validated

## Writing Guidelines

- Lead with the conclusion — busy readers need the answer first
- One finding per paragraph — don't mix unrelated observations
- Use active voice and present tense for current findings
- Quantify when possible — "47 exposed endpoints" not "many endpoints"
- Define acronyms on first use
- Keep sentences under 25 words where possible
- Separate fact from assessment — clearly label analytical judgments
- Use tables for structured data (IOCs, timelines, comparisons)

## Quality Checklist

Before delivering any report:

- [ ] All findings have citations
- [ ] Confidence levels assigned to every claim
- [ ] Executive summary stands alone (readable without the full report)
- [ ] Recommendations are specific and actionable
- [ ] No unsubstantiated attribution claims
- [ ] Sensitive data properly handled per classification
- [ ] Grammar and formatting reviewed
- [ ] Report length appropriate for type and audience

## Best Practices

- Match the report depth to the audience — executives need brevity, engineers need detail
- Always include a "what we don't know" section — honesty about gaps builds trust
- Use consistent formatting — operators should recognize the structure immediately
- Timestamp everything — intelligence degrades over time
- Version reports when updates are issued — mark what changed
- Include raw evidence in appendices, not in the main body
