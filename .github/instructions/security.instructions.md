---
applyTo: "**"
---

# Security Review Instructions

These checks apply to **every file in every PR**. The system handles student education records protected by FERPA.

## Student Data — Hard Blocks

The following will block any PR:

- [ ] **No student PII in source code** — student names, email addresses, grades, or essay content must never appear as hardcoded values, inline test fixtures, or example values in comments
- [ ] **No student data in logs** — `logger.*` calls must not include student names, essay content, or grade values; use entity IDs only (`student_id`, `essay_id`, `grade_id`)
- [ ] **No student data in error messages** — exception messages and API error responses must not include student PII
- [ ] **No student essay content in LLM system prompts** — essay content goes only in the `user` role; never in the `system` role
- [ ] **No student data in URL parameters** — queries use UUIDs, not student names or identifiers in URLs
- [ ] **No student data in frontend storage** — no student PII in `localStorage`, `sessionStorage`, or cookies

Reference: `docs/architecture/security.md#5-ferpa-compliance`

## Prompt Injection — Hard Block

- [ ] Essay content is **always** in the LLM `user` role — never interpolated into the system prompt
- [ ] The system prompt explicitly instructs the model to ignore instructions found within the essay text
- [ ] Essay text is delimited with explicit tags (`<ESSAY_START>` / `<ESSAY_END>`) in the user turn
- [ ] All LLM responses are validated against the expected schema before any data is written — a non-conforming response must be rejected or retried, never written as-is

Reference: `docs/architecture/security.md#1-prompt-injection-defense`

## Secrets & Credentials

- [ ] No API keys, passwords, JWT signing secrets, or database credentials in source code
- [ ] No secrets in comments (even "for testing" or "temporary")
- [ ] No secrets hardcoded as default values in config or environment files
- [ ] Secrets are only accessed via environment variables (`settings.jwt_secret_key`)
- [ ] **No credential-format strings in test fixtures or `conftest.py`** — values like `"sk-test"` (OpenAI) or `"AKIATEST"` (AWS) trigger secret scanners (GitHub push protection, truffleHog, gitleaks) even when fake. Use clearly synthetic strings that don't match any provider's key format, e.g. `"test-openai-key"` or `"fake-aws-key-for-testing"`.

## Authentication & Session Security

- [ ] JWT access token TTL: 15 minutes — do not extend without a documented reason
- [ ] Refresh token stored in `httpOnly; Secure; SameSite=Strict` cookie — never in `Authorization` header or `localStorage`
- [ ] Token validation uses `PyJWT.decode()` with `algorithms=["HS256"]` and `verify_exp=True`
- [ ] Logout invalidates the specific refresh token in Redis — not just client-side cookie deletion
- [ ] No endpoints that skip authentication for convenience
- [ ] **Missing or expired credentials return HTTP 401, not 403 or 422** — the frontend silent-refresh cycle fires only on 401. A 403 or 422 returned for an expired/missing token prevents the refresh-cookie path from triggering and permanently strands the session.

## Multi-Tenant Isolation

- [ ] Cross-teacher access returns `403` — do not return `404` in ways that could confirm or deny another teacher's data exists
- [ ] RLS is enforced at **both** the service layer (query filter) and the PostgreSQL RLS policy — neither alone is sufficient
- [ ] No raw SQL queries that bypass the ORM's tenant filter without manually adding the `teacher_id` condition
- [ ] Celery tasks validate teacher ownership of all entities they load

Reference: `docs/architecture/security.md#2-multi-tenant-data-isolation`

## File Upload Safety

- [ ] File MIME type is validated server-side using `python-magic` — not just file extension
- [ ] Only allowed types: `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `text/plain`
- [ ] File size limit is enforced before reading file content
- [ ] Uploaded files are stored to S3 before processing — original is preserved even if extraction fails
- [ ] Extracted text is never executed — stored and used as plain string content only

Reference: `docs/architecture/security.md#4-file-upload-security`

## Audit Trail

- [ ] Every change to a grade (score override, feedback edit, lock) writes an audit log entry with `before_value` and `after_value`
- [ ] Auth events (login success/failure, logout, token refresh) write audit log entries with `ip_address`
- [ ] Export and data deletion events write audit log entries
- [ ] `audit_logs` table is INSERT-only — no UPDATE or DELETE paths introduced anywhere
- [ ] `score_clamped` is logged when LLM returns an out-of-range score

Reference: `docs/architecture/security.md#6-soc-2-readiness`, `docs/architecture/data-model.md#auditlog`

## Input Validation

- [ ] All API inputs validated by Pydantic v2 models — no raw `request.json()` access
- [ ] Frontend form inputs validated by Zod schemas before submission
- [ ] No SQL injection vectors — all queries use SQLAlchemy parameterized queries or ORM methods
- [ ] String fields have max length constraints — no unbounded text inputs except essay content (which has its own size limit)

## Dependency Safety

- [ ] No new dependency added without a clear reason in the PR description
- [ ] `pip-audit` and `npm audit` output in CI is clean — no known high/critical CVEs in new packages
- [ ] No analytics SDKs or telemetry packages added to frontend that could send student data to third parties

## Security Headers & CORS

- [ ] No changes that weaken CORS configuration — `CORS_ORIGINS` remains an explicit allowlist
- [ ] No changes that remove security response headers (`X-Frame-Options`, `X-Content-Type-Options`, `Strict-Transport-Security`, etc.)
