"""add document review state and fact overrides

Revision ID: d13e4c6b9a20
Revises: c29a4d7e8f10
Create Date: 2026-10-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d13e4c6b9a20"
down_revision: Union[str, Sequence[str], None] = "c29a4d7e8f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("documents", sa.Column("reviewed_by_user_id", sa.Integer()))
    op.create_foreign_key(
        "fk_documents_reviewed_by_user_id_users",
        "documents",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("facts", sa.Column("reviewed_label", sa.Text()))
    op.add_column("facts", sa.Column("reviewed_value_text", sa.Text()))
    op.add_column(
        "facts",
        sa.Column("reviewed_value_number", sa.Numeric(precision=38, scale=12)),
    )
    op.add_column("facts", sa.Column("reviewed_verified", sa.Boolean()))
    op.add_column("facts", sa.Column("reviewed_verification", sa.Text()))
    op.add_column("facts", sa.Column("edited_by_user_id", sa.Integer()))
    op.add_column("facts", sa.Column("edited_at", sa.DateTime(timezone=True)))
    op.create_foreign_key(
        "fk_facts_edited_by_user_id_users",
        "facts",
        "users",
        ["edited_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_facts_edited_by_user_id_users", "facts", type_="foreignkey")
    op.drop_column("facts", "edited_at")
    op.drop_column("facts", "edited_by_user_id")
    op.drop_column("facts", "reviewed_verification")
    op.drop_column("facts", "reviewed_verified")
    op.drop_column("facts", "reviewed_value_number")
    op.drop_column("facts", "reviewed_value_text")
    op.drop_column("facts", "reviewed_label")
    op.drop_constraint(
        "fk_documents_reviewed_by_user_id_users", "documents", type_="foreignkey"
    )
    op.drop_column("documents", "reviewed_by_user_id")
    op.drop_column("documents", "reviewed_at")
