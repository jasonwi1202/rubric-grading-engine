# Testing Guide

## Overview

This document defines the testing strategy, tooling, conventions, and coverage expectations for the Rubric Grading Engine. The goal is a test suite that catches real bugs without becoming a maintenance burden — tests should give confidence, not just pass.

---

## Testing Philosophy

- **Test behavior, not implementation** — tests should verify what the system does, not how it does it internally
- **Unit test services and pure logic; integration test boundaries** — routers, database interactions, and LLM parsing need integration coverage
- **Mock external services in unit tests; use real infrastructure in integration tests** — no real OpenAI calls in CI
- **The LLM is a dependency, not a unit** — test the parsing and validation of LLM responses, not the LLM itself

---

## Test Stack

| Layer | Tool |
|---|---|
| Backend unit tests | `pytest` + `pytest-asyncio` |
| Backend integration tests | `pytest` + `httpx` (async test client) + `testcontainers` |
| Backend LLM mocking | `pytest-mock` + fixture-based response stubs |
| Frontend unit tests | `Vitest` + `React Testing Library` |
| Frontend integration | `Vitest` + `MSW` (Mock Service Worker for API mocking) |
| End-to-end tests | `Playwright` |
| Test database | PostgreSQL via `testcontainers` (real DB, isolated per test session) |
| Coverage | `pytest-cov` (backend), `@vitest/coverage-v8` (frontend) |

---

## Backend Testing

### Unit Tests

**What to unit test:**
- Service layer functions (grading_service, feedback_service, rubric_service, etc.)
- LLM response parsers (`llm/parsers.py`)
- Data ingestion logic (text extraction, normalization, skill normalization)
- Utility functions (weight validation, score calculation, fuzzy name matching)

**What NOT to unit test:**
- SQLAlchemy models themselves — test via integration tests
- FastAPI route handlers directly — test via the HTTP test client
- Celery task definitions — test the underlying service functions they call

**Location:** `backend/tests/unit/`

**Example: testing the grading response parser**
```python
# tests/unit/test_grading_parser.py
def test_parse_valid_grading_response():
    raw = {
        "criterion_scores": [
            {"criterion_id": "abc", "score": 4, "justification": "Clear thesis in opening.", "confidence": "high"}
        ],
        "summary_feedback": "Strong overall essay."
    }
    result = parse_grading_response(raw, rubric_snapshot=mock_rubric)
    assert result.criterion_scores[0].score == 4
    assert result.criterion_scores[0].confidence == Confidence.HIGH

def test_parse_response_with_out_of_range_score():
    raw = {"criterion_scores": [{"criterion_id": "abc", "score": 99, ...}], ...}
    result = parse_grading_response(raw, rubric_snapshot=mock_rubric)
    assert result.criterion_scores[0].score == mock_rubric.criteria[0].max_score  # clamped
    assert result.criterion_scores[0].confidence == Confidence.LOW
```

---

### Integration Tests

Integration tests run against a real PostgreSQL instance (via `testcontainers`) and a real Redis instance. They test the full stack from HTTP request to database state.

**What to integration test:**
- All API endpoints (happy path + key error cases)
- Authentication flow (login, refresh, logout, unauthorized access)
- Grading pipeline (mock LLM, real DB writes)
- Audit log entries are written correctly on score overrides and grade locks
- Data isolation — teacher A cannot access teacher B's data

**Location:** `backend/tests/integration/`

**Test database setup:**
- `testcontainers` spins up a real Postgres container per test session
- Alembic migrations are run before tests start
- Each test function runs in a transaction that is rolled back after — no data bleeds between tests

**Example: testing score override creates audit log entry**
```python
# tests/integration/test_grades.py
async def test_score_override_creates_audit_log(client, seeded_grade):
    response = await client.patch(
        f"/api/v1/grades/{seeded_grade.id}/criteria/{seeded_grade.criteria[0].id}",
        json={"teacher_score": 3, "teacher_feedback": "Needs more evidence."},
        headers=auth_headers
    )
    assert response.status_code == 200

    # Verify audit log
    audit = await db.execute(
        select(AuditLog).where(AuditLog.entity_id == seeded_grade.criteria[0].id)
    )
    entry = audit.scalar_one()
    assert entry.action == "score_override"
    assert entry.before_value["ai_score"] == seeded_grade.criteria[0].ai_score
    assert entry.after_value["teacher_score"] == 3
```

---

### LLM Mocking

The OpenAI API is never called in tests. LLM responses are mocked using `pytest-mock` fixtures.

**Fixture pattern:**
```python
# tests/conftest.py
@pytest.fixture
def mock_openai_grading_response():
    return {
        "criterion_scores": [
            {"criterion_id": "{id}", "score": 4, "justification": "Test justification.", "confidence": "high"}
        ],
        "summary_feedback": "Test feedback summary."
    }

@pytest.fixture(autouse=True)
def patch_llm_client(mocker, mock_openai_grading_response):
    mocker.patch(
        "app.llm.client.call_grading",
        return_value=mock_openai_grading_response
    )
```

