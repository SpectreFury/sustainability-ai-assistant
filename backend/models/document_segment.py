from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class DocumentSegment(Base):
    """The source text and locator used to extract and verify facts."""

    __tablename__ = "document_segments"
    __table_args__ = (
        UniqueConstraint(
            "extraction_run_id",
            "ordinal",
            name="uq_document_segments_run_ordinal",
        ),
        Index("ix_document_segments_document", "document_id"),
        Index("ix_document_segments_run", "extraction_run_id"),
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
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[dict] = mapped_column(JSONB, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    cells: Mapped[dict | None] = mapped_column(JSONB)
    scanned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
