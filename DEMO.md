# Running the GradeWise Demo

This guide walks you through spinning up the full GradeWise stack locally in a single command using Docker Compose, and verifying everything is healthy with the included smoke test.

**No API keys are required to explore the UI and backend.**  
You only need an OpenAI key if you want to run actual AI grading jobs.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | 4.x+ | Engine 24+ recommended |
| Python | 3.8+ | Stdlib only — no `pip install` needed for the smoke test |

That's it. Node.js and Python virtual environments are **not** required for the demo.

---

## Quick Start (3 steps)

### Step 1 — Start the stack

```bash
docker compose -f docker-compose.demo.yml up -d
```

This pulls all images and starts:

| Service | What it does | URL |
|---|---|---|
| `postgres` | Database (PostgreSQL 16 + pgvector) | — |
| `redis` | Task broker / cache | — |
| `minio` | S3-compatible file storage | [localhost:9001](http://localhost:9001) |
| `mailpit` | Email sink (catches all outbound mail) | [localhost:8025](http://localhost:8025) |
| `backend` | FastAPI app + Uvicorn | [localhost:8000/docs](http://localhost:8000/docs) |
| `demo-seed` | Runs DB migrations (one-shot) | — |
| `worker` | Celery worker for async grading | — |
| `frontend` | Next.js app | [localhost:3000](http://localhost:3000) |

The first run downloads ~1 GB of images and builds the backend and frontend images. Subsequent starts are fast.

### Step 2 — Wait and verify

```bash
python scripts/smoke_test_demo.py
```

The script automatically waits up to 120 seconds for the backend to become healthy, then runs 18 checks across all services. Example output:

```
GradeWise demo smoke test
  API:      http://localhost:8000
  Frontend: http://localhost:3000
  Mailpit:  http://localhost:8025

⏳ Waiting for backend to be ready (up to 120s)...
✓ Backend ready after ~45s

Running 18 checks...

  ✓  Backend: health endpoint                        HTTP 200   38ms
  ✓  Backend: OpenAPI schema reachable               HTTP 200   12ms
  ✓  Backend: API docs page                          HTTP 200   8ms
  ✓  Frontend: homepage (/)                          HTTP 200   6201ms
  ✓  Frontend: /product                              HTTP 200   842ms
  ...
  ✓  Mailpit: web UI reachable                       HTTP 200   2ms
  ✓  Mailpit: API messages endpoint                  HTTP 200   1ms

Results: 18 passed, 0 failed / 18 total

✓ Demo stack is healthy.
  Open the app:       http://localhost:3000
  API docs:           http://localhost:8000/docs
  Mailpit (email UI): http://localhost:8025
  MinIO console:      http://localhost:9001  (minioadmin / minioadmin)
```

### Step 3 — Open the app

| URL | What you'll find |
|---|---|
| [http://localhost:3000](http://localhost:3000) | GradeWise frontend |
| [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive API docs (Swagger UI) |
| [http://localhost:8025](http://localhost:8025) | Mailpit — see all emails sent by the app |
| [http://localhost:9001](http://localhost:9001) | MinIO console — browse uploaded files (`minioadmin` / `minioadmin`) |

---

## Using the App

### Sign up

1. Go to [http://localhost:3000/signup](http://localhost:3000/signup)
2. Fill in your name, email, and a password
3. Click **Create Account**
4. Check [Mailpit](http://localhost:8025) for the verification email — click the link to verify your account
5. You'll be redirected to the onboarding wizard

All email is trapped locally by Mailpit. Nothing is sent to a real inbox.

### AI grading (optional — requires OpenAI API key)

If you want to test AI grading, set `OPENAI_API_KEY` before starting the stack:

```bash
# macOS / Linux
OPENAI_API_KEY=sk-... docker compose -f docker-compose.demo.yml up -d

# Windows PowerShell
$env:OPENAI_API_KEY="sk-..."
docker compose -f docker-compose.demo.yml up -d
```

Without a key the app starts normally; grading tasks will fail with an API error when submitted.

---

## Smoke Test Options

```bash
# Default: wait up to 120s, retry each check 3 times
python scripts/smoke_test_demo.py

# Skip the readiness wait (useful if you know the stack is already up)
python scripts/smoke_test_demo.py --no-wait

# Increase wait time for slow machines
python scripts/smoke_test_demo.py --max-wait 180

# Custom URLs
python scripts/smoke_test_demo.py \
  --api-url http://localhost:8000 \
  --frontend-url http://localhost:3000 \
  --mailpit-url http://localhost:8025
```

---

## Stopping and Resetting

```bash
# Stop all containers (preserves data volumes)
docker compose -f docker-compose.demo.yml down

# Stop and wipe all data (clean slate)
docker compose -f docker-compose.demo.yml down -v

# View logs
docker compose -f docker-compose.demo.yml logs -f

# View logs for a specific service
docker compose -f docker-compose.demo.yml logs -f backend
```

---

## Troubleshooting

### Port conflicts

If any port is already in use, Docker will refuse to start the affected service. Check which ports are in use and stop the conflicting process, or edit `docker-compose.demo.yml` to use different host ports.

```bash
# macOS / Linux
lsof -i :3000 -i :8000 -i :8025 -i :5432 -i :6379

# Windows
netstat -ano | findstr "3000 8000 8025 5432 6379"
```

### Backend starts but migrations fail

Check the `demo-seed` container logs:

```bash
docker compose -f docker-compose.demo.yml logs demo-seed
```

If migrations fail, try a clean restart:

```bash
docker compose -f docker-compose.demo.yml down -v
docker compose -f docker-compose.demo.yml up -d
```

### Frontend shows a "Cannot connect to API" error

The frontend depends on the backend being healthy before starting. Wait 60–90 seconds after `docker compose up` for all services to start. Run the smoke test to confirm all services are healthy.

### Smoke test times out

The default 120-second wait is usually enough, but image builds on a slow connection or machine can take longer:

```bash
python scripts/smoke_test_demo.py --max-wait 300
```

### Rebuild images after code changes

```bash
docker compose -f docker-compose.demo.yml build
docker compose -f docker-compose.demo.yml up -d
```

---

## What's Included in the Demo Stack

The demo compose file (`docker-compose.demo.yml`) differs from the development `docker-compose.yml` in a few ways:

| Aspect | Development (`docker-compose.yml`) | Demo (`docker-compose.demo.yml`) |
|---|---|---|
| Environment | Loaded from `.env` file | All variables inlined — no `.env` needed |
| Backend command | `uvicorn --reload` (hot reload) | `uvicorn` (no reload, simpler) |
| Source mounts | `./backend:/app` and `./frontend:/app` | No source mounts — runs built image |
| Migrations | Manual (`docker compose exec backend alembic upgrade head`) | Auto-run by `demo-seed` service on startup |
| Data volumes | `postgres_data`, `redis_data`, `minio_data` | `demo_postgres_data`, `demo_redis_data`, `demo_minio_data` (separate from dev) |
| Secrets | Real secrets from `.env` | Fixed demo-only values (clearly labelled, not for production) |

The demo stack uses separate named volumes (`demo_*`) so it never interferes with your development database.
