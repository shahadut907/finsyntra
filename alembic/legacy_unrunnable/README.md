# Legacy, unrunnable migrations — retained for reference only

These two files were the repository's original `alembic/versions/` contents.
They are **not part of the active revision chain** and are kept here only so the
history is not lost. Nothing imports them; Alembic does not scan this directory
(`version_locations` in `alembic.ini` points at `alembic/versions` only).

They were audited in Wave 4 and found to be unrunnable and, in one case,
actively harmful.

## `001_add_lifecycle_fields.py` — cannot run on SQLite

* Uses `postgresql.UUID()` column types and
  `server_default=sa.text('gen_random_uuid()')`, which SQLite does not support.
* Assumes a `documents` table already exists (`op.add_column('documents', ...)`)
  with no create step, so it cannot build a database from zero.
* Adds `documents.is_active`, a column the SQLAlchemy model already declares —
  so on any database created by `Base.metadata.create_all()` it fails with a
  duplicate column error.
* Creates `vector_deletion_jobs` and `reconciliation_runs`, tables that no
  current SQLAlchemy model declares and that the running application never
  queries. They belong to the unused enterprise worker code.

## `002_add_chat_session_tenant_id.py` — correct intent, harmful backfill

The `op.add_column` half is right. The backfill is not:

```sql
UPDATE chat_sessions SET tenant_id = json_extract(metadata, '$.tenant_id')
```

Every historical row in the development database carries
`metadata = {"tenant_id": "default", ...}` — the phantom tenant produced by the
pre-Wave-2 indexing bug. Running this migration would have written `"default"`
into `chat_sessions.tenant_id` for all 157 rows, reintroducing exactly the
ownership defect Wave 2 removed, and doing it in a way no authenticated user
could ever match.

## Replacement

The active chain is:

* `0001_baseline_schema` — creates the six tables the SQLAlchemy models declare.
* `0002_chat_session_tenant_id` — adds the column, indexes it, and backfills
  ownership **from the authoritative user store**, never from the metadata blob,
  leaving unresolvable rows NULL rather than guessing.
