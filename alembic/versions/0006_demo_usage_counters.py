"""Add demo_usage_counters for daily public-demo usage limits.

Revision ID: 0006_demo_usage_counters
Revises: 0005_visitor_session_isolation

Rows are keyed by (scope, subject, UTC day). ``subject`` holds an HMAC of the
visitor id or client IP, never a raw identifier.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_demo_usage_counters"
down_revision = "0005_visitor_session_isolation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if "demo_usage_counters" in sa.inspect(conn).get_table_names():
        return
    op.create_table(
        "demo_usage_counters",
        sa.Column("scope", sa.String(16), primary_key=True),
        sa.Column("subject", sa.String(64), primary_key=True),
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_demo_usage_day", "demo_usage_counters", ["day"])
    op.create_table(
        "demo_runtime_settings",
        sa.Column("key", sa.String(48), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    conn = op.get_bind()
    if "demo_usage_counters" in sa.inspect(conn).get_table_names():
        op.drop_index("idx_demo_usage_day", table_name="demo_usage_counters")
        op.drop_table("demo_usage_counters")
    if "demo_runtime_settings" in sa.inspect(conn).get_table_names():
        op.drop_table("demo_runtime_settings")
