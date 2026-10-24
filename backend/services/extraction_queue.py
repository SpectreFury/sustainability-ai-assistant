from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models import Document, ExtractionOutbox, ExtractionRun

MAX_EXTRACTION_ATTEMPTS = 3
EXTRACTION_VERSION = "benchmark-facts-v1"


def retry_delay_seconds(attempt_number: int) -> int:
    return min(2**attempt_number, 30)


async def add_extraction_attempt(
    session: AsyncSession,
    document: Document,
    *,
    available_at: datetime | None = None,
    retry: bool = False,
    extraction_version: str = EXTRACTION_VERSION,
) -> ExtractionRun:
    """Add a queued run and its dispatch record to the current DB transaction."""
    now = datetime.now(UTC)
    available = available_at or now
    attempt_number = document.attempt_count + 1
    run = ExtractionRun(
        id=uuid4(),
        document_id=document.id,
        attempt_number=attempt_number,
        status="queued",
        extraction_version=extraction_version,
    )
    session.add(run)
    # There is no ORM relationship between the run and its outbox row, so make
    # the parent row visible before the FK-bearing outbox row is flushed.
    # This is still inside the caller's transaction; both rows commit or roll
    # back together.
    await session.flush()

    outbox = ExtractionOutbox(
        extraction_run_id=run.id,
        available_at=available,
    )

    document.attempt_count = attempt_number
    document.status = "processing"
    document.error_message = (
        "A temporary processing issue occurred. Retrying automatically."
        if retry
        else None
    )
    document.processing_started_at = None
    document.next_retry_at = available if retry else None
    if retry:
        document.retry_count += 1

    session.add(outbox)
    return run
