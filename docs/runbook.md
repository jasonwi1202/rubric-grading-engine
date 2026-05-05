# Operational Runbook — Rubric Grading Engine

**Audience:** On-call engineers, incident commanders, engineering leadership  
**Purpose:** Concrete, step-by-step guidance for triaging and resolving production incidents without tribal knowledge  
**Last updated:** 2026-05  
**Owner:** Engineering lead

Related documents:
- [Monitoring & alerting baseline](architecture/deployment.md#monitoring--alerting)
- [Deployment & rollback procedures](architecture/deployment.md#rollback)
- [Security & FERPA compliance](architecture/security.md)
- [Error handling reference](architecture/error-handling.md)

---

## Table of Contents

1. [Severity Classification](#1-severity-classification)
2. [On-Call Contacts and Escalation Path](#2-on-call-contacts-and-escalation-path)
3. [Incident Response Checklist](#3-incident-response-checklist)
4. [Scenario Runbooks](#4-scenario-runbooks)
   - [S1 — Degraded API Health / Availability Down](#s1--degraded-api-health--availability-down)
   - [S2 — Worker Queue Backlog](#s2--worker-queue-backlog)
   - [S3 — Database Issues](#s3--database-issues)
   - [S4 — Authentication Failures](#s4--authentication-failures)
   - [S5 — Storage (S3) Failures](#s5--storage-s3-failures)
   - [S6 — Third-Party Outages (OpenAI / LLM)](#s6--third-party-outages-openai--llm)
5. [FERPA and Privacy Breach Response](#5-ferpa-and-privacy-breach-response)
6. [Communications Templates](#6-communications-templates)
7. [Post-Incident Review (Post-Mortem)](#7-post-incident-review-post-mortem)
8. [Tabletop Exercise Walkthrough](#8-tabletop-exercise-walkthrough)

---

## 1. Severity Classification

Every incident is assigned a severity level at detection time. The severity drives paging behavior, stakeholder notification, and resolution time targets.

| Level | Name | Definition | Acknowledgment | Resolution / Escalation |
|---|---|---|---|---|
| **P1** | Critical | Student data exposed externally; system completely down and unusable; auth totally broken | **15 min** | **60 min** — resolve or escalate to incident commander |
| **P2** | High | Grading pipeline down; auth intermittently failing; data integrity issue detected; storage writes blocked | **30 min** | **2 hours** — resolve or escalate |
| **P3** | Medium | Degraded performance (high latency, some 5xx); non-critical feature broken; single school affected | **2 hours** (business hours) | **24 hours** |
| **P4** | Low | Minor UI issue; cosmetic bug; documentation error | Next business day | Next sprint |

**Downgrade rule:** If a P1 is confirmed to involve no student data exposure, downgrade to P2.  
**Upgrade rule:** If a P2 incident shows any evidence of unauthorized data access, upgrade immediately to P1 and follow the [FERPA breach response](#5-ferpa-and-privacy-breach-response).

---

## 2. On-Call Contacts and Escalation Path

> **Fill in before production launch.** The table below shows the role structure. Replace placeholder text with actual names, Slack handles, and phone numbers. Store the complete contact list in your organization's secure internal wiki — not in this public document.

| Role | Responsibility | First contacted when |
|---|---|---|
| **On-call engineer** | First responder; acknowledges within target time; executes runbook | All P1 and P2 alerts |
| **Lead engineer** | Escalation target; architectural decisions; authorizes rollback | On-call cannot resolve within 30 min |
| **Incident commander** | Overall coordination; external comms; FERPA notification decision | P1 incidents; P2 that escalates past 30 min |
| **Legal / compliance contact** | FERPA and breach notification decisions | Any incident involving potential student data exposure |
| **School administrator contact** | Recipient of FERPA notification | Only contacted by incident commander; not by on-call engineer directly |

**Escalation path:**  
Alert fires → On-call engineer acknowledges → Executes this runbook → If unresolved within 30 min, calls lead engineer → If P1 or unresolved within 60 min, activates incident commander → Incident commander decides on external notification

---

## 3. Incident Response Checklist

Use this checklist for every P1 and P2 incident. For P3, the checklist is optional but the timeline capture row is required.

### 3.1 At Detection (T+0)

- [ ] **Acknowledge the alert** in your alerting tool to stop the pager cascade
- [ ] **Classify severity** using the table in [Section 1](#1-severity-classification)
- [ ] **Open an incident channel** — create a dedicated Slack channel named `#inc-YYYY-MM-DD-<slug>` (e.g., `#inc-2026-05-14-api-down`)
- [ ] **Post the incident opener** using the [comms template](#61-incident-opener-slack) in the channel
- [ ] **Start a running timeline** (copy the [timeline template](#63-incident-timeline-log) into the channel pinned message or a shared doc)
- [ ] **Check for Railway status** — go to [railway.com/status](https://railway.com/status) to rule out a Railway infrastructure outage before debugging further
- [ ] **Go to the scenario runbook** that matches your alert signal (see [Section 4](#4-scenario-runbooks))

### 3.2 During Investigation

- [ ] **Post a status update every 15 min** to the incident channel until resolved (use the [update template](#62-status-update-slack))
- [ ] **Log every action taken** in the timeline — commands run, services restarted, config changes made
- [ ] **Do not delete or modify logs** — they are the evidence trail
- [ ] **Escalate if needed** — if you are stuck after 30 min on P1/P2, call the lead engineer now, not later

### 3.3 FERPA / Security Gate

Before taking any mitigation action that involves rotating secrets, taking a service offline, or accessing student records, stop and check:

- [ ] **Does this incident involve any potential unauthorized access to student data?**
  - If **yes**: immediately escalate to incident commander and do NOT take further action without authorization. Follow [Section 5](#5-ferpa-and-privacy-breach-response).
  - If **no**: proceed with mitigation
- [ ] **Are you accessing student data (essays, scores, names) directly in the database to diagnose?**
  - Minimize this. Use entity IDs only in notes. Never paste student essay content into Slack or any chat tool.
  - If you must query student records for diagnosis, note the query in the timeline and do not export the data

### 3.4 At Resolution

- [ ] **Confirm resolution** — run the verification steps in the relevant scenario runbook
- [ ] **Post the all-clear** using the [resolution template](#64-resolution-message-slack)
- [ ] **Downgrade the alert** in your alerting tool
- [ ] **If P1**: notify incident commander to evaluate FERPA notification obligations
- [ ] **Update the incident log** — record the final resolution, root cause summary, and corrective action
- [ ] **Schedule post-mortem** — within 2 business days for P1; within 5 business days for P2

### 3.5 Severity Classification Fields (for incident log)

Every incident record must include:

| Field | Description |
|---|---|
| `incident_id` | `INC-YYYY-MM-DD-NNN` (sequential within day) |
| `severity` | P1 / P2 / P3 |
| `detected_at` | UTC timestamp |
| `acknowledged_at` | UTC timestamp |
| `resolved_at` | UTC timestamp |
| `affected_services` | e.g., `backend, worker` |
| `affected_schools` | List of school IDs (not school names in logs) |
| `student_data_exposed` | `yes` / `no` / `under investigation` |
| `root_cause` | One-line summary |
| `corrective_actions` | What was changed to resolve |
| `ferpa_notification_required` | `yes` / `no` / `pending legal review` |

---

## 4. Scenario Runbooks

Each scenario runbook follows the same structure:
- **Detection signals** — alert rule(s) that fire, log queries
- **First checks** — quick diagnostics to confirm the scenario
- **Mitigation steps** — ordered actions to restore service
- **Rollback trigger** — when to stop mitigation and revert to the previous deployment
- **Verification** — how to confirm the issue is resolved
- **Escalation owner** — who is responsible if this runbook does not resolve the issue

---

### S1 — Degraded API Health / Availability Down

**Typical P-level:** P1 (complete down) or P2 (degraded)

#### Detection Signals

| Signal | Alert rule | Severity |
|---|---|---|
| Railway health check fails | HTTP 503 on `GET /api/v1/readiness` | 🔴 P1 |
| API error rate high | `event:"http.request" status_code:>=500` > 5% over 5 min | 🔴 P1 |
| API p95 latency high | `event:"http.request" latency_ms:>2000` > 10% over 5 min | 🟡 P2 |
| External uptime monitor fires | Any occurrence of HTTP 503 on public URL | 🔴 P1 |

#### First Checks

1. **Is Railway itself down?** Check [railway.com/status](https://railway.com/status). If yes, this is a third-party incident — notify schools, track Railway's updates.

2. **Which service is failing?**
   ```
   # Log query in your aggregator
   event:"http.request" status_code:>=500
   ```
   Look at the `path` field to identify whether failures are backend-wide or scoped to one endpoint.

3. **What does the health probe say?**
   ```
   GET https://api.{yourdomain}.com/api/v1/health
   GET https://api.{yourdomain}.com/api/v1/readiness
   ```
   If `"database": "degraded"` → go to [S3 — Database Issues](#s3--database-issues)  
   If `"redis": "degraded"` → check Redis service in Railway dashboard  
   If both are `"ok"` but errors continue → application-level issue; check worker logs

4. **Check Railway backend service restarts:**  
   Railway Dashboard → `backend` service → Deployments → look for restart loops

5. **Is there a recent deployment?**  
   Railway Dashboard → `backend` service → Deployments → compare timestamps to when the alert fired. If the outage started within 5 minutes of a deploy, [trigger a rollback](#rollback-trigger) immediately.

#### Mitigation Steps

**Case A — High error rate after a deploy:**
1. Trigger a rollback immediately (see [Rollback Trigger](#rollback-trigger) below)
2. Confirm the previous version is serving traffic
3. Verify error rate returns to baseline

**Case B — Database or Redis connectivity:**
1. Check Railway Dashboard → PostgreSQL service → ensure it is running
2. Check Railway Dashboard → Redis service → ensure it is running
3. If a Railway-managed service is down, check Railway status page and await their restoration
4. If PostgreSQL is up but the backend cannot connect, check `DATABASE_URL` variable in backend service settings — Railway service restarts may occasionally lose private-network resolution; a backend service restart usually resolves this

**Case C — Application crash / OOM:**
1. Railway Dashboard → `backend` service → check memory graph for OOM events
2. If OOM, scale the backend service to the next memory tier in Railway settings
3. If crash loop, check logs for the exception:
   ```
   logger:"uvicorn" level:"ERROR"
   ```
4. If a code bug is identified, trigger a rollback

**Case D — Dependency issue (no DB/Redis problem, no recent deploy):**
1. Check for `LLM_UNAVAILABLE` errors → go to [S6](#s6--third-party-outages-openai--llm)
2. Restart the backend service in the Railway dashboard — this resolves transient connection pool exhaustion
3. If restart does not help, check for a connection pool misconfiguration (`DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW` in environment variables)

#### Rollback Trigger

Trigger a rollback if:
- The outage started within 5 min of a deploy **and** the new deploy is confirmed as the cause
- 15 min of investigation has not revealed a fixable root cause
- The error rate is above 20% for more than 10 minutes

**How to rollback:**  
Railway Dashboard → `backend` service → Deployments → click the previously successful deployment → Redeploy.  
Do the same for `worker` and `beat` services if they were also updated.  
See [deployment.md — Rollback](architecture/deployment.md#rollback) for full procedure.

#### Verification

- `GET /api/v1/readiness` returns HTTP 200 with `"status": "ready"`
- `event:"http.request" status_code:>=500` count drops below 1% over 5 min
- External uptime monitor shows green

#### Escalation Owner

Lead engineer if unresolved in 30 minutes. Incident commander if P1 and unresolved in 60 minutes.

---

### S2 — Worker Queue Backlog

**Typical P-level:** P2 (depth >50) or P1 (depth >200, workers appear down)

#### Detection Signals

| Signal | Alert rule | Severity |
|---|---|---|
| Queue depth warning | `event:"celery.queue_depth" queue:"celery" depth:>50` | 🟡 P2 |
| Queue depth critical | `event:"celery.queue_depth" queue:"celery" depth:>200` | 🔴 P1 |
| Queue monitor failure | `event:"celery.queue_monitor_error"` | 🟡 P2 (Redis may be down) |
| No queue events in 2 min | Absence of `event:"celery.queue_depth"` for > 2 min | 🔴 P1 (beat or Redis may be down) |

#### First Checks

1. **Is the queue monitor (beat) running?**  
   Railway Dashboard → `beat` service → ensure it is running. If it is stopped or crash-looping, the queue depth alerts will be absent entirely.

2. **Are workers processing any tasks?**  
   Railway Dashboard → `worker` service → check CPU usage. If CPU is flat-zero, workers are idle or dead.

3. **What does the queue depth look like over time?**
   ```
   event:"celery.queue_depth" queue:"celery"
   ```
   Is depth growing (tasks entering faster than workers process) or flat-high (workers stopped)?

4. **Are tasks failing?**
   ```
   logger:"app.tasks.grading" level:"ERROR"
   ```
   Repeated task errors cause them to be re-queued, building up depth without workers being "stuck."

5. **Is Redis reachable?**  
   Railway Dashboard → Redis service → ensure it is running and memory usage is below its tier limit.

#### Mitigation Steps

**Case A — Workers crashed / not running:**
1. Railway Dashboard → `worker` service → restart the service
2. Monitor CPU; it should spike as workers begin processing queued tasks
3. If workers crash again immediately, check logs:
   ```
   logger:"celery.worker" level:"ERROR"
   ```
4. If a bad task is causing repeated crashes, identify the task type from error logs, then:
   - If the bad task is safe to discard: [purge the specific queue](#purging-the-queue) (see note below)
   - If tasks contain student data that must not be lost: do not purge; pause the worker, fix the underlying issue, then restart

**Case B — Queue growing because tasks are slow (workers running):**
1. Check whether a specific task type dominates the queue:
   ```
   logger:"app.tasks" level:"INFO"
   ```
2. If grading tasks are slow due to LLM latency → go to [S6](#s6--third-party-outages-openai--llm)
3. If DB queries in tasks are slow → go to [S3](#s3--database-issues)
4. If tasks are just slower than expected, scale the worker concurrency:  
   Railway Dashboard → `worker` service → Settings → Start Command → increase `--concurrency` from 4 to 8

**Case C — Beat process not emitting metrics:**
1. Railway Dashboard → `beat` service → restart if stopped
2. If beat is running but no metrics: check Redis connection from beat logs
3. Beat restart resolves most metric-absence false alarms

**Purging the queue** (emergency only, with incident commander authorization):  
Only purge if tasks are confirmed safe to discard (e.g., the same assignment is being re-graded anyway). Never purge without logging the action.

```bash
# SSH to a Railway shell or run via Railway's exec command
celery -A app.tasks.celery_app purge -Q celery --force
```

#### Rollback Trigger

Trigger a rollback if:
- Workers crash immediately after restart and the crash started after a recent deploy

#### Verification

- `event:"celery.queue_depth" queue:"celery" depth:>50` clears
- Worker CPU shows task processing activity
- Grading tasks complete successfully (check a test grading trigger in staging first)

#### Escalation Owner

Lead engineer if workers do not recover after restart. If student data may have been lost from the queue, escalate to incident commander.

---

### S3 — Database Issues

**Typical P-level:** P1 (complete unavailability or data integrity) or P2 (degraded performance)

#### Detection Signals

| Signal | Alert rule | Severity |
|---|---|---|
| Health probe shows DB degraded | `message:"Health check: database unavailable"` | 🔴 P1 |
| Health probe HTTP 503 | Readiness endpoint returns 503 | 🔴 P1 |
| Slow DB queries | `event:"http.request" latency_ms:>2000` correlated with DB-heavy paths | 🟡 P2 |
| Migration failure | Pre-deploy command fails in Railway deploy log | 🔴 P1 (blocks deployment) |

#### First Checks

1. **Is PostgreSQL running?**  
   Railway Dashboard → PostgreSQL service → check status and restart count

2. **Is it a connectivity issue or a data issue?**  
   ```
   GET /api/v1/health
   ```
   If `"database": "degraded"` → connectivity issue (proceed to mitigation)  
   If health probe returns `"ok"` but specific queries fail → schema or data issue

3. **Storage capacity:**  
   Railway Dashboard → PostgreSQL service → Storage — alert at 80% capacity. If storage is full, PostgreSQL will refuse writes.

4. **Connection pool exhaustion:**  
   Under heavy load, the backend may exhaust its DB connection pool. Check for log lines:
   ```
   error_type:"TimeoutError" logger:"sqlalchemy"
   ```

5. **Was there a recent migration?**  
   If a migration was applied in the last 30 minutes, check whether the migration is reversible and whether it introduced a breaking schema change.

#### Mitigation Steps

**Case A — PostgreSQL service down (Railway-managed):**
1. Restart the PostgreSQL service in the Railway dashboard
2. If restart does not help, check Railway status page — this may be a Railway infrastructure issue
3. While DB is down, the backend will return HTTP 503 for all requests — this is expected behavior. No student data is lost; PostgreSQL uses persistent storage volumes.

**Case B — Storage full:**
1. Railway Dashboard → PostgreSQL → upgrade storage tier immediately
2. Once storage is not full, verify writes resume by checking the health probe

**Case C — Connection pool exhausted:**
1. Restart the backend service (releases idle connections)
2. Review and reduce `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` if concurrency is too high for the PostgreSQL tier
3. Long-term: consider PgBouncer if connection exhaustion is recurring

**Case D — Migration failure blocking deployment:**
1. Check the pre-deploy command output in the Railway deploy log for the specific Alembic error
2. Common causes:
   - `DuplicateTable` or `DuplicateColumn` → migration was already partially applied; manually set the Alembic revision pointer if safe
   - `LockNotAvailable` → a long-running query held a lock; retry the migration after the query clears
   - Schema conflict → requires manual intervention; do not proceed with the deploy until resolved
3. Do **not** run `alembic downgrade` in production without lead engineer authorization and a written rollback plan
4. If the migration cannot proceed safely, revert the deploy to the previous version (see [deployment.md — Database Rollback](architecture/deployment.md#database-rollback))

**Case E — Suspected data integrity issue:**
1. Stop all writes immediately — put the application in maintenance mode (set an environment variable or redeploy with a feature that returns 503)
2. Escalate to lead engineer and incident commander immediately
3. Do not attempt to fix data integrity issues without a reviewed plan
4. This may require FERPA breach assessment — escalate to incident commander

#### Rollback Trigger

If a migration caused data corruption or service failure, do not attempt to forward-fix. Work with lead engineer to write a corrective migration. See [migrations.md](architecture/migrations.md) for zero-downtime migration patterns.

#### Verification

- `GET /api/v1/health` returns `"database": "ok"`
- `GET /api/v1/readiness` returns HTTP 200
- A non-destructive read query (e.g., `GET /api/v1/classes`) succeeds

#### Escalation Owner

Lead engineer for all database issues beyond a simple restart. Incident commander for any data integrity or data loss scenario.

---

### S4 — Authentication Failures

**Typical P-level:** P2 (partial) or P1 (all teachers locked out)

#### Detection Signals

| Signal | Alert rule | Severity |
|---|---|---|
| Auth rate-limit flood | `path:"/api/v1/auth/login" status_code:429` > 20 events over 1 min | 🟡 P2 |
| Auth 401 spike | `path:"/api/v1/auth/*" status_code:401` elevated above baseline | 🔴 P2 |
| All protected endpoints returning 401 | `status_code:401` across all non-auth paths | 🔴 P1 |
| Token refresh failures | `path:"/api/v1/auth/refresh" status_code:401` elevated | 🟡 P2 |

#### First Checks

1. **Is the JWT secret key valid?**  
   If `JWT_SECRET_KEY` was rotated without coordinating a deployment, all existing tokens are immediately invalid. Check your secrets manager for any recent secret rotations.

2. **Is Redis running?**  
   Refresh token validation reads from Redis. If Redis is down, all token refresh attempts fail.  
   Check: `GET /api/v1/health` → `"redis": "ok"`

3. **Is the token TTL causing mass expiry or was the JWT secret rotated?**  
   Access tokens expire after 15 minutes. A large number of teachers all receiving 401 simultaneously can indicate: (a) the `JWT_SECRET_KEY` was rotated — this is expected behavior that invalidates all tokens at once (see Case A below), (b) a clock skew issue, or (c) a misdeployment that reset all active sessions.

4. **Is this a credential stuffing attack?**  
   ```
   path:"/api/v1/auth/login" status_code:429
   ```
   High volume of 429 responses on the login endpoint from distributed IPs indicates a brute-force / credential stuffing attack. The rate limiter is protecting the system — no immediate action is required unless the attack is causing broader service degradation.

5. **Are teachers reporting they cannot log in at all?**  
   Test a fresh login yourself in an incognito browser against the production URL. If login fails, check the login endpoint logs directly:
   ```
   path:"/api/v1/auth/login" level:"ERROR"
   ```

#### Mitigation Steps

**Case A — JWT secret rotated without coordinating deploy:**
1. This is a P1 — all teachers are logged out simultaneously
2. This is expected behavior — JWT rotation invalidates all tokens
3. Notify teachers that they need to log in again (use the [comms template](#62-status-update-slack))
4. If the rotation was unintentional, restore the previous `JWT_SECRET_KEY` value immediately (check your secrets manager history)

**Case B — Redis down, token refresh failing:**
1. Restore Redis first — check [S2 (Worker Queue Backlog)](#s2--worker-queue-backlog) for the beat and queue monitor; apply the same approach to the cache/session Redis service in the Railway dashboard
2. Once Redis is restored, teachers with valid access tokens (not yet expired) resume automatically
3. Teachers whose access tokens expired during the Redis outage must log in again

**Case C — Credential stuffing attack:**
1. The rate limiter (100 req/min per IP on auth endpoints) is the first line of defense — verify it is active
2. If the attack is causing broad degradation, contact Railway support to add IP blocking at the load balancer level
3. Do not escalate this to a P1 unless student data access is involved
4. Log the event in the incident log for SOC 2 purposes

**Case D — Application bug causing all auth to fail:**
1. Check the auth service logs for exceptions:
   ```
   logger:"app.routers.auth" level:"ERROR"
   ```
2. If caused by a recent deploy, trigger a rollback immediately

#### Rollback Trigger

If a code-level auth bug is confirmed after a recent deploy and teachers are locked out, rollback immediately.

#### Verification

- `POST /api/v1/auth/login` with valid credentials returns HTTP 200 with a token
- `GET /api/v1/auth/refresh` returns HTTP 200
- A teacher can access `GET /api/v1/classes` with the returned token

#### Escalation Owner

Incident commander if all teachers are locked out for more than 15 minutes (P1 by definition). Lead engineer for all other auth issues.

---

### S5 — Storage (S3) Failures

**Typical P-level:** P2 (upload failures) or P3 (download degraded)

#### Detection Signals

| Signal | Alert rule | Severity |
|---|---|---|
| File upload endpoint errors | `path:"/api/v1/essays" status_code:>=500` | 🔴 P2 |
| Export failures | `path:"/api/v1/exports/*" status_code:>=500` | 🟡 P2 |
| S3 connectivity error in logs | `error_type:"S3Error" OR error_type:"ClientError"` | 🔴 P2 |

> **Note:** S3 object keys are never logged — they may contain student PII derived from filenames. Logs show only `error_type` and the relevant `essay_id` or `export_id`.

#### First Checks

1. **Is the Railway Storage Bucket running?**  
   Railway Dashboard → your storage bucket service → check status

2. **Are credentials valid?**  
   Railway Storage Buckets inject `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and the bucket endpoint automatically via variable references. Check that `S3_BUCKET_NAME` and `S3_ENDPOINT_URL` are correctly set on the backend service.

3. **Is this isolated to uploads or all S3 operations?**  
   - Upload failures only → check inbound file validation (MIME, size limits) before assuming S3 is the problem
   - Export failures only → the grading pipeline may have completed but the export Celery task failed; check worker logs
   - Both failing → S3 connectivity issue

4. **Check the bucket region / endpoint:**  
   Mismatched endpoint URL is a common cause of `SignatureDoesNotMatch` errors after a bucket was recreated.

#### Mitigation Steps

**Case A — Railway Storage Bucket down:**
1. Check Railway status page for storage service issues
2. If Railway infrastructure issue, await restoration; notify affected teachers that uploads and exports are temporarily unavailable (use the [comms template](#62-status-update-slack))
3. No student data is lost — already-uploaded files remain in the bucket; new uploads will queue when service restores (or teachers will need to re-upload)

**Case B — Invalid S3 credentials:**
1. Railway Dashboard → backend service → Settings → Variables — verify that S3 variable references resolve correctly
2. Re-link the variable references if they appear broken
3. Restart the backend service after correcting variables

**Case C — Bucket does not exist or was recreated:**
1. Verify `S3_BUCKET_NAME` points to the correct Railway storage bucket name
2. If bucket was accidentally deleted, **escalate to incident commander immediately** — this may result in data loss of uploaded essays
3. Check whether Railway has a bucket recovery option (contact Railway support)

**Case D — Upload failures due to file validation (not S3):**
1. Check backend logs:
   ```
   logger:"app.routers.essays" level:"WARNING"
   ```
2. MIME validation failures, oversized files, and unsupported file types return 422, not 500 — these are not incidents; they are expected validation rejections

#### Rollback Trigger

Not applicable for S3 failures (no application code change to roll back). If a code change broke S3 integration, roll back the application deploy.

#### Verification

- Upload a small test text file to a test class/assignment; confirm it returns HTTP 200 and a file URL
- Trigger a test export; confirm it completes and the file is downloadable

#### Escalation Owner

Lead engineer if S3 credentials are invalid or bucket is missing (potential data loss). Incident commander if data loss is confirmed.

---

### S6 — Third-Party Outages (OpenAI / LLM)

**Typical P-level:** P2 (grading pipeline down, other features work) or P3 (elevated errors, partial degradation)

#### Detection Signals

| Signal | Alert rule | Severity |
|---|---|---|
| LLM unavailable | `error_code:"LLM_UNAVAILABLE"` > 3 over 5 min | 🔴 P2 |
| LLM parse errors | `error_code:"LLM_PARSE_ERROR"` > 5 over 15 min | 🟡 P2 |
| Grading tasks failing | `logger:"app.tasks.grading" level:"ERROR"` elevated | 🔴 P2 |

#### First Checks

1. **Check the OpenAI status page:**  
   [status.openai.com](https://status.openai.com) — if OpenAI is reporting an outage or degraded API, this is a third-party incident and the root cause is external.

2. **Is the API key valid and not rate-limited?**  
   OpenAI returns HTTP 429 for rate limits and HTTP 401 for invalid/expired keys. Check the error detail in grading task logs:
   ```
   logger:"app.tasks.grading" level:"ERROR"
   ```
   Look for `error_type` to distinguish `AuthenticationError` (key issue) from `RateLimitError` or `APIError` (outage/quota).

3. **Is this a model change or prompt regression?**  
   `LLM_PARSE_ERROR` (not `LLM_UNAVAILABLE`) suggests the model returned a response that failed schema validation. This may indicate:
   - An OpenAI model version change that altered output format
   - A prompt regression introduced by a recent deploy

4. **What is the current error rate, and how long has it been elevated?**  
   A spike of a few errors resolving in < 5 min is a transient hiccup — do not page. A sustained elevation for > 5 min is an incident.

#### Mitigation Steps

**Case A — OpenAI outage (confirmed on their status page):**
1. No application fix available — this is an external dependency failure
2. New grading jobs will fail and enter Celery's retry cycle (up to 3 attempts with exponential back-off). Jobs are not lost; they will retry automatically when OpenAI recovers.
3. Notify teachers that grading is temporarily unavailable and will resume automatically:  
   Use the [comms template](#62-status-update-slack) — note that existing grades are unaffected; only new grading runs are paused
4. Monitor OpenAI status; when resolved, confirm new grading tasks complete successfully
5. No rollback needed — this is not an application error

**Case B — OpenAI API key expired or revoked:**
1. This is a P2 that requires immediate action
2. Log in to your OpenAI account and generate a new API key
3. Update `OPENAI_API_KEY` in Railway backend and worker service variables
4. Restart both `backend` and `worker` services to pick up the new key
5. Test by triggering a grading run on a test assignment
6. Root cause: establish a key rotation calendar and API key expiry alert to prevent recurrence

**Case C — LLM parse errors (model output format regression):**
1. Check whether a recent deploy changed the grading prompt or model version (`LLM_MODEL` in configuration)
2. If prompt change is the cause: roll back the deploy
3. If model version change is the cause: pin the model version in `LLM_MODEL` configuration to a stable version
4. Parse errors do not expose student data — failed grading attempts are retried; no data is written for failed parses

**Case D — Rate limit exceeded (quota):**
1. Check the OpenAI dashboard for quota usage
2. Short-term: consider throttling concurrent grading tasks by reducing worker `--concurrency`
3. Long-term: request a quota increase from OpenAI

#### Rollback Trigger

Roll back if a prompt regression (from a deploy) caused the parse errors. For external outages, rollback is not applicable.

#### Verification

- `error_code:"LLM_UNAVAILABLE"` clears from logs
- Trigger a test grading run; confirm it completes with scores and feedback in the review queue
- Queue depth returns to near-zero after the backlog of retry tasks clears

#### Escalation Owner

Lead engineer if API key has been lost and cannot be recovered. Incident commander if OpenAI rate limits or an outage affects a school's grading deadline.

---

## 5. FERPA and Privacy Breach Response

This section applies when **student data may have been exposed to unauthorized parties**. Any P1 incident involving potential student data exposure triggers this process in addition to the standard incident checklist.

> **FERPA obligation:** Affected educational institutions must be notified within **72 hours** of confirming a breach of student education records. This clock starts at confirmation, not at discovery.

### 5.1 Immediate Response (T+0 to T+1 hour)

- [ ] **Escalate immediately** to incident commander and legal/compliance contact — do not wait
- [ ] **Stop the data flow** — if ongoing exposure is occurring, take the affected service(s) offline
- [ ] **Preserve evidence** — do not delete logs, rotate secrets, or restart services until the incident commander authorizes it (evidence preservation comes first)
  - Exception: if rotating a secret is necessary to stop an active ongoing breach, rotate it, but document the action immediately
- [ ] **Identify the scope** — which of the following may have been exposed?
  - Student names or identifiers
  - Essay content (text)
  - Grades or criterion scores
  - Teacher feedback
  - Assignment rubrics with school-identifying information
- [ ] **Identify affected institutions** — which teacher accounts were involved? Which school(s)?
- [ ] **Do not notify teachers or schools yet** — that is the incident commander's decision after legal review

### 5.2 Assessment (T+1 to T+4 hours)

- [ ] **Determine actual vs. potential exposure** — was student data actually accessed by an unauthorized party, or only potentially accessible?
  - Review access logs for the affected endpoint(s) during the exposure window
  - Identify any external IP addresses that accessed the data
  - Note: absence of access logs is not evidence that no access occurred
- [ ] **Document findings** in a formal incident assessment document (not in public Slack)
- [ ] **Legal/compliance decision gate:**
  - Was FERPA-protected student data confirmed or suspected to have been accessed by an unauthorized party?
  - If **confirmed**: FERPA notification is required; proceed to 5.3
  - If **under investigation**: preserve evidence; make no notification decision until assessment is complete
  - If **no exposure confirmed**: document the negative finding and close the FERPA track

### 5.3 FERPA Breach Notification (if required, within 72 hours of confirmation)

The incident commander coordinates the notification. The on-call engineer's job is to provide technical facts.

**Notification recipients:**
- The school administrator(s) of each affected school (not individual teachers; not students directly)
- School administrators must then notify affected parents/guardians under FERPA

**Notification content (required by law):**
1. What happened — brief factual description of the incident
2. What student data was involved — categories of data (not the actual student records)
3. What the school should do — any action required by the school or families
4. What we are doing — corrective actions taken and planned
5. Contact information for questions

**Timing:**
- 72-hour window starts at the time the incident is **confirmed** as a breach, not at initial detection
- If the 72-hour window cannot be met, notify the incident commander immediately — legal counsel must be contacted

**Template for the notification email:**  
See [Communications Template — FERPA Breach Notification](#65-ferpa-breach-notification-email).

### 5.4 Post-Breach Steps

- [ ] Remediate the vulnerability — fix the code, rotate exposed secrets, revoke exposed tokens
- [ ] Re-deploy and verify the fix
- [ ] Write a post-mortem within **5 business days**
- [ ] Store the incident report in the internal incident log (a FERPA-reportable breach must be permanently recorded)
- [ ] Review whether changes to the data model, access controls, or logging are needed
- [ ] Schedule a security review of the affected area within 30 days

---

## 6. Communications Templates

All external communications must be reviewed by the incident commander before sending. On-call engineers post only to the internal incident channel.

### 6.1 Incident Opener (Slack)

```
🚨 INCIDENT OPEN — [SEVERITY: P1/P2/P3]
Incident ID: INC-YYYY-MM-DD-NNN
Detected at: [UTC timestamp]
Affected: [services / features affected]
Summary: [one-sentence description of what is wrong]
Current impact: [what teachers cannot do right now]
Incident commander: [name or TBD]
Updates every 15 min in this channel.
```

### 6.2 Status Update (Slack)

```
📊 STATUS UPDATE — [HH:MM UTC]
Current status: [Investigating / Identified / Monitoring fix / Resolved]
What we know: [brief factual update]
What we are doing: [action in progress]
Next update: [HH:MM UTC]
```

### 6.3 Incident Timeline Log

Maintain a running log in the incident channel pinned message or a shared doc. Each entry:

```
[HH:MM UTC] [Who] [What happened / what was done]
```

Example:
```
[14:03 UTC] @alice  Alert fired: API error rate > 20%
[14:07 UTC] @alice  Confirmed: backend returning 503; health probe shows DB degraded
[14:12 UTC] @alice  DB service shows as running in Railway; restarting backend service
[14:15 UTC] @alice  Backend restarted; error rate falling
[14:22 UTC] @alice  Error rate < 1%; health probe green; monitoring
[14:30 UTC] @alice  Resolved. Root cause: transient connection pool exhaustion after deploy
```

### 6.4 Resolution Message (Slack)

```
✅ INCIDENT RESOLVED
Incident ID: INC-YYYY-MM-DD-NNN
Resolved at: [UTC timestamp]
Duration: [HH hours MM minutes]
Root cause (brief): [one sentence]
Impact: [who was affected and for how long]
Fix applied: [what was done to restore service]
Post-mortem: [scheduled / not required for P3]
```

### 6.5 FERPA Breach Notification Email

> **Review with legal counsel before sending.** Do not send this without incident commander sign-off.

```
Subject: Important Notice: Student Data Security Incident — [School Name]

Dear [School Administrator Name],

We are writing to notify you of a security incident that may have affected student 
education records stored in the Rubric Grading Engine.

What happened:
[Factual description of the incident. State dates and times in local time for the school.]

What student information was involved:
[Describe the categories of data — e.g., "student essay submissions and associated 
grades." Do not include actual student records in this email.]

What you should do:
[Any specific action required by the school. If no action is needed: "No action is 
required from you at this time."]

What we have done:
[List corrective actions already taken.]

What we are doing:
[List corrective actions in progress.]

If you have questions, please contact us at [support email / phone].

We take the security of student education records extremely seriously and sincerely 
apologize for any concern this incident may cause.

[Name]  
[Title]  
[Organization]
```

### 6.6 Teacher-Facing Service Status Message

For posting on a status page or in the application when service is degraded:

```
Some features are temporarily unavailable due to a technical issue. Our team is 
working to restore service. Existing grades and student records are unaffected. 
We will post an update by [time].
```

---

## 7. Post-Incident Review (Post-Mortem)

A post-mortem is required for every P1 incident and strongly recommended for P2 incidents.

**Timeline:**
- P1: post-mortem written and reviewed within **5 business days** of resolution
- P2: post-mortem written within **10 business days**

**Post-mortem format:**

```markdown
# Incident Post-Mortem — INC-YYYY-MM-DD-NNN

## Summary
[2-3 sentence summary of what happened, impact, and resolution]

## Timeline (UTC)
| Time | Event |
|---|---|
| [time] | [event] |

## Root Cause
[Clear technical explanation of what caused the incident]

## Impact
- Duration: [HH:MM]
- Affected services: [list]
- Affected schools: [number, not names]
- Student data exposed: yes / no

## What Went Well
- [things that worked: detection speed, runbook accuracy, comms]

## What Went Wrong
- [things that did not work: detection gaps, runbook errors, slow escalation]

## Action Items
| Action | Owner | Due date |
|---|---|---|
| [specific corrective action] | [name] | [date] |

## FERPA Notes
[Whether FERPA notification was required, sent, and to whom. Or "Not applicable."]
```

**Storage:** Post-mortems are stored in the internal incident log. They must not be stored in public repositories.

**Blameless culture:** Post-mortems are blameless. The goal is to understand what happened and improve the system — not to assign blame.

---

## 8. Tabletop Exercise Walkthrough

This section documents a structured tabletop exercise that can be used to verify the runbook can be followed without prior knowledge of the system. Run this exercise at least once before the first production launch and after any significant infrastructure change.

**Participants:** On-call engineer (or candidate), lead engineer (observer and prompter)  
**Duration:** 60–90 minutes  
**Goal:** Confirm the runbook is complete, unambiguous, and executable without tribal knowledge

### 8.1 Setup

Before the exercise:
1. The observer opens this runbook and the linked architecture documents
2. The participant is given a scenario card (see below) — nothing else
3. Both parties agree the exercise is a tabletop (no live systems are changed)
4. The observer tracks which runbook steps the participant finds unclear or skips

### 8.2 Scenario Cards

Print or share one card per exercise. Run each scenario at least once.

---

**Scenario Card A — API Down After Deploy**

> You receive a P1 alert at 14:03 UTC: "API availability down — HTTP 503 on readiness probe."  
> You check the Railway dashboard and see the backend service was deployed at 13:58 UTC.  
> The previous deployment was at 09:00 UTC and was running without issues.

Questions to walk through:
1. What is your first action after acknowledging the alert?
2. How do you determine whether this is a Railway infrastructure issue or an application issue?
3. What is the rollback trigger, and is it met here?
4. Who do you notify and when?
5. How do you verify the rollback resolved the issue?

---

**Scenario Card B — Worker Queue Backlog**

> At 16:30 UTC, you receive a P2 alert: "Celery queue depth > 200."  
> Worker service CPU is flat-zero in the Railway dashboard.  
> No deploy has occurred in the last 6 hours.

Questions to walk through:
1. What log queries do you run first?
2. How do you determine whether workers are crashed vs. deadlocked vs. overloaded?
3. What is the first mitigation action, and what do you monitor to confirm it worked?
4. Under what circumstances would you purge the queue, and who must authorize it?

---

**Scenario Card C — Suspected Student Data Exposure**

> A teacher emails your support address at 09:15 UTC: "I can see another teacher's students in my class list."  
> You reproduce the issue: teacher A's API token returns teacher B's students from `GET /api/v1/classes/{id}/students`.  
> The bug was introduced in a deploy at 08:45 UTC.

Questions to walk through:
1. What is the severity classification?
2. What is your immediate first action — fix the bug, or something else?
3. Who do you notify first, and within what timeframe?
4. When does the 72-hour FERPA clock start?
5. What evidence do you preserve, and how?
6. What information goes into the FERPA notification, and who reviews it before it is sent?

---

**Scenario Card D — OpenAI Outage During School Day**

> At 10:00 UTC (during peak school usage hours), teachers start reporting that grading is not completing.  
> You check logs and see `error_code:"LLM_UNAVAILABLE"` occurring on every grading task.  
> OpenAI's status page shows a confirmed API outage, estimated resolution in 2–3 hours.

Questions to walk through:
1. What is the severity classification?
2. Is there any application fix you can apply, or is this purely external?
3. What happens to grading jobs that were queued during the outage?
4. What do you communicate to teachers, and how?
5. When the outage resolves, what do you check to confirm auto-recovery?

---

### 8.3 Observer Notes

After each scenario, the observer records:

| Step | Found in runbook? | Clear without tribal knowledge? | Notes |
|---|---|---|---|
| Alert acknowledgment | yes / no | yes / no | |
| Severity classification | yes / no | yes / no | |
| First checks | yes / no | yes / no | |
| Mitigation steps | yes / no | yes / no | |
| Escalation decision | yes / no | yes / no | |
| FERPA gate | yes / no | yes / no | |
| Comms template | yes / no | yes / no | |
| Verification | yes / no | yes / no | |

Any "no" in the "Found in runbook?" column is a runbook gap. Update the runbook before the next exercise.

### 8.4 Certification

After the exercise, the observer signs off:

```
Tabletop exercise completed: [date]
Scenarios run: [list]
Participant: [name]
Observer: [name]
Runbook gaps identified: [number; link to issues filed]
Runbook certified for production use: yes / no
```

Re-run the exercise after any of the following:
- A significant change to the infrastructure or deployment model
- A real P1 or P2 incident (to validate the runbook held up under real conditions)
- Rotation of on-call personnel
- Annually at minimum

---

*This runbook is a living document. File a pull request to update it when you discover a gap during an incident or exercise.*
