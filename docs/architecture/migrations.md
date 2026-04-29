# Database Migrations

## Overview

Database migrations are managed with **Alembic**. This document covers how migrations are written, reviewed, tested, and run safely in production. Migrations are one of the highest-risk operations in a deployed system — a bad migration can corrupt data or take down production. This process is designed to make that outcome essentially impossible.

---

## Tooling

| Tool | Role |
|---|---|
| Alembic | Migration framework — generates and runs schema changes |
| SQLAlchemy 2.0 | ORM — source of truth for the schema |
| `alembic upgrade head` | Applies all pending migrations |
| `alembic downgrade -1` | Rolls back one migration (used carefully — see below) |
| `alembic current` | Shows current migration revision in the database |
| `alembic history` | Shows full migration history |

---

## Directory Structure

```
backend/
├── alembic.ini                   # Alembic config — points to migrations/ directory
└── app/
    └── db/
        └── migrations/
            ├── env.py            # Alembic env — connects to DB, imports models
            ├── script.py.mako    # Template for new migration files
            └── versions/
                ├── 0001_initial_schema.py
                ├── 0002_add_skill_profile.py
                └── ...
```

---

## Generating a Migration

Never write migration files by hand for schema changes. Always generate them from the SQLAlchemy models.

### Workflow

```bash
# 1. Make your model change in app/models/

# 2. Generate the migration (auto-detect diff between models and current DB schema)
alembic revision --autogenerate -m "add_prompt_version_to_grade"

# 3. Review the generated file in migrations/versions/
#    - Verify upgrade() and downgrade() are correct
#    - Check for any missed columns, indexes, or constraints
#    - Ensure no data is silently dropped

# 4. Run the migration locally to verify
alembic upgrade head

# 5. Verify the schema looks correct
# psql → \d grades
```

### What autogenerate misses
Alembic's autogenerate does not detect all changes. Manually review and add to the migration file if you have:
- Custom PostgreSQL types or enums
- Default values for existing rows (data migrations)
- Index changes on JSONB fields
- RLS policy changes
- `pgvector` extension or index changes
- Renaming columns or tables (autogenerate sees this as drop + add — always convert to an explicit rename)

---

## Migration File Rules

Every migration file must follow these rules before it is merged:

### 1. One concern per migration
Don't bundle schema changes with data backfills in the same migration. If you need both, use two sequential migrations: one for schema, one for data.

### 2. Always write a downgrade
`downgrade()` must be implemented and correct. The only exception is a migration that cannot be reversed (e.g., a data migration that deleted rows) — in that case, raise `NotImplementedError` with an explicit comment explaining why.

### 3. Label it clearly
Migration message should describe what changes: `add_confidence_column_to_criterion_score`, not `update_schema`.

### 4. No application logic
Migrations must not import from application services or models (other than Base). They should use raw SQL or Alembic ops only. Application models may change after the migration is written.

### 5. Test the roundtrip
Every migration must be verified locally:
```bash
alembic upgrade head      # apply
alembic downgrade -1      # revert
alembic upgrade head      # re-apply — must succeed cleanly
```

---

## Zero-Downtime Migration Rules

Production uses rolling deployments — old and new application containers run simultaneously during a deploy. Migrations must be compatible with both the old and new application version.

### Safe operations (no coordination needed)
- Adding a nullable column
- Adding a new table
- Adding an index (use `CREATE INDEX CONCURRENTLY`)
- Widening a VARCHAR column
- Adding a default value to a nullable column

### Operations requiring a multi-step deploy

**Adding a NOT NULL column:**
```
Step 1: Add the column as nullable → deploy app version that writes the column
Step 2: Backfill existing rows → deploy
Step 3: Add NOT NULL constraint → deploy
```

**Renaming a column:**
```
Step 1: Add new column (keep old column) → deploy app that writes both
Step 2: Backfill new column from old → deploy
Step 3: Remove old column → deploy
Never: rename in a single migration while app is live
```

**Dropping a column or table:**
```
Step 1: Deploy app version that no longer reads or writes the column
Step 2: Drop the column in a migration → deploy
Never: drop a column the current app version still references
```

**Changing a column type:**
```
Treat as rename: add new column, backfill, remove old. Never ALTER TYPE on a live column.
```

