import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import update

from broker import broker
from db import SessionLocal
from models import Document, ExtractionRun
from services.errors import TemporaryExtractionError
from services.extraction import download_document, extract_document
from services.fact_persistence import persist_extracted_facts
from services.text_sanitization import sanitize_json, sanitize_text

logger = logging.getLogger(__name__)
_MAX_EXTRACTION_ATTEMPTS = 3


@broker.task
async def process_document(extraction_run_id: str) -> None:
    try:
        parsed_run_id = UUID(extraction_run_id)
    except ValueError:
        logger.error("Received an invalid extraction run id: %s", extraction_run_id)
        return

    document_id: UUID | None = None
    try:
        async with SessionLocal() as session:
            claim = await session.execute(
                update(ExtractionRun)
                .where(
                    ExtractionRun.id == parsed_run_id,
                    ExtractionRun.status == "queued",
                )
                .values(status="running")
                .returning(ExtractionRun.document_id, ExtractionRun.attempt_number)
            )
            claimed = claim.one_or_none()
            if claimed is None:
                return

            document_id, attempt_number = claimed
            run = await session.get(ExtractionRun, parsed_run_id)
            document = await session.get(Document, document_id)
            if run is None or document is None or document.status != "processing":
                if run is not None:
                    run.status = "failed"
                    run.error_message = "Document is no longer queued for processing."
                    run.completed_at = datetime.now(UTC)
                await session.commit()
                return

            document.attempt_count = attempt_number
            document.last_attempt_at = datetime.now(UTC)
            document.processing_started_at = datetime.now(UTC)
            document.next_retry_at = None
            cloudinary_public_id = document.cloudinary_public_id
            filename = document.filename
            file_hash = document.file_hash
            await session.commit()

        if not cloudinary_public_id:
            raise ValueError("Document has no Cloudinary public ID.")

        content = await download_document(cloudinary_public_id, filename, file_hash)
        extracted = await extract_document(filename, content)
        if not extracted.facts:
            raise ValueError("No supported facts were extracted from this document.")

        async with SessionLocal() as session:
            run = await session.get(ExtractionRun, parsed_run_id)
            document = await session.get(Document, document_id)
            if (
                run is None
                or run.status != "running"
                or document is None
                or document.status != "processing"
            ):
                return

            await persist_extracted_facts(
                session,
                document_id=document.id,
                run=run,
                document_kind=extracted.document_kind,
                extracted=extracted,
            )

            run.status = "succeeded"
            run.completed_at = datetime.now(UTC)
            run.result_metadata = sanitize_json(
                {
                    "fact_count": len(extracted.facts),
                    "source_evidence_count": len(extracted.source_evidence)
                    + len(extracted.facts),
                    "warnings": extracted.warnings,
                }
            )
            document.document_kind = sanitize_text(extracted.document_kind) or "unknown"
            document.entity_name = sanitize_text(extracted.entity_name)
            document.status = "success"
            document.error_message = None
            document.processing_started_at = None
            document.next_retry_at = None
            await session.commit()
    except Exception as error:
        logger.exception(
            "Extraction failed for document %s (run %s)",
            document_id,
            extraction_run_id,
        )
        await _mark_failed(parsed_run_id, document_id, error)


async def _mark_failed(
    run_id: UUID,
    document_id: UUID | None,
    error: Exception,
) -> None:
    retry_run_id: UUID | None = None
    retry_delay = 0
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        run = await session.get(ExtractionRun, run_id)
        if run is None or run.status != "running":
            return
        document = (
            await session.get(Document, document_id) if document_id is not None else None
        )
        run.status = "failed"
        run.completed_at = now

        can_retry = (
            document is not None
            and document.status == "processing"
            and run.attempt_number < _MAX_EXTRACTION_ATTEMPTS
            and _is_retryable_error(error)
        )
        if can_retry and document is not None:
            retry_run = ExtractionRun(
                document_id=document.id,
                attempt_number=run.attempt_number + 1,
                status="queued",
                extraction_version=run.extraction_version,
            )
            retry_run_id = retry_run.id
            retry_delay = min(2**run.attempt_number, 30)
            document.attempt_count = retry_run.attempt_number
            document.status = "processing"
            document.error_message = _user_facing_error(error, retrying=True)
            document.processing_started_at = None
            document.next_retry_at = now + timedelta(seconds=retry_delay)
            session.add(retry_run)
        elif document is not None and document.status == "processing":
            document.status = "failed"
            document.error_message = _user_facing_error(error)
            document.processing_started_at = None
            document.next_retry_at = None
        run.error_message = _user_facing_error(error)
        await session.commit()

    if retry_run_id is not None:
        await asyncio.sleep(retry_delay)
        try:
            await process_document.kiq(str(retry_run_id))
        except Exception as enqueue_error:
            logger.error(
                "Unable to enqueue retry run %s (%s)",
                retry_run_id,
                type(enqueue_error).__name__,
            )
            await _mark_retry_enqueue_failed(retry_run_id, document_id)


def _is_retryable_error(error: Exception) -> bool:
    if isinstance(error, (TemporaryExtractionError, TimeoutError, ConnectionError)):
        return True
    name = type(error).__name__.casefold()
    return any(
        token in name
        for token in (
            "timeout",
            "resourceexhausted",
            "serviceunavailable",
            "internalservererror",
            "toomanyrequests",
        )
    )


async def _mark_retry_enqueue_failed(
    run_id: UUID,
    document_id: UUID | None,
) -> None:
    async with SessionLocal() as session:
        run = await session.get(ExtractionRun, run_id)
        document = (
            await session.get(Document, document_id) if document_id is not None else None
        )
        if run is not None and run.status == "queued":
            run.status = "failed"
            run.error_message = "Could not enqueue the retry job."
            run.completed_at = datetime.now(UTC)
        if document is not None and document.status == "processing":
            document.status = "failed"
            document.error_message = (
                "Could not enqueue a retry after a temporary processing error."
            )
            document.processing_started_at = None
            document.next_retry_at = None
        await session.commit()


def _user_facing_error(error: Exception, *, retrying: bool = False) -> str:
    if retrying:
        return "A temporary processing issue occurred. Retrying automatically."

    message = str(error).strip()
    known_messages = {
        "Encrypted PDFs are not supported.": (
            "This PDF is password-protected and cannot be processed."
        ),
        "Downloaded document is empty.": "The uploaded file is empty or unavailable.",
        "Downloaded document checksum does not match the uploaded file.": (
            "File verification failed. Please upload the document again."
        ),
        "Set GEMINI_API_KEY to enable PDF extraction.": (
            "PDF extraction is not configured. Please contact your administrator."
        ),
        "No supported facts were extracted from this document.": (
            "No supported information could be extracted from this document."
        ),
        "No verifiable facts were extracted from the PDF.": (
            "No verifiable information could be extracted from this PDF."
        ),
    }
    if message in known_messages:
        return known_messages[message]
    if "size limit" in message.casefold():
        return "This document exceeds the configured processing size limit."
    if "unsupported file type" in message.casefold():
        return "Only PDF and XLSX documents are supported."
    if "cloudinary" in message.casefold():
        return "The uploaded document could not be retrieved from storage."
    return "Document processing failed. Please try again or contact support."
