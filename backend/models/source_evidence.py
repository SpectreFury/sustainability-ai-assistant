from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class SourceEvidence(Base):
    __tablename__ = "source_evidence"
    __table_args__ = (
        Index("ix_source_evidence_document", "document_id"),
        Index("ix_source_evidence_run", "extraction_run_id"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    extraction_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("extraction_runs.id", ondelete="SET NULL"),
    )
    evidence_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    printed_page_label: Mapped[str | None] = mapped_column(String(32))
    sheet_name: Mapped[str | None] = mapped_column(String(128))
    cell_reference: Mapped[str | None] = mapped_column(String(32))
    range_reference: Mapped[str | None] = mapped_column(String(128))
    quote: Mapped[str | None] = mapped_column(Text)
    bounding_box: Mapped[dict | None] = mapped_column(JSONB)
    source_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
