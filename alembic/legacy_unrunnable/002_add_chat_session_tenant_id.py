"""Add tenant_id column to chat_sessions

Revision ID: 002_tenant_id
Revises: 001_lifecycle
Create Date: 2025-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = '002_tenant_id'
down_revision = '001_lifecycle'
branch_labels = None
depends_on = None


def upgrade():
    """Add tenant_id column to chat_sessions for multi-tenant isolation.

    - Column is nullable for backward compatibility with existing rows.
    - Backfill from the metadata JSON blob where possible (SQLite-safe).
    - Composite index (tenant_id, user_id) for efficient scoped queries.
    """
    # 1. Add the column
    op.add_column(
        'chat_sessions',
        sa.Column('tenant_id', sa.String(), nullable=True)
    )

    # 2. Backfill: Extract tenant_id from the metadata JSON column.
    #    SQLite uses json_extract; PostgreSQL uses metadata->>'tenant_id'.
    #    We use raw SQL with try/except for dialect safety.
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == 'sqlite':
        conn.execute(sa.text(
            "UPDATE chat_sessions "
            "SET tenant_id = json_extract(metadata, '$.tenant_id') "
            "WHERE tenant_id IS NULL "
            "AND metadata IS NOT NULL "
            "AND json_extract(metadata, '$.tenant_id') IS NOT NULL"
        ))
    elif dialect == 'postgresql':
        conn.execute(sa.text(
            "UPDATE chat_sessions "
            "SET tenant_id = metadata->>'tenant_id' "
            "WHERE tenant_id IS NULL "
            "AND metadata IS NOT NULL "
            "AND metadata->>'tenant_id' IS NOT NULL"
        ))
    else:
        # For other dialects, skip backfill — the column stays NULL
        pass

    # 3. Add composite index for efficient tenant-scoped user queries
    op.create_index(
        'idx_chat_sessions_tenant_user',
        'chat_sessions',
        ['tenant_id', 'user_id']
    )


def downgrade():
    """Remove tenant_id column and index from chat_sessions."""
    op.drop_index('idx_chat_sessions_tenant_user', table_name='chat_sessions')
    op.drop_column('chat_sessions', 'tenant_id')
