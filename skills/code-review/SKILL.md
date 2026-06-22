---
name: code-review
category: engineering
tags: [code, review, security, quality, analysis, lint, vulnerability, audit]
triggers: [review, audit, analyze, inspect, check, scan, code quality, security review, code review]
version: 1.0
---

# Code Review Skill

## When to Use

When the operator requests a code review, security audit, quality analysis, or structural assessment of source code. Applies to any language or framework. Use for pull request reviews, pre-deployment audits, or general code quality assessments.

## Review Classification

| Review Type | Focus | Depth |
|-------------|-------|-------|
| Quick Scan | Obvious bugs, style issues | Surface |
| Structural Review | Architecture, patterns, coupling | Medium |
| Security Audit | Vulnerabilities, injection, auth flaws | Deep |
| Performance Review | Bottlenecks, complexity, resource usage | Deep |
| Full Review | All of the above | Comprehensive |

## Workflow

1. **Scope** — Identify files, language, framework, and review type
2. **Structural Analysis** — Map module dependencies, entry points, data flow
3. **Pattern Check** — Verify adherence to framework conventions and idioms
4. **Security Scan** — Check for common vulnerability classes
5. **Quality Assessment** — Evaluate readability, testability, maintainability
6. **Report** — Prioritized findings with severity and remediation guidance

## Structural Analysis

```
1. Map file/directory structure and module boundaries
2. Identify entry points (main, handlers, routes, controllers)
3. Trace data flow: input → processing → output
4. Map external dependencies and their versions
5. Identify shared state and side effects
6. Check for circular dependencies
```

## Security Checklist

### Injection
- SQL injection (raw queries, string concatenation)
- Command injection (shell exec, subprocess with user input)
- XSS (unsanitized output in HTML/templates)
- Path traversal (user-controlled file paths)

### Authentication & Authorization
- Hardcoded credentials or secrets
- Missing authentication on endpoints
- Insufficient authorization checks
- Insecure session management

### Data Handling
- Sensitive data in logs or error messages
- Missing input validation/sanitization
- Insecure deserialization
- Plaintext storage of secrets

### Dependencies
- Known vulnerable package versions
- Unpinned dependency versions
- Abandoned or unmaintained libraries

### Configuration
- Debug mode in production code
- Verbose error messages exposing internals
- Missing security headers or CORS misconfiguration
- Secrets in source control

## Quality Metrics

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Function length | <30 lines | 30-50 lines | >50 lines |
| Cyclomatic complexity | <10 | 10-20 | >20 |
| Test coverage | >80% | 50-80% | <50% |
| Type annotations | Full | Partial | None |
| Documentation | Public APIs | Key functions | None |

## Output Format

```markdown
# Code Review: [Project/File]

## Summary
- **Scope**: [files reviewed]
- **Language/Framework**: [detected stack]
- **Review Type**: [quick/structural/security/full]
- **Overall Assessment**: [pass/needs work/critical issues]

## Findings

### [SEVERITY] [Category]: [Title]
- **Location**: `file:line`
- **Issue**: [description]
- **Impact**: [what could go wrong]
- **Remediation**: [specific fix with code example]

## Architecture Notes
[Structural observations, dependency map, design pattern assessment]

## Recommendations
[Prioritized list of improvements, ordered by impact]
```

## Severity Levels

- **CRITICAL** — Exploitable vulnerability or data loss risk. Fix immediately.
- **HIGH** — Security weakness or significant quality issue. Fix before merge.
- **MEDIUM** — Code smell, missing validation, or improvement opportunity.
- **LOW** — Style issue, minor optimization, or documentation gap.

## Best Practices

- Read the code before judging — understand intent and context
- Check existing tests before suggesting new ones
- Respect the project's established patterns and conventions
- Provide concrete code examples in remediation suggestions
- Distinguish between blocking issues and nice-to-have improvements
- Never suggest changes without understanding the full call chain
- Flag any hardcoded secrets, tokens, or credentials as CRITICAL
