import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update

from broker import broker
from db import SessionLocal
from models import Document, ExtractionOutbox, ExtractionRun
from services.errors import TemporaryExtractionError
from services.extraction import download_document, extract_document
from services.extraction_queue import (
    MAX_EXTRACTION_ATTEMPTS,
    add_extraction_attempt,
    retry_delay_seconds,
)
from services.fact_persistence import persist_extraction
from services.text_sanitization import sanitize_json, sanitize_text

logger = logging.getLogger(__name__)
_LEASE_SECONDS = max(30, int(os.getenv("EXTRACTION_RUN_LEASE_SECONDS", "120")))
_HEARTBEAT_SECONDS = max(
    5,
    min(
        int(os.getenv("EXTRACTION_RUN_HEARTBEAT_SECONDS", "30")),
        _LEASE_SECONDS // 2,
    ),
)


@broker.task
async def process_document(extraction_run_id: str) -> None:
    try:
        parsed_run_id = UUID(extraction_run_id)
    except ValueError:
        logger.error("Received an invalid extraction run id: %s", extraction_run_id)
        return

    document_id: UUID | None = None
    lease_token = uuid4()
    heartbeat_task: asyncio.Task | None = None
    try:
        async with SessionLocal() as session:
            now = datetime.now(UTC)
            claim = await session.execute(
                update(ExtractionRun)
                .where(
                    ExtractionRun.id == parsed_run_id,
                    ExtractionRun.status == "queued",
                )
                .values(
                    status="running",
                    lease_token=lease_token,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=_LEASE_SECONDS),
                )
                .returning(ExtractionRun.document_id, ExtractionRun.attempt_number)
            )
            claimed = claim.one_or_none()
            if claimed is None:
                return

            document_id, attempt_number = claimed
            document = await session.scalar(
                select(Document)
                .where(Document.id == document_id)
                .with_for_update()
            )
            run = await session.get(ExtractionRun, parsed_run_id)
            if run is None or document is None or document.status != "processing":
                if run is not None:
                    run.status = "failed"
                    run.error_message = "Document is no longer queued for processing."
                    run.completed_at = datetime.now(UTC)
                    run.lease_token = None
                    run.lease_expires_at = None
                await session.commit()
                return

            document.attempt_count = attempt_number
            document.last_attempt_at = now
            document.processing_started_at = now
            document.next_retry_at = None
            document.error_message = None
            cloudinary_public_id = document.cloudinary_public_id
            filename = document.filename
            file_hash = document.file_hash
            await session.execute(
                update(ExtractionOutbox)
                .where(
                    ExtractionOutbox.extraction_run_id == parsed_run_id,
                    ExtractionOutbox.worker_claimed_at.is_(None),
                )
                .values(
                    worker_claimed_at=now,
                    dispatch_lease_token=None,
                    dispatch_lease_expires_at=None,
                    next_dispatch_at=None,
                )
            )
            await session.commit()

        heartbeat_task = asyncio.create_task(
            _heartbeat_lease(parsed_run_id, lease_token),
            name=f"extraction-heartbeat-{parsed_run_id}",
        )

        if not cloudinary_public_id:
            raise ValueError("Document has no Cloudinary public ID.")

        content = await download_document(cloudinary_public_id, filename, file_hash)
        extracted = await extract_document(
            filename,
            content,
            trace_context={
                "document_id": str(document_id),
                "extraction_run_id": str(parsed_run_id),
                "attempt_number": str(attempt_number),
            },
        )
        if not extracted.facts:
            raise ValueError("No supported facts were extracted from this document.")

        async with SessionLocal() as session:
            # Lock the run before checking its fencing token. A recovery sweep
            # either wins first and makes this attempt a no-op, or waits until
            # this complete result transaction commits.
            run = await session.scalar(
                select(ExtractionRun)
                .where(ExtractionRun.id == parsed_run_id)
                .with_for_update()
            )
            document = await session.scalar(
                select(Document)
                .where(Document.id == document_id)
                .with_for_update()
            )
            now = datetime.now(UTC)
            if (
                run is None
                or run.status != "running"
                or run.lease_token != lease_token
                or run.lease_expires_at is None
                or run.lease_expires_at <= now
                or document is None
                or document.status != "processing"
            ):
                return

            await persist_extraction(
                session,
                document_id=document.id,
                run=run,
                extracted=extracted,
            )

            run.status = "succeeded"
            run.completed_at = now
            run.model_name = extracted.model
            run.lease_token = None
            run.lease_expires_at = None
            run.result_metadata = sanitize_json(
                {
                    "fact_count": len(extracted.facts),
                    "verified_fact_count": sum(fact.verified for fact in extracted.facts),
                    "unverified_fact_count": sum(not fact.verified for fact in extracted.facts),
                    "segment_count": len(extracted.segments),
                    "issues": extracted.issues,
                    "title": extracted.title,
                    "issuer": extracted.issuer,
                    "summary": extracted.summary,
                    "period_start": extracted.period_start,
                    "period_end": extracted.period_end,
                    "page_count": extracted.page_count,
                    "model": extracted.model,
                    "pipeline": extracted.pipeline,
                }
            )
            document.document_kind = sanitize_text(extracted.doc_type) or "unknown"
            document.entity_name = sanitize_text(extracted.organisation)
            document.status = "success"
            document.error_message = None
            document.processing_started_at = None
            document.next_retry_at = None
            document.retry_count = 0
            await session.commit()
    except Exception as error:
        logger.exception(
            "Extraction failed for document %s (run %s)",
            document_id,
            extraction_run_id,
        )
        await _mark_failed(parsed_run_id, document_id, lease_token, error)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)


