from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models import Document, ExtractionRun

MAX_EXTRACTION_ATTEMPTS = 3
EXTRACTION_VERSION = "kuki-facts-v2"


def retry_delay_seconds(attempt_number: int) -> int:
    return min(2**attempt_number, 30)


async def add_extraction_run(
    session: AsyncSession, document: Document
) -> ExtractionRun:
    """Persist a run before the API publishes its ID directly to Redis."""
    attempt_number = document.attempt_count + 1
    run = ExtractionRun(
        id=uuid4(),
        document_id=document.id,
        attempt_number=attempt_number,
        status="queued",
        extraction_version=EXTRACTION_VERSION,
    )
    session.add(run)
    document.attempt_count = attempt_number
    document.status = "processing"
    document.error_message = None
    document.processing_started_at = None
    document.next_retry_at = None
    return run
