from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class ExtractedRecord(Base):
    __tablename__ = "extracted_records"
    __table_args__ = (
        Index(
            "ix_extracted_records_metric_fy",
            "metric_name",
            "financial_year_start_year",
        ),
        Index("ix_extracted_records_origin", "value_origin"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    extraction_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "extraction_runs.id",
            ondelete="SET NULL",
            name="fk_extracted_records_run_id",
        ),
    )
    source_evidence_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "source_evidence.id",
            ondelete="SET NULL",
            name="fk_extracted_records_evidence_id",
        ),
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    fact_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="metric", server_default="metric"
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 12, asdecimal=True), nullable=True
    )
    raw_value: Mapped[str | None] = mapped_column(Text)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_date: Mapped[date | None] = mapped_column(Date)
    unit: Mapped[str | None] = mapped_column(String(50))
    currency_code: Mapped[str | None] = mapped_column(String(3))
    value_origin: Mapped[str] = mapped_column(
        String(24), nullable=False, default="reported", server_default="reported"
    )
    aggregation_role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="observation", server_default="observation"
    )
    billing_period_start: Mapped[str | None] = mapped_column(String(64))
    billing_period_end: Mapped[str | None] = mapped_column(String(64))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_grain: Mapped[str | None] = mapped_column(String(16))
    financial_year: Mapped[str | None] = mapped_column(String(12))
    financial_year_start_year: Mapped[int | None] = mapped_column()
    description: Mapped[str | None] = mapped_column(Text)
    dimensions: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    calculation_method: Mapped[str | None] = mapped_column(Text)
    derived_from: Mapped[list | None] = mapped_column(JSONB)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
