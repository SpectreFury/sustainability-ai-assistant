"""add benchmark-style facts and source segments

Revision ID: a4c7d2e91f60
Revises: 4fe7bb2c7939
Create Date: 2026-10-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a4c7d2e91f60"
down_revision: Union[str, Sequence[str], None] = "4fe7bb2c7939"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_segments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("cells", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("scanned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "extraction_run_id",
            "ordinal",
            name="uq_document_segments_run_ordinal",
        ),
    )
    op.create_index(
        "ix_document_segments_document", "document_segments", ["document_id"]
    )
    op.create_index(
        "ix_document_segments_run", "document_segments", ["extraction_run_id"]
    )

    op.create_table(
        "facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("metric", sa.String(length=32), nullable=True),
        sa.Column("series", sa.Text(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=False),
        sa.Column("value_number", sa.Numeric(precision=38, scale=12), nullable=True),
        sa.Column("unit", sa.String(length=100), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(length=16), server_default="reported", nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("verification", sa.Text(), server_default="", nullable=False),
        sa.Column("derivation", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('reported', 'calculated')", name="ck_facts_origin"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_facts_document", "facts", ["document_id"])
    op.create_index("ix_facts_run", "facts", ["extraction_run_id"])
    op.create_index(
        "ix_facts_metric_period",
        "facts",
        ["metric", "period_start", "period_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_facts_metric_period", table_name="facts")
    op.drop_index("ix_facts_run", table_name="facts")
    op.drop_index("ix_facts_document", table_name="facts")
    op.drop_table("facts")
    op.drop_index("ix_document_segments_run", table_name="document_segments")
    op.drop_index("ix_document_segments_document", table_name="document_segments")
    op.drop_table("document_segments")
