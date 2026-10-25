"""add extraction chunk progress

Revision ID: 7c4a2e91d6f3
Revises: f5a8d1c2e930
Create Date: 2026-10-25 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c4a2e91d6f3"
down_revision: Union[str, Sequence[str], None] = "c7d31f8e9b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "extraction_runs",
        sa.Column("chunks_completed", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("chunks_total", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("extraction_runs", "chunks_total")
    op.drop_column("extraction_runs", "chunks_completed")
