import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select, update

from broker import broker
from db import SessionLocal
from models import Document, ExtractionRun
from services.errors import TemporaryExtractionError
from services.extraction import download_document, extract_document
from services.extraction_queue import (
    MAX_EXTRACTION_ATTEMPTS,
    retry_delay_seconds,
)
from services.fact_persistence import persist_extraction
from services.text_sanitization import sanitize_json, sanitize_text
from utils.worker_logging import configure_worker_logging
# Register evaluation tasks on the same broker so the existing worker command
# can consume both document processing and evaluation jobs.
from workers.evaluation import process_evaluation as _process_evaluation

logger = logging.getLogger(__name__)
_LEASE_SECONDS = max(30, int(os.getenv("EXTRACTION_RUN_LEASE_SECONDS", "120")))
_HEARTBEAT_SECONDS = max(
    5,
    min(
        int(os.getenv("EXTRACTION_RUN_HEARTBEAT_SECONDS", "30")),
        _LEASE_SECONDS // 2,
    ),
)

if broker.is_worker_process:
    configure_worker_logging()
    logger.info("Worker task registered | task=extraction")


@broker.task
async def process_document(extraction_run_id: str) -> None:
    configure_worker_logging()
    logger.info(
        "event=worker_task_received task=extraction run_id=%s",
        extraction_run_id,
    )
    try:
        parsed_run_id = UUID(extraction_run_id)
    except ValueError:
        logger.error(
            "event=worker_task_rejected task=extraction reason=invalid_run_id run_id=%s",
            extraction_run_id,
        )
        return

    job_started = perf_counter()
    stage = "claim"
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
                    or_(
                        ExtractionRun.status == "queued",
                        and_(
                            ExtractionRun.status == "running",
                            or_(
                                ExtractionRun.lease_expires_at.is_(None),
                                ExtractionRun.lease_expires_at <= now,
                            ),
                        ),
                    ),
                )
                .values(
                    status="running",
                    lease_token=lease_token,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=_LEASE_SECONDS),
                    completed_at=None,
                    error_message=None,
                )
                .returning(ExtractionRun.document_id, ExtractionRun.attempt_number)
            )
            claimed = claim.one_or_none()
            if claimed is None:
                logger.info(
                    "event=worker_task_skipped task=extraction run_id=%s reason=not_queued_or_already_claimed",
                    parsed_run_id,
                )
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
                logger.warning(
                    "event=worker_task_rejected task=extraction run_id=%s document_id=%s reason=document_not_processing",
                    parsed_run_id,
                    document_id,
                )
                return

            document.attempt_count = attempt_number
            document.last_attempt_at = now
            document.processing_started_at = now
            document.next_retry_at = None
            document.error_message = None
            cloudinary_public_id = document.cloudinary_public_id
            filename = document.filename
            file_hash = document.file_hash
            logger.info(
                "event=worker_task_claimed task=extraction run_id=%s document_id=%s filename=%r attempt=%s",
                parsed_run_id,
                document_id,
                filename,
                attempt_number,
            )
            await session.commit()

        heartbeat_task = asyncio.create_task(
            _heartbeat_lease(parsed_run_id, lease_token),
            name=f"extraction-heartbeat-{parsed_run_id}",
        )

        if not cloudinary_public_id:
            raise ValueError("Document has no Cloudinary public ID.")

        stage = "cloudinary_download"
        download_started = perf_counter()
        logger.info(
            "Fetching from Cloudinary | event=stage_started task=extraction stage=cloudinary_download run_id=%s document_id=%s filename=%r",
            parsed_run_id,
            document_id,
            filename,
        )
        try:
            content = await download_document(
                cloudinary_public_id, filename, file_hash
            )
        except Exception as error:
            logger.error(
                "Cloudinary fetch failed | event=stage_failed task=extraction stage=cloudinary_download run_id=%s document_id=%s filename=%r duration_ms=%s error_type=%s",
                parsed_run_id,
                document_id,
                filename,
                int((perf_counter() - download_started) * 1000),
                type(error).__name__,
            )
            raise
        logger.info(
            "Fetched from Cloudinary | event=stage_finished task=extraction stage=cloudinary_download run_id=%s document_id=%s filename=%r duration_ms=%s bytes=%s",
            parsed_run_id,
            document_id,
            filename,
            int((perf_counter() - download_started) * 1000),
            len(content),
        )

        stage = "llm_extraction"
        extraction_started = perf_counter()
        logger.info(
            "Sending document to Gemini for fact extraction | event=stage_started task=extraction stage=llm_extraction run_id=%s document_id=%s filename=%r bytes=%s",
            parsed_run_id,
            document_id,
            filename,
            len(content),
        )
        try:
            extracted = await extract_document(
                filename,
                content,
                trace_context={
                    "document_id": str(document_id),
                    "extraction_run_id": str(parsed_run_id),
                    "attempt_number": str(attempt_number),
                },
            )
        except Exception as error:
            logger.error(
                "Gemini fact extraction failed | event=stage_failed task=extraction stage=llm_extraction run_id=%s document_id=%s filename=%r duration_ms=%s error_type=%s",
                parsed_run_id,
                document_id,
                filename,
                int((perf_counter() - extraction_started) * 1000),
                type(error).__name__,
            )
            raise
        logger.info(
            "Received extraction from Gemini | event=stage_finished task=extraction stage=llm_extraction run_id=%s document_id=%s filename=%r duration_ms=%s model=%s pipeline=%s facts=%s verified_facts=%s segments=%s",
            parsed_run_id,
            document_id,
            filename,
            int((perf_counter() - extraction_started) * 1000),
            extracted.model,
            extracted.pipeline,
            len(extracted.facts),
            sum(fact.verified for fact in extracted.facts),
            len(extracted.segments),
        )
        if not extracted.facts:
            raise ValueError("No supported facts were extracted from this document.")

        stage = "persist_result"
        async with SessionLocal() as session:
            # Lock the run before checking its fencing token. A redelivered
            # task can reclaim an expired lease, while this token prevents an
            # older worker attempt from overwriting the reclaimed result.
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
                logger.warning(
                    "event=worker_result_discarded task=extraction run_id=%s document_id=%s reason=lease_or_document_state_changed",
                    parsed_run_id,
                    document_id,
                )
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
            logger.info(
                "event=worker_task_finished task=extraction status=succeeded run_id=%s document_id=%s filename=%r attempt=%s duration_ms=%s facts=%s verified_facts=%s model=%s",
                parsed_run_id,
                document_id,
                filename,
                attempt_number,
                int((perf_counter() - job_started) * 1000),
                len(extracted.facts),
                sum(fact.verified for fact in extracted.facts),
                extracted.model,
            )
    except Exception as error:
        logger.exception(
            "event=worker_task_failed task=extraction stage=%s run_id=%s document_id=%s error_type=%s",
            stage,
            parsed_run_id,
            document_id,
            type(error).__name__,
        )
        retry_delay = await _mark_failed(
            parsed_run_id,
            document_id,
            lease_token,
            error,
        )
        if retry_delay is not None:
            await asyncio.sleep(retry_delay)
            try:
                publish_started = perf_counter()
                await process_document.kiq(str(parsed_run_id))
            except Exception as publish_error:
                logger.exception(
                    "event=retry_publish_failed task=extraction run_id=%s document_id=%s error_type=%s",
                    parsed_run_id,
                    document_id,
                    type(publish_error).__name__,
                )
                await _mark_retry_enqueue_failed(
                    parsed_run_id,
                    document_id,
                    publish_error,
                )
                logger.error(
                    "event=worker_task_finished task=extraction status=retry_enqueue_failed run_id=%s document_id=%s duration_ms=%s",
                    parsed_run_id,
                    document_id,
                    int((perf_counter() - job_started) * 1000),
                )
            else:
                logger.info(
                    "event=task_dispatched task=extraction run_id=%s document_id=%s retry=true queue_publish_ms=%s",
                    parsed_run_id,
                    document_id,
                    int((perf_counter() - publish_started) * 1000),
                )
                logger.info(
                    "event=worker_task_finished task=extraction status=retry_scheduled run_id=%s document_id=%s duration_ms=%s",
                    parsed_run_id,
                    document_id,
                    int((perf_counter() - job_started) * 1000),
                )
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
) -> int | None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        run = await session.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.id == run_id)
            .with_for_update()
        )
        if run is None or run.status != "running" or run.lease_token != lease_token:
            return None
        document = None
        if document_id is not None:
            document = await session.scalar(
                select(Document)
                .where(Document.id == document_id)
                .with_for_update()
            )

        run.lease_token = None
        run.lease_expires_at = None

        can_retry = (
            document is not None
            and document.status == "processing"
            and document.retry_count + 1 < MAX_EXTRACTION_ATTEMPTS
            and _is_retryable_error(error)
        )
        if can_retry and document is not None:
            failed_attempt = run.attempt_number
            delay = retry_delay_seconds(run.attempt_number)
            run.status = "queued"
            run.completed_at = None
            run.error_message = _user_facing_error(error)
            run.attempt_number += 1
            document.attempt_count = run.attempt_number
            document.retry_count += 1
            document.error_message = (
                "A temporary processing issue occurred. Retrying automatically."
            )
            document.processing_started_at = None
            document.next_retry_at = now + timedelta(seconds=delay)
            await session.commit()
            logger.warning(
                "event=worker_retry_scheduled task=extraction run_id=%s document_id=%s filename=%r failed_attempt=%s next_attempt=%s delay_seconds=%s error_type=%s",
                run_id,
                document.id,
                document.filename,
                failed_attempt,
                run.attempt_number,
                delay,
                type(error).__name__,
            )
            return delay
        elif document is not None and document.status == "processing":
            run.status = "failed"
            run.completed_at = now
            document.status = "failed"
            document.error_message = _user_facing_error(error)
            document.processing_started_at = None
            document.next_retry_at = None
            run.error_message = document.error_message
        else:
            run.status = "failed"
            run.completed_at = now
            run.error_message = _user_facing_error(error)
        await session.commit()
        logger.error(
            "event=worker_task_finished task=extraction status=failed run_id=%s document_id=%s filename=%r attempt=%s error_type=%s",
            run_id,
            document_id,
            document.filename if document is not None else None,
            run.attempt_number,
            type(error).__name__,
        )
        return None


async def _mark_retry_enqueue_failed(
    run_id: UUID,
    document_id: UUID | None,
    error: Exception,
) -> None:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        run = await session.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.id == run_id)
            .with_for_update()
        )
        document = (
            await session.scalar(
                select(Document)
                .where(Document.id == document_id)
                .with_for_update()
            )
            if document_id is not None
            else None
        )
        if run is not None and run.status == "queued":
            run.status = "failed"
            run.completed_at = now
            run.error_message = "Could not submit the automatic retry to Redis."
            run.lease_token = None
            run.lease_expires_at = None
        if document is not None and document.status == "processing":
            document.status = "pending"
            document.error_message = (
                "Automatic retry could not be submitted. Please start processing again."
            )
            document.processing_started_at = None
            document.next_retry_at = None
        await session.commit()
    logger.error(
        "event=worker_retry_abandoned task=extraction run_id=%s document_id=%s error_type=%s",
        run_id,
        document_id,
        type(error).__name__,
    )


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
