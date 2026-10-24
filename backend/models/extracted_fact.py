from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class ExtractedFact(Base):
    """A benchmark-style reported or calculated fact tied to source evidence."""

    __tablename__ = "facts"
    __table_args__ = (
        CheckConstraint("origin IN ('reported', 'calculated')", name="ck_facts_origin"),
        Index("ix_facts_document", "document_id"),
        Index("ix_facts_run", "extraction_run_id"),
        Index("ix_facts_metric_period", "metric", "period_start", "period_end"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    extraction_run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    metric: Mapped[str | None] = mapped_column(String(32))
    series: Mapped[str | None] = mapped_column(Text)
    value_text: Mapped[str] = mapped_column(Text, nullable=False)
    value_number: Mapped[Decimal | None] = mapped_column(Numeric(38, 12, asdecimal=True))
    unit: Mapped[str | None] = mapped_column(String(100))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="reported", server_default="reported")
    locator: Mapped[dict] = mapped_column(JSONB, nullable=False)
    quote: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    verification: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    derivation: Mapped[str | None] = mapped_column(Text)
    reviewed_label: Mapped[str | None] = mapped_column(Text)
    reviewed_value_text: Mapped[str | None] = mapped_column(Text)
    reviewed_value_number: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 12, asdecimal=True)
    )
    reviewed_verified: Mapped[bool | None] = mapped_column()
    reviewed_verification: Mapped[str | None] = mapped_column(Text)
    edited_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
            name="fk_facts_edited_by_user_id_users",
        )
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
