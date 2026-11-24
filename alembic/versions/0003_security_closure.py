"""Authoritative user tenancy, document ownership, and refresh revocation.

Revision ID: 0003_security_closure
Revises: 0002_chat_session_tenant_id
Create Date: 2026-08-28

Existing document and user rows remain NULL-owned and therefore inaccessible
until deterministic startup seeding or explicit administrator triage assigns
them. Conversation rows are intentionally untouched.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_security_closure"
down_revision = "0002_chat_session_tenant_id"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "users" in tables:
        if "tenant_id" not in _columns("users"):
            with op.batch_alter_table("users") as batch:
                batch.add_column(sa.Column("tenant_id", sa.String(), nullable=True))
        if "ix_users_tenant_id" not in _indexes("users"):
            op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    if "documents" in tables:
        document_columns = _columns("documents")
        with op.batch_alter_table("documents") as batch:
            if "tenant_id" not in document_columns:
                batch.add_column(sa.Column("tenant_id", sa.String(), nullable=True))
            if "storage_path" not in document_columns:
                batch.add_column(sa.Column("storage_path", sa.String(), nullable=True))
        if "ix_documents_tenant_id" not in _indexes("documents"):
            op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])

    if "refresh_tokens" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "refresh_tokens",
            sa.Column("jti", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replaced_by", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("jti"),
        )
        op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
        op.create_index("ix_refresh_tokens_revoked_at", "refresh_tokens", ["revoked_at"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "refresh_tokens" in tables:
        op.drop_table("refresh_tokens")
    if "documents" in tables:
        if "ix_documents_tenant_id" in _indexes("documents"):
            op.drop_index("ix_documents_tenant_id", table_name="documents")
        with op.batch_alter_table("documents") as batch:
            for name in ("storage_path", "tenant_id"):
                if name in _columns("documents"):
                    batch.drop_column(name)
    if "users" in tables:
        if "ix_users_tenant_id" in _indexes("users"):
            op.drop_index("ix_users_tenant_id", table_name="users")
        if "tenant_id" in _columns("users"):
            with op.batch_alter_table("users") as batch:
                batch.drop_column("tenant_id")
