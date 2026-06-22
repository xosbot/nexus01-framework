---
name: osint-recon
category: intelligence
tags: [osint, reconnaissance, domain, username, email, ip, enumeration]
triggers: [research, investigate, recon, osint, scan, enumerate, lookup, intel, gather, footprint]
version: 1.0
---

# OSINT Reconnaissance Skill

## When to Use

When the operator requests intelligence gathering on a target — including usernames, domains, email addresses, IP addresses, or organizations. Use this skill for any open-source intelligence collection, digital footprinting, or target enumeration task.

## Target Classification

Classify the target before executing any tools:

| Target Type | Indicators | Primary Tools |
|-------------|-----------|---------------|
| Username | Social handle, alias | Sherlock, social media APIs |
| Domain | URL, FQDN, company name | theHarvester, DNS tools, Crawl4AI |
| Email | Email address | holehe, breach databases |
| IP Address | IPv4/IPv6, CIDR range | Shodan, WHOIS, reverse DNS |
| Organization | Company name, brand | theHarvester, LinkedIn, web scraping |

## Workflow

1. **Classify** the target type and validate input format
2. **Enumerate** using appropriate tools based on classification
3. **Correlate** findings across sources — cross-reference usernames, emails, domains
4. **Validate** results — confirm findings with secondary sources where possible
5. **Score** confidence for each finding (high / medium / low)
6. **Report** structured intelligence with citations

## Tools Available

- **Sherlock** — Username enumeration across 400+ social platforms
- **theHarvester** — Domain reconnaissance (emails, subdomains, hosts)
- **holehe** — Email existence checking across 120+ platforms
- **Crawl4AI** — Web scraping and content extraction
- **Firecrawl** — Advanced web crawling with LLM extraction
- **Dark Web Monitor** — Breach database and dark web scanning

## Enumeration Procedures

### Username Targets
```
1. Run Sherlock against target username
2. Filter results: confirmed profiles vs. possible matches
3. Extract profile metadata (bio, location, join date, connections)
4. Cross-reference discovered emails with holehe
5. Map social graph connections
```

### Domain Targets
```
1. Run theHarvester for emails, subdomains, and hosts
2. DNS enumeration: A, AAAA, MX, TXT, NS records
3. Subdomain validation and fingerprinting
4. Certificate transparency log search
5. Web technology stack identification
6. Historical WHOIS data collection
```

### Email Targets
```
1. Run holehe to check platform registrations
2. Breach database lookup (if dark web monitor available)
3. Extract associated usernames from platform profiles
4. Cross-reference with username enumeration results
5. Verify email format patterns for organization
```

### IP Targets
```
1. Reverse DNS lookup
2. WHOIS / ASN identification
3. Port scanning context (if authorized)
4. Geolocation and hosting provider identification
5. Historical DNS resolution
```

## Output Format

```markdown
# OSINT Report: [Target]

## Target Classification
- Type: [username/domain/email/ip]
- Value: [target value]
- Date: [timestamp]

## Findings

### [Category]
- **Finding**: [description]
- **Source**: [tool/platform used]
- **Evidence**: [URL or data reference]
- **Confidence**: [high/medium/low]

## Correlations
[Cross-referenced findings linking multiple data points]

## Intelligence Summary
[Concise summary of key findings and their significance]
```

## Best Practices

- Always cite sources with URLs where available
- Cross-reference findings across multiple tools before marking high confidence
- Flag any findings that could be false positives
- Respect rate limits on all external services
- Never execute active scanning without explicit authorization
- Log all reconnaissance activity for audit trail
- Sanitize output — redact sensitive data not relevant to the mission
