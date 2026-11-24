"""Add chat_sessions.tenant_id and backfill ownership deterministically.

Revision ID: 0002_chat_session_tenant_id
Revises: 0001_baseline_schema
Create Date: 2026-08-27

The column is added NULLABLE on purpose. Ownership of historical rows is only
knowable where the row's user_id resolves against the authoritative user store;
anything else stays NULL and is reported rather than guessed. Tightening to
NOT NULL is a separate decision that can only be made once every remaining row
has been triaged by a human.

Explicitly NOT done here — the superseded 002_add_chat_session_tenant_id.py
backfilled from ``json_extract(metadata, '$.tenant_id')``. Every historical row
in this project carries ``"tenant_id": "default"`` in that blob, a leftover of
the pre-Wave-2 indexing defect. Copying it would have stamped 157 sessions with
a phantom tenant that no authenticated user can ever match.

SQLite has no native ADD COLUMN for every case, so batch_alter_table is used;
env.py sets render_as_batch for SQLite.
"""
import logging

from alembic import op
import sqlalchemy as sa

revision = "0002_chat_session_tenant_id"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

INDEX_NAME = "idx_chat_sessions_tenant_user"


def _authoritative_tenant_map():
    """email -> tenant_id, from the application's user store.

    Returns an empty map if the store cannot be read, which makes the backfill a
    no-op rather than a guess. Leaving rows NULL is always recoverable; writing
    the wrong owner is not.
    """
    try:
        from src.config.roles import DEMO_USERS
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "TENANT_BACKFILL_SKIPPED could not import the authoritative user "
            "store (%s); leaving every tenant_id NULL rather than guessing.", exc)
        return {}

    mapping = {}
    for email, data in (DEMO_USERS or {}).items():
        tenant = (data or {}).get("tenant_id")
        if email and tenant:
            mapping[email.strip().lower()] = tenant
    return mapping


def _has_column(conn, table, column):
    return column in {c["name"] for c in sa.inspect(conn).get_columns(table)}


def _has_index(conn, table, name):
    return name in {i["name"] for i in sa.inspect(conn).get_indexes(table)}


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add the column (idempotent — a partially applied run must not explode).
    if not _has_column(conn, "chat_sessions", "tenant_id"):
        with op.batch_alter_table("chat_sessions") as batch:
            batch.add_column(sa.Column("tenant_id", sa.String(), nullable=True))
        logger.info("TENANT_COLUMN_ADDED chat_sessions.tenant_id")
    else:
        logger.info("TENANT_COLUMN_PRESENT chat_sessions.tenant_id — skipping add")

    # 2. Deterministic backfill from the authoritative user store only.
    tenant_map = _authoritative_tenant_map()
    resolved = 0
    if tenant_map:
        for email, tenant in sorted(tenant_map.items()):
            res = conn.execute(
                sa.text(
                    "UPDATE chat_sessions SET tenant_id = :tenant "
                    "WHERE tenant_id IS NULL AND lower(trim(user_id)) = :email"
                ),
                {"tenant": tenant, "email": email},
            )
            if res.rowcount:
                resolved += res.rowcount
                logger.info("TENANT_BACKFILL user=%s tenant=%s rows=%d",
                            email, tenant, res.rowcount)

    unresolved = conn.execute(
        sa.text("SELECT COUNT(*) FROM chat_sessions WHERE tenant_id IS NULL")
    ).scalar() or 0

    logger.info("TENANT_BACKFILL_SUMMARY resolved=%d unresolved=%d", resolved, unresolved)
    if unresolved:
        rows = conn.execute(sa.text(
            "SELECT user_id, COUNT(*) FROM chat_sessions WHERE tenant_id IS NULL "
            "GROUP BY user_id ORDER BY COUNT(*) DESC"
        )).fetchall()
        logger.warning(
            "TENANT_BACKFILL_UNRESOLVED %d session(s) have no resolvable owner and "
            "were left NULL (never guessed). Per user_id: %s",
            unresolved, ", ".join("%s=%d" % (r[0], r[1]) for r in rows))

    # 3. Index for tenant-scoped listing.
    if not _has_index(conn, "chat_sessions", INDEX_NAME):
        op.create_index(INDEX_NAME, "chat_sessions", ["tenant_id", "user_id"])


def downgrade() -> None:
    conn = op.get_bind()
    if _has_index(conn, "chat_sessions", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="chat_sessions")
    if _has_column(conn, "chat_sessions", "tenant_id"):
        with op.batch_alter_table("chat_sessions") as batch:
            batch.drop_column("tenant_id")
