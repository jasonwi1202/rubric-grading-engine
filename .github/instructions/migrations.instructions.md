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
- [ ] Foreign keys reference existing tables and columns
- [ ] Index names follow convention: `ix_{table}_{column(s)}` (e.g., `ix_essays_assignment_id`)
- [ ] Foreign key names follow convention: `fk_{table}_{referenced_table}`
- [ ] Table names are `snake_case`, plural
- [ ] Column names are `snake_case`
- [ ] `UNIQUE` constraints are intentional and reflect a domain requirement, not just DB convenience
- [ ] `pgvector` columns (`embedding`) use the correct `Vector(N)` type and have an appropriate index (ivfflat or hnsw)

## Audit Log Special Rules

The `audit_logs` table is INSERT-only. These are hard blocks:

- [ ] No `ALTER TABLE audit_logs` that removes or changes existing columns
- [ ] No migration that grants UPDATE or DELETE privileges on `audit_logs`
- [ ] New columns on `audit_logs` must be nullable (existing rows cannot have the new value retroactively)

## Concurrent Index Note

Migrations that use `postgresql_concurrently=True` cannot run inside a transaction. Ensure `env.py` handles this:

```python
# In the migration file, add at the top:
# This migration creates indexes concurrently and must run outside a transaction.
```

And set the migration's `transaction_per_migration` behavior appropriately in `env.py`.
