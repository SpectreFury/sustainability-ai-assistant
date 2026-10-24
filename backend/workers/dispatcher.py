"""Dispatch durable extraction jobs and recover abandoned worker attempts."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update

from broker import broker
from db import SessionLocal
from models import Document, ExtractionOutbox, ExtractionRun
from services.extraction_queue import (
    MAX_EXTRACTION_ATTEMPTS,
    add_extraction_attempt,
    retry_delay_seconds,
)
from workers.extraction import process_document

logger = logging.getLogger(__name__)

_POLL_SECONDS = 2
_OUTBOX_BATCH_SIZE = 25
_DISPATCH_LEASE_SECONDS = 60
_REPUBLISH_AFTER_SECONDS = 60
_RECOVERY_BATCH_SIZE = 50


async def dispatch_due_outbox_rows() -> int:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        result = await session.scalars(
            select(ExtractionOutbox)
            .join(
                ExtractionRun,
                ExtractionRun.id == ExtractionOutbox.extraction_run_id,
            )
            .where(
                ExtractionRun.status == "queued",
                ExtractionOutbox.worker_claimed_at.is_(None),
                ExtractionOutbox.available_at <= now,
                or_(
                    ExtractionOutbox.next_dispatch_at.is_(None),
                    ExtractionOutbox.next_dispatch_at <= now,
                ),
                or_(
                    ExtractionOutbox.dispatch_lease_expires_at.is_(None),
                    ExtractionOutbox.dispatch_lease_expires_at <= now,
                ),
            )
            .order_by(ExtractionOutbox.available_at, ExtractionOutbox.created_at)
            .limit(_OUTBOX_BATCH_SIZE)
            .with_for_update(skip_locked=True, of=ExtractionOutbox)
        )
        rows = list(result)
        claimed: list[tuple[UUID, UUID, UUID, int]] = []
        for row in rows:
            token = uuid4()
            row.dispatch_lease_token = token
            row.dispatch_lease_expires_at = now + timedelta(
                seconds=_DISPATCH_LEASE_SECONDS
            )
            row.dispatch_attempts += 1
            claimed.append(
                (row.id, row.extraction_run_id, token, row.dispatch_attempts)
            )
        await session.commit()

    for outbox_id, run_id, lease_token, attempts in claimed:
        await _publish_claimed_row(outbox_id, run_id, lease_token, attempts)
    return len(claimed)


async def _publish_claimed_row(
    outbox_id: UUID,
    run_id: UUID,
    lease_token: UUID,
    dispatch_attempts: int,
) -> None:
    try:
        await process_document.kiq(str(run_id))
    except Exception as error:
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            row = await session.scalar(
                select(ExtractionOutbox)
                .where(
                    ExtractionOutbox.id == outbox_id,
                    ExtractionOutbox.dispatch_lease_token == lease_token,
                    ExtractionOutbox.worker_claimed_at.is_(None),
                )
                .with_for_update()
            )
            if row is None:
                return
            delay = min(2 ** min(row.dispatch_attempts, 6), 60)
            row.next_dispatch_at = now + timedelta(seconds=delay)
            row.dispatch_lease_token = None
            row.dispatch_lease_expires_at = None
            row.last_error = f"Queue publication failed ({type(error).__name__})."
            await session.commit()
        logger.warning(
            "Could not publish extraction run %s; will retry in %s seconds (%s)",
            run_id,
            delay,
            type(error).__name__,
        )
        return

    now = datetime.now(UTC)
    async with SessionLocal() as session:
        await session.execute(
            update(ExtractionOutbox)
            .where(
                ExtractionOutbox.id == outbox_id,
                ExtractionOutbox.dispatch_lease_token == lease_token,
                ExtractionOutbox.worker_claimed_at.is_(None),
            )
            .values(
                last_published_at=now,
                next_dispatch_at=now
                + timedelta(
                    seconds=min(
                        _REPUBLISH_AFTER_SECONDS
                        * 2 ** min(dispatch_attempts - 1, 3),
                        300,
                    )
                ),
                dispatch_lease_token=None,
                dispatch_lease_expires_at=None,
                last_error=None,
            )
        )
        await session.commit()


async def recover_stale_attempts() -> int:
    now = datetime.now(UTC)
    recovered = 0
    async with SessionLocal() as session:
        result = await session.scalars(
            select(ExtractionRun)
            .where(
                ExtractionRun.status == "running",
                or_(
                    ExtractionRun.lease_expires_at.is_(None),
                    ExtractionRun.lease_expires_at <= now,
                ),
            )
            .order_by(ExtractionRun.lease_expires_at, ExtractionRun.started_at)
            .limit(_RECOVERY_BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        runs = list(result)
        for run in runs:
            # The run row is locked before its document, matching the lock order
            # used by completion and failure handling.
            document = await session.scalar(
                select(Document)
                .where(Document.id == run.document_id)
                .with_for_update()
            )
            now = datetime.now(UTC)
            if (
                run.status != "running"
                or (run.lease_expires_at is not None and run.lease_expires_at > now)
            ):
                continue

            run.status = "failed"
            run.completed_at = now
            run.error_message = "Worker stopped before completing this attempt."
            run.lease_token = None
            run.lease_expires_at = None

            if document is None or document.status != "processing":
                recovered += 1
                continue

            if document.retry_count + 1 < MAX_EXTRACTION_ATTEMPTS:
                delay = retry_delay_seconds(run.attempt_number)
                await add_extraction_attempt(
                    session,
                    document,
                    available_at=now + timedelta(seconds=delay),
                    retry=True,
                    extraction_version=run.extraction_version,
                )
            else:
                document.status = "failed"
                document.error_message = (
                    "Document processing failed repeatedly. Please retry the document."
                )
                document.processing_started_at = None
                document.next_retry_at = None
            recovered += 1

        await session.commit()
    if recovered:
        logger.warning("Recovered %s abandoned extraction attempt(s)", recovered)
    return recovered


async def run_dispatcher() -> None:
    await broker.startup()
    logger.info("Extraction outbox dispatcher started")
    try:
        while True:
            try:
                await recover_stale_attempts()
                await dispatch_due_outbox_rows()
            except Exception:
                logger.exception("Extraction dispatch/recovery cycle failed")
            await asyncio.sleep(_POLL_SECONDS)
    finally:
        await broker.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_dispatcher())
