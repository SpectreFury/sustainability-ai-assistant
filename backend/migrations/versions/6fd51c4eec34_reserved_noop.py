"""reserved historical revision; legacy fact storage is not part of the schema

Revision ID: 6fd51c4eec34
Revises: 75044360ed61
Create Date: 2026-10-23

This revision ID was already deployed. Keep the no-op node so existing Alembic
revision histories remain valid, but do not create the removed legacy tables.
"""
from typing import Sequence, Union


revision: str = "6fd51c4eec34"
down_revision: Union[str, Sequence[str], None] = "75044360ed61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
