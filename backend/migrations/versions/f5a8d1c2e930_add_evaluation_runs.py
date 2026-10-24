"""add persisted source-backed evaluation runs

Revision ID: f5a8d1c2e930
Revises: e4b2c91a7d63
Create Date: 2026-10-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f5a8d1c2e930"
down_revision: Union[str, Sequence[str], None] = "e4b2c91a7d63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=True),
        sa.Column("case_set_version", sa.String(length=64), nullable=False),
        sa.Column("case_set_hash", sa.String(length=64), nullable=False),
        sa.Column("answer_prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("extraction_prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("document_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "extraction_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "case_results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("dispatch_attempts", sa.Integer(), nullable=False),
        sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_lease_token", sa.Uuid(), nullable=True),
        sa.Column("dispatch_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_lease_token", sa.Uuid(), nullable=True),
        sa.Column("worker_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_evaluation_runs_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_runs_user_created", "evaluation_runs", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_evaluation_runs_dispatch", "evaluation_runs", ["status", "next_dispatch_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_dispatch", table_name="evaluation_runs")
    op.drop_index("ix_evaluation_runs_user_created", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
