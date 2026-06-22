---
name: threat-analysis
category: intelligence
tags: [threat, malware, attack, mitre, ioc, risk, vulnerability, adversary, apt]
triggers: [threat, analyze threat, attack, malware, ioc, indicator, mitre, risk assessment, adversary, apt, ttp]
version: 1.0
---

# Threat Analysis Skill

## When to Use

When the operator requests threat analysis, adversary profiling, IOC processing, MITRE ATT&CK mapping, risk scoring, or incident assessment. Use for analyzing suspicious activity, evaluating threat intelligence feeds, or producing threat assessments for decision-makers.

## Threat Classification

| Category | Description | Examples |
|----------|-------------|---------|
| APT | Advanced persistent threat, nation-state | APT29, Lazarus Group |
| Cybercrime | Financially motivated threat actors | Ransomware gangs, carding |
| Hacktivism | Ideologically motivated | Defacement, DDoS |
| Insider | Internal threat, trusted access | Data exfiltration, sabotage |
| Opportunistic | Low-sophistication, automated | Botnets, script kiddies |

## Workflow

1. **Ingest** — Collect IOCs, alerts, threat feeds, and contextual data
2. **Classify** — Determine threat category, sophistication, and intent
3. **Map** — Align observed behavior to MITRE ATT&CK tactics and techniques
4. **Assess** — Score risk based on likelihood and impact
5. **Attribute** — Identify probable threat actor (if sufficient evidence)
6. **Recommend** — Produce actionable defensive measures

## MITRE ATT&CK Mapping

### Tactics (Kill Chain Phases)
```
Reconnaissance → Resource Development → Initial Access → Execution →
Persistence → Privilege Escalation → Defense Evasion → Credential Access →
Discovery → Lateral Movement → Collection → Command and Control →
Exfiltration → Impact
```

### Mapping Procedure
```
1. Extract observed behaviors from evidence (logs, alerts, reports)
2. Match each behavior to ATT&CK technique IDs (e.g., T1566.001)
3. Group techniques under their parent tactics
4. Identify the kill chain stage progression
5. Flag gaps in detection coverage for each mapped technique
6. Cross-reference with known threat actor profiles
```

## IOC Processing

### IOC Types
| Type | Format | Validation |
|------|--------|------------|
| IPv4 | `x.x.x.x` | Octet range check |
| IPv6 | Full or compressed | RFC 5952 format |
| Domain | FQDN | DNS syntax validation |
| URL | Full URL | Scheme + host + path |
| Hash (MD5) | 32 hex chars | Length and charset |
| Hash (SHA1) | 40 hex chars | Length and charset |
| Hash (SHA256) | 64 hex chars | Length and charset |
| Email | `user@domain` | RFC 5322 basic |
| Filename | Path or basename | Platform-specific |

### Processing Pipeline
```
1. Validate IOC format and normalize
2. Deduplicate against existing IOC database
3. Enrich: WHOIS, DNS, reputation scores, threat feed correlation
4. Score confidence: confirmed / probable / unverified
5. Tag with MITRE techniques and threat actor associations
6. Generate detection rules (YARA, Sigma, Snort) where applicable
```

## Risk Scoring

### Risk Matrix

| | Low Impact | Medium Impact | High Impact | Critical Impact |
|---|-----------|---------------|-------------|-----------------|
| **Likely** | Medium | High | Critical | Critical |
| **Probable** | Low | Medium | High | Critical |
| **Possible** | Low | Low | Medium | High |
| **Unlikely** | Low | Low | Low | Medium |

### Scoring Factors
- **Sophistication** — Tooling, opsec, zero-day usage (1-5)
- **Targeting** — Broad vs. targeted (1-5)
- **Impact** — Data loss, disruption, financial (1-5)
- **Likelihood** — Historical frequency, current intelligence (1-5)
- **Detection Gap** — Existing coverage vs. TTPs (1-5)

**Risk Score** = (Sophistication + Targeting + Impact + Likelihood) / 4, weighted by Detection Gap

## Output Format

```markdown
# Threat Assessment: [Subject]

## Executive Summary
[2-3 sentence assessment for decision-makers]

## Threat Profile
- **Category**: [APT/cybercrime/hacktivism/insider/opportunistic]
- **Attribution**: [threat actor or unknown]
- **Motivation**: [financial/espionage/ideological/disruption]
- **Sophistication**: [low/medium/high/advanced]

## MITRE ATT&CK Mapping
| Tactic | Technique | ID | Evidence |
|--------|-----------|----|----------|
| [tactic] | [technique name] | [T####.###] | [source] |

## Indicators of Compromise
| Type | Value | Confidence | Context |
|------|-------|------------|---------|
| [type] | [value] | [level] | [notes] |

## Risk Assessment
- **Likelihood**: [rating]
- **Impact**: [rating]
- **Overall Risk**: [rating]
- **Detection Coverage**: [percentage estimate]

## Recommendations
1. [Immediate actions]
2. [Short-term mitigations]
3. [Long-term strategic improvements]
```

## Best Practices

- Always distinguish between confirmed intelligence and speculation
- Use structured formats (STIX/TAXII concepts) for IOC sharing
- Map every claim to evidence — no assertions without sources
- Consider the defender's perspective — recommendations must be actionable
- Flag detection gaps prominently
- Update assessments as new intelligence becomes available
- Never overstate attribution confidence without corroborating evidence
