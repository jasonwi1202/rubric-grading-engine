# Rubric Grading Engine

A **teacher-facing AI grading assistant** for K-12 writing instruction. Teachers upload student essays, the AI grades each one against a rubric with per-criterion scores and written justifications, and the teacher reviews, overrides, and locks grades before any feedback is shared.

> **Human-in-the-loop always.** The AI prepares; the teacher decides. No grade is recorded and no feedback is shared without explicit teacher approval.

---

## What It Does

- **AI Grading** — score essays against any rubric, per criterion, with evidence-grounded justifications
- **Teacher Review** — override scores, edit feedback, and lock grades before anything is shared
- **Batch Processing** — grade a full class in the background; review results as they complete
- **Export** — PDF feedback packets, CSV gradebook exports, clipboard copy for any LMS
- **Student Profiles** — persistent skill tracking across assignments and academic years
- **Class Insights** — skill heatmaps, common issues, score distributions, cross-assignment trends
- **Instruction Engine** — targeted exercises, mini-lesson recommendations, and student groupings by skill gap
- **Academic Integrity** — AI-generated content detection and cross-submission similarity signals

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 + TypeScript (App Router) |
| UI | shadcn/ui + Tailwind CSS |
| Backend API | FastAPI + Python 3.12 |
| Database | PostgreSQL 16 + pgvector |
| Task queue | Celery 5 + Redis 7 |
| File storage | S3-compatible (configurable endpoint) |
| LLM | OpenAI API (model configurable) |
| Local dev | Docker Compose |

---

## Project Status

Currently in active development. See [`docs/roadmap.md`](docs/roadmap.md) for milestones and planned issues.

| Milestone | Status |
|---|---|
| M0 — Project Scaffold | Not started |
| M1 — Foundation (core grading MVP) | Not started |
| M2 — Workflow | Not started |
| M3 — Student Intelligence | Not started |
| M4 — Prioritization & Instruction | Not started |
| M5 — Closed Loop | Not started |

---

## Getting Started

> Prerequisites: Docker Desktop, Node.js 20+, Python 3.12+

```bash
# 1. Clone the repo
git clone https://github.com/<org>/rubric-grading-engine.git
cd rubric-grading-engine

# 2. Copy environment template
cp .env.example .env
# Edit .env — minimum required vars are documented in docs/architecture/configuration.md

# 3. Start all services
docker compose up

# 4. Apply database migrations
docker compose exec backend alembic upgrade head

# 5. Open the app
# Frontend: http://localhost:3000
# Backend API docs: http://localhost:8000/docs
```

The first `docker compose up` will pull and build all images. Subsequent starts are fast.

---

## Development

### Backend

```bash
cd backend
pip install -e ".[dev]"

# Lint + format
ruff check . && ruff format .

# Type check
mypy

# Tests
pytest tests/unit -q
pytest tests/integration -q   # requires Docker
```

### Frontend

```bash
cd frontend
npm install

# Dev server (requires backend running)
npm run dev

# Lint + type check
npm run lint && npx tsc --noEmit

# Tests
npm test -- --run
```

### Running CI checks locally

```bash
# Backend (from backend/)
ruff check . && ruff format --check . && mypy && pytest tests/unit -q

# Frontend (from frontend/)
npm run lint && npx tsc --noEmit && npm test -- --run
```

---

## Documentation

Full documentation lives in [`docs/`](docs/README.md).

| What | Where |
|---|---|
| Architecture overview | [`docs/architecture/`](docs/architecture/) |
| Feature specifications | [`docs/features/`](docs/features/) |
| Product vision & principles | [`docs/prd/product-vision.md`](docs/prd/product-vision.md) |
| Roadmap & GitHub issues | [`docs/roadmap.md`](docs/roadmap.md) |
| Data model | [`docs/architecture/data-model.md`](docs/architecture/data-model.md) |
| API design | [`docs/architecture/api-design.md`](docs/architecture/api-design.md) |
| Security | [`docs/architecture/security.md`](docs/architecture/security.md) |
| Configuration reference | [`docs/architecture/configuration.md`](docs/architecture/configuration.md) |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branching model, commit conventions, PR process, and coding standards.

## Security

See [SECURITY.md](SECURITY.md) to report a vulnerability. Do not open a public issue for security problems.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history.

