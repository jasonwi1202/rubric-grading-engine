---
applyTo: "backend/tests/**,frontend/tests/**"
---

# QA / Test Engineer Review Instructions

When reviewing a PR that touches test files, check every item below.

Reference: `docs/architecture/testing-guide.md`

## Coverage Requirements

- [ ] Overall backend test coverage ≥ 80% (`pytest-cov` enforced in CI)
- [ ] LLM response parsers coverage ≥ 95% — `backend/app/llm/parsers.py` is fully deterministic and must be thoroughly tested
- [ ] Every new public service function has at least one **direct unit test** — router-level tests that mock the service at the boundary do not substitute for service unit tests. Service error branches (e.g., `ForbiddenError`, `ConflictError`, soft-delete semantics) must be tested at the service layer.
- [ ] Every new API endpoint has both a happy-path and at least one error-case integration test

## Test Structure

- [ ] Unit tests in `backend/tests/unit/` — no database, no network, no file I/O; pure logic only
- [ ] Integration tests in `backend/tests/integration/` — use `testcontainers` for real PostgreSQL and Redis; all LLM calls mocked
- [ ] Frontend unit/integration tests in `frontend/tests/unit/` and `frontend/tests/integration/`
- [ ] E2E tests in `frontend/tests/e2e/` using Playwright against Docker Compose

## LLM Mocking — Mandatory

- [ ] No real OpenAI API calls in any test — mock via `pytest-mock` fixture
- [ ] LLM mock is applied as an `autouse` fixture — not patched individually in each test
- [ ] **Test assertions must be capable of failing** — an assertion like `assert "direct" in system_content` passes vacuously if the template already contains the word "direct" in multiple places (e.g., in option descriptions). Assertions for injected/templated values must target the specific rendered line or field, not just a substring that is always present. Review each assertion and ask: "would this pass even if the feature was completely broken?"
- [ ] The following LLM failure scenarios have explicit tests:
  - [ ] Valid response (happy path)
  - [ ] JSON parse failure → retry behavior
  - [ ] Missing criterion in response → validation behavior
  - [ ] Score out of range → clamping behavior
  - [ ] Request timeout → task failure handling

Reference: `docs/architecture/testing-guide.md#llm-mocking`

## Tenant Isolation Tests

- [ ] Integration tests for all endpoints that access teacher-scoped data include a cross-teacher access test
- [ ] Cross-teacher test: create resource as Teacher A, authenticate as Teacher B, assert `403`
- [ ] Celery task tests verify `teacher_id` ownership check is performed before loading entities

## Audit Log Tests

- [ ] After any grade change (override, feedback edit, lock), the integration test asserts the correct audit log entry exists
- [ ] Audit assertions query by `entity_id` and `action` — not just `ORDER BY created_at DESC LIMIT 1`

## Test Data Rules

- [ ] No real student names, email addresses, or essay content in test fixtures — use `Faker` or factory helpers
- [ ] No hardcoded UUIDs — generate with `uuid4()` or factory fixtures
- [ ] No hardcoded timestamps — use `datetime.now(UTC)` or `freeze_time`
- [ ] Factories defined in `backend/tests/factories.py` — inline dict construction is not permitted for model instances
- [ ] **No credential-format strings in fixtures or `conftest.py`** — values like `"sk-test"` (OpenAI) or `"AKIATEST"` (AWS) trigger secret scanners (GitHub push protection, truffleHog) even when fake. Use clearly synthetic strings like `"test-openai-key"` or `"fake-aws-key-for-testing"` that no scanner will flag as a real credential format.

## Test Quality

- [ ] No test that always passes regardless of implementation (`assert True`, empty body)
- [ ] No test that tests the mock rather than the real code — mock the I/O boundary, not the function under test
- [ ] Meaningful assertion messages: `assert result == expected, f"Got {result}, expected {expected}"`
- [ ] No `time.sleep()` in tests — use `freeze_time` for time-dependent logic
- [ ] Database is clean before each test — use transaction rollback fixture or explicit TRUNCATE

## SQLAlchemy Async Mock Correctness

- [ ] **`db.add()` and `db.delete()` must be mocked as `MagicMock`, not `AsyncMock`** — these are synchronous methods on `AsyncSession`. Mocking them as `AsyncMock` makes tests pass against incorrect `await db.add(...)` / `await db.delete(...)` calls that would fail at runtime. If production code is fixed to not await these methods, tests that used `AsyncMock` will need to be updated too.
- [ ] **Only awaitable `AsyncSession` methods use `AsyncMock`**: `execute`, `flush`, `commit`, `refresh`, `rollback`, `close`.

## Integration Test Error Assertions

- [ ] Error response assertions use `resp.json()["error"]["code"]` — the API normalizes all errors to `{"error": {"code": ..., "message": ...}}`
- [ ] Do not assert on `resp.json()["detail"]` — that is FastAPI's default, which our error handler overrides

## Playwright E2E Tests

- [ ] New navigable routes are covered by at least one E2E spec
- [ ] Minimum per new page: renders without error, primary data is visible, key interactive element (modal, form) opens and closes
- [ ] No assertions on exact student names or essay content — test structure and behavior, not data values
- [ ] MSW is not used in E2E — tests run against the real Docker Compose stack

## Pre-Push Checklist for Test Files

```bash
# From backend/
ruff check --fix tests/
ruff format tests/
ruff check tests/
pytest tests/unit/test_my_new_file.py -q
```
