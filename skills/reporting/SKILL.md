# Reporting Skill — Intelligence Products & Documentation

## Purpose
Generate professional intelligence reports, after-action reviews, and operational documentation.

## When to Use
- Mission debriefing and reporting
- Threat intelligence documentation
- Vulnerability assessment reports
- Executive risk summaries
- Technical findings documentation
- After-action reviews

## Report Types

### Intelligence Report
Comprehensive threat intelligence with citations and recommendations.

### Vulnerability Assessment
Technical findings with risk scoring and remediation.

### Executive Summary
High-level risk overview for decision makers.

### After-Action Report
Mission debrief with lessons learned.

### IOC Report
Indicators of compromise in machine-readable format.

## Output Formats

### Markdown (Default)
- Best for: Documentation, collaboration, version control
- Structure: Headers, lists, code blocks, tables
- Usage: All reports default to this format

### HTML
- Best for: Web viewing, presentations, sharing
- Structure: Single-file with embedded CSS
- Usage: When visual presentation matters

### JSON
- Best: Machine-readable, API consumption, automation
- Structure: Structured data with nested objects
- Usage: IOC sharing, automated processing

### CSV
- Best: Spreadsheet analysis, bulk data
- Structure: Tabular data with headers
- Usage: IOC lists, target lists

## Report Templates

### Intelligence Report
```markdown
# [Classification] — Intelligence Report

**Report ID**: [id]
**Date**: [timestamp]
**Analyst**: NEXUS-01
**Classification**: [Confidential/Secret/Top Secret]
**Handling**: [SCI/FOUO/NOFORN]

## Executive Summary
[2-3 paragraph overview]

## Threat Overview
[Threat actor/campaign description]

## Key Findings
1. [Finding with citation]
2. [Finding with citation]

## Indicators of Compromise
| Type | Value | Context |
|------|-------|---------|
| IP | [ip] | [context] |
| Domain | [domain] | [context] |
| Hash | [hash] | [context] |

## MITRE ATT&CK Mapping
| Tactic | Technique | ID |
|--------|-----------|-----|
| [tactic] | [technique] | [id] |

## Recommendations
1. [Immediate action]
2. [Long-term mitigation]

## Appendices
### A. Raw Data
[Supporting data]

### B. Sources
1. [Source with URL]

### C. Methodology
[How intelligence was gathered]
```

### Vulnerability Assessment
```markdown
# [Classification] — Vulnerability Assessment

**Target**: [target]
**Date**: [timestamp]
**Assessor**: NEXUS-01
**Scope**: [scope]

## Executive Summary
[Overview of vulnerabilities found]

## Findings Summary
| Severity | Count | CVSS Range |
|----------|-------|------------|
| Critical | X | 9.0-10.0 |
| High | X | 7.0-8.9 |
| Medium | X | 4.0-6.9 |
| Low | X | 0.1-3.9 |

## Critical Findings
### [Finding Name]
- **CVSS**: [score]
- **Affected**: [systems]
- **Impact**: [description]
- **Remediation**: [fix]

## Recommendations
1. [Priority 1]
2. [Priority 2]

## Appendix
[Technical details]
```

### After-Action Report
```markdown
# After-Action Report — [Operation Name]

**Date**: [timestamp]
**Operator**: [operator]
**Duration**: [time]
**Status**: [Success/Partial/Failed]

## Mission Overview
[What was accomplished]

## Timeline
| Time | Activity | Result |
|------|----------|--------|
| [time] | [action] | [result] |

## Findings
[Key discoveries]

## Lessons Learned
- [What worked]
- [What didn't]
- [Improvements]

## Recommendations
[Future improvements]
```

## Quality Standards

### Citations
- Every claim needs a source
- Format: [Source: name] [Confidence: H/M/L]
- Include URL when available
- Date-stamp time-sensitive data

### Classification
- Mark all reports with classification
- Include handling instructions
- Use appropriate markers

### Accuracy
- Verify facts before including
- Distinguish facts from inferences
- Note confidence levels
- Acknowledge limitations

### Completeness
- Cover all relevant findings
- Include negative results
- Document methodology
- Provide context

## File Generation
1. Generate report content
2. Format for target output
3. Save to workspace
4. Provide download link
5. Store in knowledge base
6. Log generation for audit