### Index creation
Always use `CREATE INDEX CONCURRENTLY` for indexes on large tables in production. Alembic's `op.create_index()` supports this:
```python
op.create_index(
    "ix_essays_assignment_id",
    "essays",
    ["assignment_id"],
    postgresql_concurrently=True
)
```
Note: `CONCURRENTLY` cannot run inside a transaction. Wrap the `op.create_index()` call in `op.get_context().autocommit_block()` (Alembic ≥ 1.7, supported by this project's `env.py`):
```python
def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_essays_assignment_id",
            "essays",
            ["assignment_id"],
            postgresql_concurrently=True,
        )

def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_essays_assignment_id",
            table_name="essays",
            postgresql_concurrently=True,
        )
```
Keep concurrent-index operations in a dedicated migration file.

---

## Running Migrations in Production

Migrations are run as part of the deployment pipeline — never manually in a production shell unless recovering from an incident.

### M5 revision-id compatibility note

Milestone M5 introduced two long revision identifiers that were later shortened
to avoid `alembic_version.version_num` truncation on fresh databases:

- `024_essay_versions_writing_snapshots` -> `024_essay_versions_snapshots`
- `025_essay_versions_process_signals` -> `025_essay_versions_signals`

Fresh databases are unaffected (they use the shortened IDs directly).
For an environment that already recorded the long IDs, reconcile the
`alembic_version` table once before running `alembic upgrade head`:

```sql
UPDATE alembic_version
SET version_num = '024_essay_versions_snapshots'
WHERE version_num = '024_essay_versions_writing_snapshots';

UPDATE alembic_version
SET version_num = '025_essay_versions_signals'
WHERE version_num = '025_essay_versions_process_signals';
```

Validate after reconciliation:

```bash
alembic current --verbose
alembic history
```

### Normal deploy flow
```
1. CI builds new Docker image
2. Deploy script runs ECS one-off task:
   docker run rubric-grading-backend alembic upgrade head
3. Migration task exits 0 → proceed with rolling service deploy
4. Migration task exits non-zero → deploy aborted, alert triggered
```

### Pre-deploy checklist
Before triggering a production migration:
- [ ] Migration runs cleanly on staging with production-like data volume
- [ ] `alembic downgrade -1` works on staging
- [ ] Migration does not lock tables for more than a few seconds (check `LOCK` statements in generated SQL)
- [ ] If multi-step deploy is required, confirm which step this migration corresponds to

### Checking current state
```bash
# What revision is production currently at?
alembic current --verbose

# What migrations are pending?
alembic upgrade head --sql   # dry run — prints SQL without executing
```

---

## Data Migrations

Data migrations (backfilling values, transforming existing data) are handled as separate Alembic migration files, sequenced after the schema migration they depend on.

### Rules for data migrations
- Use raw SQL via `op.execute()` — do not use SQLAlchemy ORM models (they may drift)
- Batch large updates: never `UPDATE table SET column = value` on a table with millions of rows in one statement. Use batched updates with a loop:

```python
def upgrade():
    op.execute("""
        UPDATE criterion_scores
        SET confidence = 'high'
        WHERE confidence IS NULL
          AND id IN (
            SELECT id FROM criterion_scores
            WHERE confidence IS NULL
            LIMIT 1000
          )
    """)
    # In practice: loop until no rows remain, or use a DO block
```

- Data migrations are one-way. `downgrade()` should raise `NotImplementedError` if the data cannot be meaningfully reversed.
- Test data migrations against a copy of production data before running on production.

---

## Rollback

### Automated rollback
If a migration fails mid-execution, Alembic's transaction wrapping rolls back the incomplete migration automatically (for transactional migrations). The database is left at the previous revision.

### Manual rollback
```bash
# Roll back one migration
alembic downgrade -1

# Roll back to a specific revision
alembic downgrade 0003_add_skill_profile
```

Manual rollback in production requires:
1. Explicit sign-off (this is a rare, high-risk operation)
2. Confirming the previous app version is being redeployed simultaneously
3. Documenting the rollback in the incident log

### Migrations that cannot be rolled back
If a migration dropped a column or deleted data, downgrade is not possible. Recovery options:
1. Restore from RDS automated snapshot (data loss equal to time since last snapshot)
2. Write a forward migration that recreates what was lost
3. Accept the loss if the data was genuinely disposable

This is why multi-step deploys exist — they make irreversible states harder to reach accidentally.
