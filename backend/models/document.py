from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("user_id", "file_hash", name="uq_documents_user_file_hash"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'success', 'failed')",
            name="ck_documents_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cloudinary_url: Mapped[str | None] = mapped_column(Text)
    cloudinary_public_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    document_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", server_default="unknown"
    )
    entity_name: Mapped[str | None] = mapped_column(String(255))
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upload_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
