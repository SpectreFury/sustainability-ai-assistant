from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class ExtractedRecord(Base):
    __tablename__ = "extracted_records"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(
        Numeric(38, 12, asdecimal=True), nullable=False
    )
    unit: Mapped[str | None] = mapped_column(String(50))
    billing_period_start: Mapped[str | None] = mapped_column(String(64))
    billing_period_end: Mapped[str | None] = mapped_column(String(64))
    financial_year: Mapped[str | None] = mapped_column(String(12))
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
