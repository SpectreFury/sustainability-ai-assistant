"""support queued extraction attempts

Revision ID: 4fe7bb2c7939
Revises: 1d2a4fde3eea
Create Date: 2026-10-23 23:17:58.157696

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4fe7bb2c7939'
down_revision: Union[str, Sequence[str], None] = '1d2a4fde3eea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint('uq_extraction_runs_document_attempt', 'extraction_runs', ['document_id', 'attempt_number'])
    op.drop_constraint('ck_extraction_runs_status', 'extraction_runs', type_='check')
    op.create_check_constraint(
        'ck_extraction_runs_status',
        'extraction_runs',
        "status IN ('queued', 'running', 'succeeded', 'failed')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_extraction_runs_status', 'extraction_runs', type_='check')
    op.create_check_constraint(
        'ck_extraction_runs_status',
        'extraction_runs',
        "status IN ('running', 'succeeded', 'failed')",
    )
    op.drop_constraint('uq_extraction_runs_document_attempt', 'extraction_runs', type_='unique')
