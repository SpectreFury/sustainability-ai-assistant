"""add extraction runs and document processing metadata

Revision ID: 1d2a4fde3eea
Revises: 6fd51c4eec34
Create Date: 2026-10-23 22:57:48.379412

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "1d2a4fde3eea"
down_revision: Union[str, Sequence[str], None] = "6fd51c4eec34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="running", nullable=False),
        sa.Column("extraction_version", sa.String(length=32), server_default="v1", nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_extraction_runs_status",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_runs_document_started",
        "extraction_runs",
        ["document_id", "started_at"],
    )
    op.add_column(
        "documents",
        sa.Column("document_kind", sa.String(length=32), server_default="unknown", nullable=False),
    )
    op.add_column("documents", sa.Column("entity_name", sa.String(length=255), nullable=True))
    op.add_column(
        "documents",
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "documents", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "documents", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("documents", "next_retry_at")
    op.drop_column("documents", "last_attempt_at")
    op.drop_column("documents", "processing_started_at")
    op.drop_column("documents", "attempt_count")
    op.drop_column("documents", "entity_name")
    op.drop_column("documents", "document_kind")
    op.drop_index("ix_extraction_runs_document_started", table_name="extraction_runs")
    op.drop_table("extraction_runs")