Test multiple LLM response scenarios explicitly:
- Valid response — happy path
- Missing criterion in response — validation and retry behavior
- Score out of range — clamping behavior
- JSON parse failure — retry then fail behavior
- Timeout — task failure handling

---

### Celery Task Tests

Celery tasks are tested by calling the underlying service function directly — not by running through the Celery worker. This avoids the complexity of running a real broker in tests.

```python
# tests/unit/test_grading_tasks.py
async def test_grade_single_essay_writes_grade_to_db(db_session, mock_essay, mock_rubric_snapshot):
    # Call the service function directly, not the Celery task
    await grade_essay_service(essay_id=mock_essay.id, rubric_snapshot=mock_rubric_snapshot, strictness="balanced")

    grade = await db_session.get(Grade, filter_by_essay_version=mock_essay.current_version_id)
    assert grade is not None
    assert len(grade.criterion_scores) == len(mock_rubric_snapshot.criteria)
```

---

## Frontend Testing

### Unit Tests (Vitest + React Testing Library)

**What to unit test:**
- Individual UI components in isolation (rubric builder form, score control, feedback editor)
- Custom hooks (`useGrading`, `useBatchProgress`, etc.)
- Utility functions (`lib/utils/`, `lib/schemas/`)
- Zod schema validation

**Location:** `frontend/tests/unit/`

**What NOT to unit test:**
- Next.js page components — too much routing/layout coupling; test via integration or E2E
- API client functions — mock at the hook layer, not the fetch layer

### Integration Tests (Vitest + MSW)

MSW intercepts fetch calls and returns mock responses — no real API calls. Test full component trees including data fetching.

**What to integration test:**
- The essay review interface — renders scores, allows override, shows unsaved state warning
- Batch grading progress component — polls correctly, stops on completion
- Rubric builder — validates weights, saves correctly

**Location:** `frontend/tests/integration/`

---

## End-to-End Tests (Playwright)

E2E tests run against a real local environment (Docker Compose) with a seeded test database. They cover critical user journeys, not every edge case.

**Critical journeys to cover:**

1. **Teacher login → create class → add students → create rubric → create assignment**
2. **Upload essays → review auto-assignments → trigger grading → watch progress**
3. **Open review queue → override a score → edit feedback → lock grade**
4. **Export batch as PDF ZIP → download**
5. **View student profile → see skill history across two assignments**

**Location:** `frontend/tests/e2e/`

**Run command:** `docker compose -f docker-compose.test.yml up --abort-on-container-exit`

---

## Coverage Targets

| Layer | Target | Notes |
|---|---|---|
| Backend services | 80% line coverage | Core business logic — high bar |
| Backend routers | 70% | Covered primarily via integration tests |
| Backend LLM parsers | 95% | Parsing is critical and fully deterministic |
| Backend Celery tasks | 60% | Test service functions, not task wiring |
| Frontend components | 70% | Focus on interactive components |
| Frontend hooks | 80% | Data fetching logic |

Coverage is a floor, not a goal. 80% coverage with meaningful tests beats 95% coverage with trivial assertions.

---

## CI Pipeline

Tests run in GitHub Actions (or equivalent) on every push and PR:

1. `pytest` — backend unit + integration tests (with testcontainers)
2. `vitest` — frontend unit + integration tests
3. `playwright` — E2E tests (on PRs to `main` only — slow)
4. Coverage report generated and posted as PR comment
5. PR blocked from merge if coverage drops below targets

**Test isolation:** Each CI run uses a fresh database. No shared test state between runs.

---

## Local Environment Gotchas

Some shell-level environment variables can make local backend tests fail in
ways that do not reproduce in CI.

Common examples:

- `RATE_LIMIT_ENABLED=false` can invalidate rate-limit middleware assertions.
- `ALLOW_UNVERIFIED_LOGIN_IN_TEST=true` can bypass unverified-auth checks.
- `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `S3_ENDPOINT_URL` can break
    tests that assert config defaults.

Before running backend unit tests locally, clear these overrides in your shell:

```powershell
Remove-Item Env:RATE_LIMIT_ENABLED -ErrorAction SilentlyContinue
Remove-Item Env:ALLOW_UNVERIFIED_LOGIN_IN_TEST -ErrorAction SilentlyContinue
Remove-Item Env:DATABASE_POOL_SIZE -ErrorAction SilentlyContinue
Remove-Item Env:DATABASE_MAX_OVERFLOW -ErrorAction SilentlyContinue
Remove-Item Env:S3_ENDPOINT_URL -ErrorAction SilentlyContinue
```
