"""Add explicit public-demo ownership and protection flags.

Revision ID: 0004_wave7_public_demo
Revises: 0003_security_closure
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_wave7_public_demo"
down_revision = "0003_security_closure"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has_table("users") and "is_public_demo" not in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("is_public_demo", sa.Boolean(), nullable=False, server_default=sa.false()))
    if _has_table("documents") and "is_protected_demo" not in _columns("documents"):
        with op.batch_alter_table("documents") as batch:
            batch.add_column(sa.Column("is_protected_demo", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    if _has_table("documents") and "is_protected_demo" in _columns("documents"):
        with op.batch_alter_table("documents") as batch:
            batch.drop_column("is_protected_demo")
    if _has_table("users") and "is_public_demo" in _columns("users"):
        with op.batch_alter_table("users") as batch:
            batch.drop_column("is_public_demo")