async def _heartbeat_lease(run_id: UUID, lease_token: UUID) -> None:
    while True:
        await asyncio.sleep(_HEARTBEAT_SECONDS)
        now = datetime.now(UTC)
        try:
            async with SessionLocal() as session:
                result = await session.execute(
                    update(ExtractionRun)
                    .where(
                        ExtractionRun.id == run_id,
                        ExtractionRun.status == "running",
                        ExtractionRun.lease_token == lease_token,
                    )
                    .values(
                        heartbeat_at=now,
                        lease_expires_at=now + timedelta(seconds=_LEASE_SECONDS),
                    )
                )
                await session.commit()
                if result.rowcount != 1:
                    return
        except Exception:
            logger.exception("Could not renew extraction lease for run %s", run_id)


async def _mark_failed(
    run_id: UUID,
    document_id: UUID | None,
    lease_token: UUID,
    error: Exception,
) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        run = await session.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.id == run_id)
            .with_for_update()
        )
        if run is None or run.status != "running" or run.lease_token != lease_token:
            return
        document = None
        if document_id is not None:
            document = await session.scalar(
                select(Document)
                .where(Document.id == document_id)
                .with_for_update()
            )

        run.status = "failed"
        run.completed_at = now
        run.lease_token = None
        run.lease_expires_at = None

        can_retry = (
            document is not None
            and document.status == "processing"
            and document.retry_count + 1 < MAX_EXTRACTION_ATTEMPTS
            and _is_retryable_error(error)
        )
        if can_retry and document is not None:
            delay = retry_delay_seconds(run.attempt_number)
            run.error_message = _user_facing_error(error)
            await add_extraction_attempt(
                session,
                document,
                available_at=now + timedelta(seconds=delay),
                retry=True,
                extraction_version=run.extraction_version,
            )
        elif document is not None and document.status == "processing":
            document.status = "failed"
            document.error_message = _user_facing_error(error)
            document.processing_started_at = None
            document.next_retry_at = None
            run.error_message = document.error_message
        else:
            run.error_message = _user_facing_error(error)
        await session.commit()


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


def _user_facing_error(error: Exception) -> str:
    message = str(error).strip()
    known_messages = {
        "Encrypted PDFs are not supported.": (
            "This PDF is password-protected and cannot be processed."
        ),
        "Downloaded document is empty.": "The uploaded file is empty or unavailable.",
        "The uploaded document is empty.": "The uploaded file is empty or unavailable.",
        "Downloaded document checksum does not match the uploaded file.": (
            "File verification failed. Please upload the document again."
        ),
        "Set GEMINI_API_KEY to enable document extraction.": (
            "Document extraction is not configured. Please contact your administrator."
        ),
        "No supported facts were extracted from this document.": (
            "No supported information could be extracted from this document."
        ),
        "No verifiable facts were extracted from the PDF.": (
            "No verifiable information could be extracted from this PDF."
        ),
        "The model returned no structured extraction.": (
            "No supported information could be extracted from this document."
        ),
        "Only PDF and XLSX documents are supported.": (
            "Only PDF and XLSX documents are supported."
        ),
    }
    if message in known_messages:
        return known_messages[message]
    if "size limit" in message.casefold():
        return "This document exceeds the configured processing size limit."
    if "password protected" in message.casefold():
        return "This PDF is password-protected and cannot be processed."
    if "unsupported file type" in message.casefold():
        return "Only PDF and XLSX documents are supported."
    if "cloudinary" in message.casefold():
        return "The uploaded document could not be retrieved from storage."
    return "Document processing failed. Please try again or contact support."
