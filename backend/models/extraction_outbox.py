from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class ExtractionOutbox(Base):
    """Durable handoff from a database extraction run to the Redis broker."""

    __tablename__ = "extraction_outbox"
    __table_args__ = (
        Index(
            "ix_extraction_outbox_dispatch",
            "worker_claimed_at",
            "available_at",
            "next_dispatch_at",
            "dispatch_lease_expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    next_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    dispatch_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    dispatch_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
