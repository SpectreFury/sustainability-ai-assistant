"""remove database-backed job dispatch

Revision ID: c7d31f8e9b42
Revises: f5a8d1c2e930
Create Date: 2026-10-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d31f8e9b42"
down_revision: Union[str, Sequence[str], None] = "f5a8d1c2e930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Jobs waiting only in the database outbox cannot be transferred by a
    # schema migration. Return document uploads to the retryable pending state
    # and close queued runs so the UI can submit them through the direct path.
    op.execute(
        sa.text(
            """
            UPDATE documents
            SET status = 'pending',
                error_message = 'Processing was reset during the queue change. Submit the document again.',
                processing_started_at = NULL,
                next_retry_at = NULL
            WHERE status = 'processing'
              AND id IN (
                  SELECT document_id
                  FROM extraction_runs
                  WHERE status = 'queued'
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE extraction_runs
            SET status = 'failed',
                completed_at = now(),
                error_message = 'This queued job was reset during the queue change. Submit the document again.'
            WHERE status = 'queued'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE evaluation_runs
            SET status = 'failed',
                current_stage = 'Queue changed',
                completed_at = now(),
                error_message = 'This queued evaluation was reset during the queue change. Start a new run.'
            WHERE status = 'queued'
            """
        )
    )

    op.drop_index("ix_evaluation_runs_dispatch", table_name="evaluation_runs")
    op.drop_column("evaluation_runs", "dispatch_lease_expires_at")
    op.drop_column("evaluation_runs", "dispatch_lease_token")
    op.drop_column("evaluation_runs", "next_dispatch_at")
    op.drop_column("evaluation_runs", "dispatch_attempts")

    op.drop_index("ix_extraction_outbox_dispatch", table_name="extraction_outbox")
    op.drop_table("extraction_outbox")


def downgrade() -> None:
    op.add_column(
        "evaluation_runs",
        sa.Column("dispatch_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.alter_column("evaluation_runs", "dispatch_attempts", server_default=None)
    op.add_column(
        "evaluation_runs",
        sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "evaluation_runs",
        sa.Column("dispatch_lease_token", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "evaluation_runs",
        sa.Column("dispatch_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_evaluation_runs_dispatch",
        "evaluation_runs",
        ["status", "next_dispatch_at"],
    )

    op.create_table(
        "extraction_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("next_dispatch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_lease_token", sa.Uuid(), nullable=True),
        sa.Column(
            "dispatch_lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "dispatch_attempts", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"],
            ["extraction_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("extraction_run_id"),
    )
    op.create_index(
        "ix_extraction_outbox_dispatch",
        "extraction_outbox",
        [
            "worker_claimed_at",
            "available_at",
            "next_dispatch_at",
            "dispatch_lease_expires_at",
        ],
    )
