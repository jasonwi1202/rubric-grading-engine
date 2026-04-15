# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues by emailing **security@[your-domain]** (update this address before going live). Include:

- A description of the vulnerability and its potential impact
- Steps to reproduce
- Any suggested remediation if you have one

You will receive an acknowledgment within 48 hours. We will keep you informed as we investigate and will credit your report in the release notes unless you prefer to remain anonymous.

---

## Scope

This system handles student education records protected under FERPA. The following are in scope for responsible disclosure:

- Authentication bypass or session hijacking
- Cross-teacher data access (tenant isolation failures)
- Prompt injection via essay content that causes the LLM to reveal or manipulate grades
- Student PII exposure in logs, error messages, or API responses
- SQL injection or other injection attacks
- Insecure file upload handling
- Secrets exposed in source code, logs, or API responses

---

## Out of Scope

- Denial of service attacks
- Social engineering of project maintainers
- Issues in third-party dependencies (report those to the dependency maintainer directly; we monitor `pip-audit` and `npm audit` in CI)
- Theoretical vulnerabilities without a proof of concept

---

## Supported Versions

Only the latest release is actively supported with security patches. Older milestone releases are not backpatched.

---

## Security Architecture

See [`docs/architecture/security.md`](docs/architecture/security.md) for the full security design, including:

- Prompt injection defense strategy
- Multi-tenant data isolation (application + RLS)
- FERPA compliance controls
- Authentication and session security
- File upload safety
