"""Add lifecycle and tenant fields to documents (additive only)

Revision ID: 001_lifecycle
Revises: 
Create Date: 2024-01-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

revision = '001_lifecycle'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    """Add lifecycle fields - all nullable for backwards compatibility"""
    
    # Add lifecycle fields to documents table (all nullable for existing data)
    op.add_column('documents', 
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'))
    op.add_column('documents', 
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('documents', 
        sa.Column('deleted_by', postgresql.UUID(), nullable=True))
    op.add_column('documents', 
        sa.Column('version', sa.Integer(), nullable=True, server_default='1'))
    op.add_column('documents', 
        sa.Column('checksum', sa.String(64), nullable=True))
    op.add_column('documents', 
        sa.Column('tenant_id', postgresql.UUID(), nullable=True))
    op.add_column('documents', 
        sa.Column('previous_version_id', postgresql.UUID(), nullable=True))
    
    # Add indexes for performance (won't affect existing queries)
    op.create_index('idx_documents_active', 'documents', ['is_active', 'deleted_at'])
    op.create_index('idx_documents_tenant', 'documents', ['tenant_id', 'is_active'])
    op.create_index('idx_documents_version', 'documents', ['filename', 'version'])
    
    # Create vector_deletion_jobs table (new table, no impact on existing)
    op.create_table('vector_deletion_jobs',
        sa.Column('id', postgresql.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('doc_id', postgresql.UUID(), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(), nullable=True),
        sa.Column('source_filename', sa.String(255), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('processed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_deletion_jobs_status', 'vector_deletion_jobs', ['status', 'attempts'])
    op.create_index('idx_deletion_jobs_created', 'vector_deletion_jobs', ['created_at'])
    
    # Create reconciliation_runs table for tracking
    op.create_table('reconciliation_runs',
        sa.Column('id', postgresql.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='running'),
        sa.Column('db_docs', sa.Integer(), nullable=True),
        sa.Column('vector_sources', sa.Integer(), nullable=True),
        sa.Column('orphaned_count', sa.Integer(), nullable=True),
        sa.Column('missing_count', sa.Integer(), nullable=True),
        sa.Column('final_drift', sa.Integer(), nullable=True),
        sa.Column('dry_run', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_index('idx_reconciliation_runs_started', 'reconciliation_runs', ['started_at'])

def downgrade():
    """Remove added tables and columns"""
    # Drop new tables
    op.drop_table('reconciliation_runs')
    op.drop_table('vector_deletion_jobs')
    
    # Drop indexes
    op.drop_index('idx_documents_active')
    op.drop_index('idx_documents_tenant')
    op.drop_index('idx_documents_version')
    
    # Drop columns (safe as they're all nullable)
    op.drop_column('documents', 'is_active')
    op.drop_column('documents', 'deleted_at')
    op.drop_column('documents', 'deleted_by')
    op.drop_column('documents', 'version')
    op.drop_column('documents', 'checksum')
    op.drop_column('documents', 'tenant_id')
    op.drop_column('documents', 'previous_version_id')
