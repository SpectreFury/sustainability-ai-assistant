"""add extracted records

Revision ID: 6fd51c4eec34
Revises: 75044360ed61
Create Date: 2026-10-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6fd51c4eec34"
down_revision: Union[str, Sequence[str], None] = "75044360ed61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "extracted_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("metric_value", sa.Numeric(precision=38, scale=12), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("billing_period_start", sa.String(length=64), nullable=True),
        sa.Column("billing_period_end", sa.String(length=64), nullable=True),
        sa.Column("financial_year", sa.String(length=12), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extracted_records_document_id",
        "extracted_records",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extracted_records_document_id", table_name="extracted_records"
    )
    op.drop_table("extracted_records")
