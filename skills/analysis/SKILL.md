# Analysis Skill — Threat Intelligence & Data Analysis

## Purpose
Analyze intelligence data, identify patterns, assess threats, and generate actionable reports.

## When to Use
- Threat actor profiling and tracking
- Vulnerability assessment and risk analysis
- Attack pattern recognition
- Incident investigation and forensics
- Data correlation across sources
- Risk assessment and prioritization

## Capabilities

### Threat Analysis
- **Actor Profiling**: TTPs, motivations, infrastructure
- **Campaign Tracking**: Attack timelines, indicators
- **Malware Analysis**: Behavior patterns, C2 infrastructure
- **Attribution**: Confidence-weighted attribution

### Vulnerability Analysis
- **Risk Scoring**: CVSS calculation, contextual risk
- **Exploitability**: Known exploits, weaponization potential
- **Impact Assessment**: Business impact, data exposure
- **Prioritization**: Risk-based remediation ordering

### Data Analysis
- **Pattern Recognition**: Behavioral, temporal, network patterns
- **Anomaly Detection**: Statistical and behavioral anomalies
- **Correlation**: Cross-source data linking
- **Trend Analysis**: Evolution over time

### Report Generation
- **Intelligence Reports**: Structured threat intelligence
- **Executive Summaries**: Risk-focused overviews
- **Technical Reports**: Detailed technical findings
- **After-Action Reports**: Mission debrief and lessons learned

## Workflow

### Standard Analysis
1. Gather intelligence from OSINT or memory
2. Apply appropriate analysis framework
3. Identify patterns and indicators
4. Assess confidence levels
5. Generate structured findings
6. Provide actionable recommendations

### Threat Assessment
1. Identify threat actors or vulnerabilities
2. Map TTPs to MITRE ATT&CK framework
3. Assess likelihood and impact
4. Prioritize based on risk
5. Recommend mitigations

## Output Format
```markdown
## Intelligence Assessment — [Classification]
**Subject**: [topic]
**Date**: [timestamp]
**Analyst**: NEXUS-01
**Confidence**: [H/M/L]

### Executive Summary
[2-3 sentence overview]

### Threat Assessment
- **Threat Level**: [Critical/High/Medium/Low]
- **Likelihood**: [Certain/Likely/Possible/Unlikely]
- **Impact**: [Severe/Moderate/Minor/Negligible]

### Key Findings
1. [Finding with evidence]
2. [Finding with evidence]

### Indicators of Compromise (IOCs)
- IP: [indicator]
- Domain: [indicator]
- Hash: [indicator]

### MITRE ATT&CK Mapping
- **Tactic**: [tactic]
- **Technique**: [technique]

### Recommendations
- [Immediate action]
- [Long-term mitigation]

### Sources
- [Source 1]
```

## Analysis Frameworks
- **MITRE ATT&CK**: Adversary tactics and techniques
- **Cyber Kill Chain**: Attack progression stages
- **Diamond Model**: Adversary, capability, infrastructure, victim
- **STIX/TAXII**: Structured threat intelligence

## Quality Standards
- Always cite sources with confidence levels
- Distinguish facts from inferences
- Provide actionable recommendations
- Use structured intelligence formats
- Include IOCs in machine-readable format
