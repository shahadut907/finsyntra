"""Baseline schema — the six tables declared by the SQLAlchemy models.

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-08-27

This is a frozen transcription of src/backend/database/database.py as of Wave 4.
It exists so a completely empty database can reach head, which the previous
migration chain could not do (see alembic/legacy_unrunnable/README.md).

Idempotent by design: each table is created only if absent. That matters because
the application has historically built its schema with
``Base.metadata.create_all()`` at startup, so a database may already have these
tables without any Alembic version stamp. Running this revision against such a
database is a no-op, which makes ``alembic stamp`` and ``alembic upgrade`` both
safe entry points.

Deliberately NOT included: vector_deletion_jobs and reconciliation_runs. No
current model declares them and the application never queries them; they came
from the unused enterprise worker code.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def _existing_tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("username", sa.String(), nullable=False),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("hashed_password", sa.String(), nullable=False),
            sa.Column("full_name", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=False, server_default="employee"),
            sa.Column("department", sa.String(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_users_id", "users", ["id"])
        op.create_index("ix_users_username", "users", ["username"], unique=True)
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "chat_sessions" not in existing:
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_chat_sessions_id", "chat_sessions", ["id"])
        op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    if "chat_messages" not in existing:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("message_type", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("sources", sa.JSON(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_chat_messages_id", "chat_messages", ["id"])
        op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
        op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])

    if "documents" not in existing:
        op.create_table(
            "documents",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("content_type", sa.String(), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("department", sa.String(), nullable=False),
            sa.Column("clearance_level", sa.Integer(), nullable=True),
            sa.Column("uploaded_by", sa.String(), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("chunk_count", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_documents_id", "documents", ["id"])

    if "session_facts" not in existing:
        op.create_table(
            "session_facts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("fact_key", sa.String(), nullable=False),
            sa.Column("fact_value", sa.String(), nullable=False),
            sa.Column("source_document", sa.String(), nullable=True),
            sa.Column("confidence", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_session_facts_id", "session_facts", ["id"])
        op.create_index("ix_session_facts_session_id", "session_facts", ["session_id"])

    if "system_metrics" not in existing:
        op.create_table(
            "system_metrics",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("metric_name", sa.String(), nullable=False),
            sa.Column("metric_value", sa.String(), nullable=False),
            sa.Column("metric_type", sa.String(), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_system_metrics_id", "system_metrics", ["id"])
        op.create_index("ix_system_metrics_metric_name", "system_metrics", ["metric_name"])


def downgrade() -> None:
    """Drop the baseline tables.

    Destructive: this removes conversation history. Alembic will happily run it,
    so treat `alembic downgrade base` as a development-only operation on a
    throwaway database.
    """
    for table in ("system_metrics", "session_facts", "documents",
                  "chat_messages", "chat_sessions", "users"):
        op.drop_table(table)
