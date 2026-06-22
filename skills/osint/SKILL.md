# OSINT Skill — Offensive Intelligence Gathering

## Purpose
Full-spectrum open-source intelligence for offensive security operations.

## When to Use
- Reconnaissance on targets (people, companies, infrastructure)
- Pre-engagement intelligence gathering
- Continuous monitoring and surveillance
- Threat actor profiling
- Attack surface mapping
- Social engineering preparation

## Available Tools

### Username Enumeration
- **Sherlock**: 300+ platform checks with parallel execution
- **Built-in Scanner**: High-confidence platforms (GitHub, Twitter, Reddit, LinkedIn, etc.)
- **API Enumeration**: Platform-specific API discovery
- **Custom Scanners**: Extendable scanner framework

### Domain Reconnaissance
- **theHarvester**: Subdomains, emails, IPs from multiple sources
- **crt.sh**: Certificate transparency log mining
- **DNS Enumeration**: A, AAAA, MX, NS, TXT, SOA records
- **Subdomain Brute-force**: Dictionary-based subdomain discovery
- **WHOIS**: Registration data, registrar info, name servers

### Email Intelligence
- **holehe**: Account existence verification
- **GitHub/Gravatar**: Profile discovery and linkage
- **HIBP**: Breach monitoring and exposure checks
- **Disposable Detection**: Temporary email identification
- **Social Linkage**: Email to social media mapping

### IP/Network Intelligence
- **Geolocation**: Physical location from IP
- **ASN Lookup**: Network ownership and routing
- **Port Scanning**: Service discovery and fingerprinting
- **Banner Grabbing**: Version detection and identification

### Web Intelligence
- **Crawl4AI**: Self-hosted LLM-friendly web scraper
- **Browser Automation**: Playwright headless for SPAs
- **Content Extraction**: Full page content, JavaScript rendered
- **Technology Detection**: Framework and CMS identification

### Dark Web (Phase 4)
- **OnionSearch**: Dark web search engine integration
- **Marketplace Monitoring**: Credential and data exposure
- **Forum Scraping**: Threat actor communication tracking

## Workflow

### Standard Reconnaissance
1. Classify target type (person/domain/email/IP)
2. Select appropriate tools based on target
3. Execute tools in parallel for speed
4. Aggregate and deduplicate results
5. Generate citation-backed report
6. Store in operational memory

### Multi-Phase Operation
1. **Phase 1 - Passive Recon**: OSINT without direct contact
2. **Phase 2 - Active Recon**: Limited interaction with target
3. **Phase 3 - Enumeration**: Detailed service and user mapping
4. **Phase 4 - Validation**: Verify findings with multiple sources

## Output Format
```markdown
## OSINT Report — [Classification]
**Target**: [target]
**Type**: [person/domain/email/network]
**Date**: [timestamp]
**Operator**: [operator]
**Confidence**: [H/M/L]

### Findings
1. [Platform]: [result] [Source: platform] [Confidence: H]
2. [Platform]: [result] [Source: platform] [Confidence: M]

### Exposure Summary
- **Platforms Found**: X/Y checked
- **Risk Level**: [Critical/High/Medium/Low]
- **Data Points**: [key findings]

### Attack Surface
- [Vulnerability or exposure point]
- [Weakness or misconfiguration]

### Recommendations
- [Action based on findings]
```

## Error Handling
- Log all tool executions for audit
- Continue on individual tool failure
- Report partial results with failure reasons
- Suggest alternative approaches when blocked

## Operational Security
- Use proxy/VPN for sensitive reconnaissance
- Rotate user agents and headers
- Respect rate limits to avoid detection
- Log all queries for after-action review
- Never leave forensic traces
