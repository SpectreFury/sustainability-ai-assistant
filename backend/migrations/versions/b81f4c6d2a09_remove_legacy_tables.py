"""remove legacy extraction table names

Revision ID: b81f4c6d2a09
Revises: a4c7d2e91f60
Create Date: 2026-10-24 00:00:00.000000

The legacy tables and their rows are intentionally removed per request. IF
EXISTS also supports databases that skipped the historical legacy-table DDL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b81f4c6d2a09"
down_revision: Union[str, Sequence[str], None] = "a4c7d2e91f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS extracted_records"))
    op.execute(sa.text("DROP TABLE IF EXISTS source_evidence"))


def downgrade() -> None:
    # The dropped tables were intentionally retired and are not restored.
    pass
