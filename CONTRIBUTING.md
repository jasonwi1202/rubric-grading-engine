# Contributing

Thank you for contributing to the Rubric Grading Engine. This document covers everything you need to get started: branching model, commit conventions, PR process, and coding standards.

---

## Before You Start

1. Read [`docs/prd/product-vision.md`](docs/prd/product-vision.md) — understand what this product is and what it is not
2. Read the **Non-Negotiable Implementation Rules** in [`.github/copilot-instructions.md`](.github/copilot-instructions.md) — these apply to all contributors, human and AI
3. Check [`docs/roadmap.md`](docs/roadmap.md) to understand which milestone is active and what's in scope

---

## Branching Model

```
main  (stable — tagged releases only)
  └── release/mN  (milestone integration branch)
        ├── feat/mN-<issue-number>-<slug>
        └── fix/mN-<issue-number>-<slug>
```

**Rules:**
- Never push directly to `main` or `release/mN`
- All work goes through a feature branch PR targeting the active `release/mN` branch
- `main` is only updated by merging a completed `release/mN` branch
- Branch from `release/mN`, not from `main`

```bash
# Start a new issue
git checkout release/m1
git pull origin release/m1
git checkout -b feat/m1-23-rubric-templates
```

---

## Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(rubric): add template picker to assignment creation
fix(grading): clamp criterion scores before DB write
chore(deps): bump pydantic to 2.7.0
docs(api): update endpoint reference for /grades
test(tenant): add cross-teacher isolation test for essays
migration: add prompt_version column to grades
```

Scopes are optional but helpful. Keep the subject line under 72 characters.

---

## Pull Requests

1. Open your PR **targeting `release/mN`** — not `main`
2. Reference the GitHub issue: `Closes #N`
3. Add exactly one `type:` label (see label reference in [`.github/copilot-instructions.md`](.github/copilot-instructions.md))
4. The default PR template will pre-populate a checklist — complete every applicable item before requesting review
5. For release PRs (merging `release/mN` → `main`), use the release template: append `?template=release.md` to the PR URL

---

## Code Standards

### Backend (Python)

- Formatter and linter: **Ruff** (`ruff check . && ruff format .` from `backend/`)
- Type checker: **mypy** (strict mode)
- All public functions must have type annotations
- `AsyncSession` only — no synchronous SQLAlchemy
- No business logic in routers; no HTTP concerns in services
- Secrets via `settings.*` only — never `os.environ.get()`

```bash
# Before every push (from backend/)
ruff check --fix . && ruff format . && mypy
pytest tests/unit -q
```

### Frontend (TypeScript)

- Linter: **ESLint** (`npm run lint` from `frontend/`)
- Type checker: `tsc --noEmit`
- TypeScript strict mode — no `any`, no `@ts-ignore` without explanation
- All API calls through `lib/api/client.ts` — no raw `fetch()`
- All server state via React Query — no `useEffect + fetch`

```bash
# Before every push (from frontend/)
npm run lint && npx tsc --noEmit && npm test -- --run
```

### Database Migrations

- Generate with `alembic revision --autogenerate -m "<description>"`
- Always implement both `upgrade()` and `downgrade()`
- Test roundtrip locally: upgrade → downgrade → upgrade
- See [`.github/instructions/migrations.instructions.md`](.github/instructions/migrations.instructions.md) for zero-downtime rules

---

## Testing

| Layer | Tool | Location |
|---|---|---|
| Backend unit | pytest | `backend/tests/unit/` |
| Backend integration | pytest + testcontainers | `backend/tests/integration/` |
| Frontend unit/component | Vitest + Testing Library | `frontend/tests/unit/` |
| Frontend integration | Vitest + MSW | `frontend/tests/integration/` |
| E2E | Playwright | `frontend/tests/e2e/` |

**Coverage gates:** ≥ 80% overall backend; ≥ 95% for `backend/app/llm/parsers.py`

**No real LLM calls in tests.** The OpenAI client is always mocked. See [`docs/architecture/testing-guide.md`](docs/architecture/testing-guide.md) for mocking patterns.

**No student PII in fixtures.** Use `Faker` or the factory helpers in `backend/tests/factories.py`. No hardcoded names or essay content.

---

## Security & FERPA

This system handles student education records. Before submitting any PR:

- Review [`.github/instructions/security.instructions.md`](.github/instructions/security.instructions.md)
- No student PII in logs, error messages, test fixtures, or comments
- Essay content always in the LLM `user` role — never the system prompt
- No secrets committed — use `settings.*` for all credential access

Report security vulnerabilities via [SECURITY.md](SECURITY.md), not as public issues.

---

## Getting Help

- Architecture questions → check `docs/architecture/` first
- Feature scope questions → check `docs/features/` and `docs/prd/product-vision.md`
- Unsure which milestone an issue belongs to → check `docs/roadmap.md`
- Found a rule you disagree with → open a discussion issue rather than silently working around it
