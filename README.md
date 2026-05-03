# Rubric Grading Engine

A **teacher-facing AI grading assistant** for K-12 writing instruction. Teachers upload student essays, the AI grades each one against a rubric with per-criterion scores and written justifications, and the teacher reviews, overrides, and locks grades before any feedback is shared.

> **Human-in-the-loop always.** The AI prepares; the teacher decides. No grade is recorded and no feedback is shared without explicit teacher approval.

---

## What It Does

- **AI Grading** — score essays against any rubric, per criterion, with evidence-grounded justifications
- **Teacher Review** — override scores, edit feedback, and lock grades before anything is shared
- **Batch Processing** — grade a full class in the background; review results as they complete
- **Teacher Worklist** — prioritize who needs intervention first, with actionable status workflows
- **Intervention Recommendations** — review and approve agent-generated intervention suggestions before any follow-up action
- **Teacher Copilot** — ask natural-language questions about class trends and risk signals in a read-only conversational UI
- **Auto-Grouping** — cluster students by shared skill gaps for small-group instruction
- **Export** — PDF feedback packets, CSV gradebook exports, clipboard copy for any LMS
- **Student Profiles** — persistent skill tracking across assignments and academic years
- **Class Insights** — skill heatmaps, common issues, score distributions, cross-assignment trends
- **Instruction Engine** — targeted exercises and mini-lesson recommendations tied to observed gaps
- **Resubmission Loop** — versioned essay resubmissions with revision comparison and improvement signals
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
| M1 — Project Scaffold | Complete |
| M2 — Public Website & Onboarding | Complete |
| M3 — Foundation | Complete |
| M4 — Workflow | Complete |
| M5 — Student Intelligence | Complete |
| M6 — Prioritization & Instruction | Complete |
| M7 — Closed Loop | Complete |
| MX — Cross-Cutting | Ongoing |

---

## Getting Started

> Prerequisites: Docker Desktop, Node.js 20+, Python 3.12+

**Want to try the app without setting up a development environment?**  
See **[DEMO.md](DEMO.md)** — spin up the full stack in one command, no `.env` file needed.

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
| **Demo setup** | [**DEMO.md**](DEMO.md) |
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

