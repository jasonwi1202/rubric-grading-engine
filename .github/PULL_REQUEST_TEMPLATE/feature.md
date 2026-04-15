## Summary
<!-- What does this PR do? Why? Link to the feature spec or roadmap issue. -->

Closes #

## Changes
<!-- List the key changes made -->
-

## Testing
<!-- How was this tested? Unit / integration / E2E? -->

---

## Checklist

### All PRs
- [ ] Follows branch naming: `feat/mN-<issue>-<slug>` or `fix/mN-<issue>-<slug>` off `release/mN`
- [ ] Conventional commit messages (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `migration:`)
- [ ] Lint passes: `ruff check .` (backend), `eslint` (frontend), zero errors
- [ ] Type check passes: `mypy` (backend), `tsc --noEmit` (frontend)
- [ ] Tests added or updated — unit + at least one integration test for new functionality
- [ ] Coverage gate passes: ≥ 80% overall; ≥ 95% for `backend/app/llm/parsers.py`
- [ ] No student PII in source code, comments, test fixtures, or log statements
- [ ] No secrets, API keys, or credentials committed
- [ ] Documentation updated if behavior changed

### Backend PRs
- [ ] All queries scoped to authenticated `teacher_id` — no cross-teacher data access possible
- [ ] Every grade state change (override, feedback edit, lock) writes an audit log entry
- [ ] Grading uses `assignment.rubric_snapshot` — never the live `Rubric` record
- [ ] All public functions have type annotations (mypy strict)
- [ ] Services contain no HTTP layer imports — routers call services, not the reverse

### LLM / Grading PRs
- [ ] Essay content is in the `user` role only — never in the system prompt
- [ ] System prompt instructs model to ignore directives found in essay content
- [ ] LLM response is validated against schema before any DB write
- [ ] All LLM failure modes have test coverage (parse error, missing criterion, timeout)

### Migration PRs
- [ ] Both `upgrade()` and `downgrade()` implemented and tested as a roundtrip
- [ ] `CREATE INDEX` uses `postgresql_concurrently=True`
- [ ] No `DROP TABLE` / `DROP COLUMN` without prior deprecation step
- [ ] No `UPDATE`/`DELETE` affecting > 1000 rows inline

### Security (all PRs — see `.github/instructions/security.instructions.md`)
- [ ] No student PII in logs, error messages, URL params, or frontend storage
- [ ] Prompt injection defenses in place for any LLM-touching code
- [ ] `audit_logs` table remains INSERT-only — no UPDATE/DELETE paths introduced

> **Instruction files:** backend PRs → `.github/instructions/backend.instructions.md` · frontend PRs → `.github/instructions/frontend.instructions.md` · migration PRs → `.github/instructions/migrations.instructions.md` · test PRs → `.github/instructions/testing.instructions.md`
