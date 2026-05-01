---
applyTo: "backend/app/db/migrations/**"
---

# Database Migration Review Instructions

When reviewing a PR that touches `backend/app/db/migrations/**`, this is a **high-risk review**. Migrations are the hardest change to roll back in production. Check everything below carefully.

Reference: `docs/architecture/migrations.md`

## Reversibility

- [ ] Both `upgrade()` and `downgrade()` are implemented — no empty `downgrade()` functions
- [ ] `downgrade()` is the exact inverse of `upgrade()` — walk through it step by step mentally
- [ ] If `downgrade()` is intentionally not reversible (e.g., data deletion), it raises `NotImplementedError` with an explanation comment
- [ ] Migration was tested locally as a roundtrip: `upgrade` → `downgrade` → `upgrade` all succeed

## Zero-Downtime Safety

These operations cause table locks and will take down production on large tables:

- [ ] **`CREATE INDEX`** → must use `CREATE INDEX CONCURRENTLY`: `op.create_index(..., postgresql_concurrently=True)`
- [ ] Every `CREATE INDEX CONCURRENTLY` and `DROP INDEX CONCURRENTLY` operation is wrapped in `with op.get_context().autocommit_block():` in both `upgrade()` and `downgrade()`
- [ ] Do not add migration-local no-op flags like `transaction_per_migration = False` unless `env.py` actually reads them; document transaction behavior accurately in comments/docstrings
- [ ] **`ADD COLUMN NOT NULL` without default** → add as nullable first; backfill in a separate migration; add constraint last
- [ ] **`ALTER COLUMN` type change** → multi-step migration required; never in one shot on a populated table
- [ ] **`DROP COLUMN`** → application code no longer references the column first; dropped in a separate migration
- [ ] **`DROP TABLE`** → never dropped until all references are removed and data confirmed safe

Reference: `docs/architecture/migrations.md#zero-downtime-migration-rules`

## Data Safety

- [ ] No `DROP TABLE` in this migration without prior explicit sign-off
- [ ] No `DROP COLUMN` — make nullable first, remove in a future migration
- [ ] No `UPDATE` or `DELETE` affecting more than 1000 rows — use a batched data migration
- [ ] No `TRUNCATE`
- [ ] New `NOT NULL` columns have a `server_default` to handle existing rows

## Schema Correctness

- [ ] New columns, tables, and indexes are consistent with `docs/architecture/data-model.md`
- [ ] Alembic `revision` and `down_revision` identifiers fit the `alembic_version.version_num` storage limit used by this project
- [ ] Foreign keys reference existing tables and columns
- [ ] Index names follow convention: `ix_{table}_{column(s)}` (e.g., `ix_essays_assignment_id`)
- [ ] **Foreign keys must have an explicit `name=` argument** — e.g., `sa.ForeignKey("users.id", name="fk_comment_bank_entries_users")`. Unnamed foreign keys use auto-generated names that differ across databases and Alembic environments, making diffs and targeted drops unreliable. Convention: `fk_{child_table}_{parent_table}`.
- [ ] Table names are `snake_case`, plural
- [ ] Column names are `snake_case`
- [ ] `UNIQUE` constraints are intentional and reflect a domain requirement, not just DB convenience
- [ ] `pgvector` columns (`embedding`) use the correct `Vector(N)` type and have an appropriate index (ivfflat or hnsw)
- [ ] **ORM model indexes match the migration** — if a SQLAlchemy model column has `index=True`, a corresponding single-column index must exist in the migration. If the migration only creates a composite index, remove `index=True` from the ORM column to prevent Alembic autogenerate drift on subsequent runs.
- [ ] **Postgres trigger functions have an explicit `RETURN` statement** — a `RETURNS trigger` function that never executes `RETURN` will raise a Postgres error at `CREATE FUNCTION` time. Row-level triggers must `RETURN NEW` (or `RETURN OLD` for DELETE triggers).
- [ ] **Seed data uses `INSERT ... ON CONFLICT DO NOTHING`** — `op.bulk_insert` without conflict handling causes PK violations and migration failure if the migration is re-run after a partial upgrade.
- [ ] **Dropping extensions in `downgrade()` is flagged** — dropping `CREATE EXTENSION` (e.g., `vector`, `pgcrypto`) in downgrade can break other schemas or pre-existing installations that depended on the extension. Document the risk in a comment; prefer leaving extensions installed.

## Audit Log Special Rules

The `audit_logs` table is INSERT-only. These are hard blocks:

- [ ] No `ALTER TABLE audit_logs` that removes or changes existing columns
- [ ] No migration that grants UPDATE or DELETE privileges on `audit_logs`
- [ ] New columns on `audit_logs` must be nullable (existing rows cannot have the new value retroactively)

## Concurrent Index Note

Migrations that use `postgresql_concurrently=True` cannot run inside a transaction.

- [ ] Every concurrent index statement is inside `op.get_context().autocommit_block()`
- [ ] Module docstring/comments explicitly state why concurrent index operations are outside a transaction
- [ ] Downgrade path uses the same concurrent + autocommit pattern when dropping those indexes
