---
name: market-research
category: intelligence
tags: [market, research, competitor, trends, industry, analysis, business, intelligence]
triggers: [market research, competitor, market trends, industry analysis, business intelligence, competitive analysis]
version: 1.0
---

# Market Research Skill

## When to Use

When the operator requests market research, competitor analysis, trend identification, or industry intelligence. Use for any query about market dynamics, competitive landscapes, or business environment analysis.

## Capabilities

### Competitor Analysis
- **Product Mapping**: Feature comparison, pricing, positioning
- **Market Share**: Revenue estimates, growth rates, market penetration
- **Strategy Analysis**: Business model, go-to-market, partnerships
- **Strengths/Weaknesses**: SWOT-style assessment

### Market Trends
- **Industry Trends**: Growth patterns, emerging technologies, market shifts
- **Consumer Trends**: Behavioral changes, preferences, demographics
- **Technology Trends**: Innovation cycles, adoption rates, disruption potential
- **Regulatory Trends**: Policy changes, compliance requirements

### Industry Analysis
- **Market Size**: TAM, SAM, SOM estimates
- **Growth Projections**: CAGR, forecast trends
- **Competitive Intensity**: Porter's Five Forces analysis
- **Value Chain**: Supply chain, distribution, key players

### Source Intelligence
- **Primary Sources**: Company websites, press releases, SEC filings
- **Secondary Sources**: News articles, analyst reports, industry publications
- **Data Sources**: Statista, Crunchbase, LinkedIn, Google Trends
- **Social Signals**: Twitter/X, Reddit, HN discussions

## Workflow

### Standard Research
1. Parse the research query to identify:
   - Target market/industry
   - Specific competitors or companies
   - Time frame and scope
2. Search for prior context in RAG/memory
3. Gather intelligence from multiple sources:
   - Web search for recent news and reports
   - Scrape competitor websites for product/pricing info
   - Check social media for sentiment and trends
4. Analyze and synthesize findings
5. Generate structured report with confidence levels

### Competitive Deep Dive
1. Identify the target company/competitor
2. Gather product information and pricing
3. Analyze recent news and announcements
4. Check social media presence and engagement
5. Compare against known alternatives
6. Generate competitive intelligence report

## Output Format

```markdown
# Market Research Report: [Topic]

**Date**: [timestamp]
**Analyst**: NEXUS-01 IVA
**Confidence**: [H/M/L]
**Sources**: [count]

## Executive Summary
[2-3 sentence overview of key findings]

## Market Overview
- **Market Size**: [estimate with source]
- **Growth Rate**: [CAGR or trend]
- **Key Players**: [list major players]

## Competitor Analysis

### [Competitor Name]
- **Product**: [description]
- **Pricing**: [if available]
- **Strengths**: [list]
- **Weaknesses**: [list]
- **Recent Activity**: [notable news/changes]

## Key Trends
1. [Trend 1]: [description and implications]
2. [Trend 2]: [description and implications]
3. [Trend 3]: [description and implications]

## Opportunities & Threats
### Opportunities
- [opportunity 1]
- [opportunity 2]

### Threats
- [threat 1]
- [threat 2]

## Recommendations
1. [actionable recommendation 1]
2. [actionable recommendation 2]

## Sources
| # | Source | URL | Confidence |
|---|--------|-----|------------|
| 1 | [name] | [url] | [H/M/L] |
```

## Confidence Levels

- **High**: Multiple independent sources confirm
- **Medium**: Single reliable source or consistent pattern
- **Low**: Limited data, single source, or speculative
- **Unconfirmed**: Raw data, not yet validated

## Quality Standards

- Cite all sources with URLs when available
- Distinguish facts from inferences
- Provide confidence levels for key claims
- Use structured format for easy scanning
- Include actionable recommendations
- Note data limitations and gaps

## Integration Points

- **RAG**: Pull prior research on same topic
- **OSINT**: Use OSINT tools for deep investigation
- **Analysis Skill**: Apply analytical frameworks
- **Report Generation**: Format as executive brief or detailed report
