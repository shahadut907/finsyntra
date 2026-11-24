"""Add chat_sessions.visitor_session_id for public-demo conversation isolation.

Revision ID: 0005_visitor_session_isolation
Revises: 0004_wave7_public_demo

The column is added NULLABLE and is never backfilled. NULL means either
"non-demo session" (the overwhelming majority of rows, and the only kind
that will ever exist for a real employee/admin tenant) or "legacy public-demo
session created before Phase 3" — both must keep behaving exactly as before:
non-demo ownership is unaffected, and a legacy NULL-vsid demo row must NOT
become visible to a new visitor's vsid-scoped queries. The application layer
(``_assert_session_owner``) enforces that a vsid, once required for a
public-demo caller, must match exactly — NULL never matches a real vsid.

The new composite index matches the query load this feature actually adds:
``list_conversations`` filters chat_sessions by (tenant_id, user_id) for every
request, and now additionally by visitor_session_id for every public-demo
request — the same three columns together, in the same order the existing
idx_chat_sessions_tenant_user index already uses as its prefix.

SQLite has no native ADD COLUMN for every case, so batch_alter_table is used;
env.py sets render_as_batch for SQLite.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_visitor_session_isolation"
down_revision = "0004_wave7_public_demo"
branch_labels = None
depends_on = None

INDEX_NAME = "idx_chat_sessions_tenant_user_visitor"


def _has_column(conn, table, column):
    return column in {c["name"] for c in sa.inspect(conn).get_columns(table)}


def _has_index(conn, table, name):
    return name in {i["name"] for i in sa.inspect(conn).get_indexes(table)}


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, "chat_sessions", "visitor_session_id"):
        with op.batch_alter_table("chat_sessions") as batch:
            batch.add_column(sa.Column("visitor_session_id", sa.String(), nullable=True))

    if not _has_index(conn, "chat_sessions", INDEX_NAME):
        op.create_index(
            INDEX_NAME, "chat_sessions", ["tenant_id", "user_id", "visitor_session_id"]
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _has_index(conn, "chat_sessions", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="chat_sessions")
    if _has_column(conn, "chat_sessions", "visitor_session_id"):
        with op.batch_alter_table("chat_sessions") as batch:
            batch.drop_column("visitor_session_id")
