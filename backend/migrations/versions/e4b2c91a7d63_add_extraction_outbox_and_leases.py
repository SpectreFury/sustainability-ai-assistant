"""add durable extraction dispatch and worker leases

Revision ID: e4b2c91a7d63
Revises: d13e4c6b9a20
Create Date: 2026-10-24 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4b2c91a7d63"
down_revision: Union[str, Sequence[str], None] = "d13e4c6b9a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "extraction_runs", sa.Column("lease_token", sa.Uuid(), nullable=True)
    )
    op.add_column(
        "extraction_runs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "extraction_runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_extraction_runs_recovery",
        "extraction_runs",
        ["status", "lease_expires_at"],
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

    # Make work already queued before this migration visible to the dispatcher.
    op.execute(
        sa.text(
            """
            INSERT INTO extraction_outbox (id, extraction_run_id, available_at)
            SELECT gen_random_uuid(), runs.id, COALESCE(documents.next_retry_at, now())
            FROM extraction_runs AS runs
            JOIN documents ON documents.id = runs.document_id
            WHERE runs.status = 'queued'
            ON CONFLICT (extraction_run_id) DO NOTHING
            """
        )
    )
    # Previously running attempts have no heartbeat yet. Give active attempts a
    # short lease based on their recorded start time; old abandoned attempts
    # become eligible for recovery immediately.
    op.execute(
        sa.text(
            """
            UPDATE extraction_runs AS runs
            SET lease_expires_at = COALESCE(documents.processing_started_at, runs.started_at)
                + interval '2 minutes'
            FROM documents
            WHERE documents.id = runs.document_id
              AND runs.status = 'running'
              AND runs.lease_expires_at IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_outbox_dispatch", table_name="extraction_outbox")
    op.drop_table("extraction_outbox")
    op.drop_index("ix_extraction_runs_recovery", table_name="extraction_runs")
    op.drop_column("extraction_runs", "heartbeat_at")
    op.drop_column("extraction_runs", "lease_expires_at")
    op.drop_column("extraction_runs", "lease_token")
    op.drop_column("documents", "retry_count")
