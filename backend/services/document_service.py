import logging
from datetime import UTC, datetime
from pathlib import PurePath
from time import perf_counter, time
from urllib.parse import urlparse
from uuid import UUID, uuid4

from cloudinary.utils import api_sign_request
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import Document, ExtractionRun
from schemas.documents import (
    DocumentResponse,
    UploadCompleteRequest,
    UploadSignatureRequest,
    UploadSignatureResponse,
)
from services.extraction_queue import add_extraction_run
from utils.cloudinary import configure_cloudinary

logger = logging.getLogger(__name__)


async def create_upload_signature(
    session: AsyncSession,
    user_id: int,
    payload: UploadSignatureRequest,
) -> UploadSignatureResponse:
    cloudinary_config = configure_cloudinary()
    filename = PurePath(payload.filename).name
    existing = await session.scalar(
        select(Document).where(
            Document.user_id == user_id,
            Document.file_hash == payload.file_hash,
        )
    )

    public_id = (
        f"documents/{user_id}/{uuid4().hex}{PurePath(filename).suffix.lower()}"
    )

    if existing is not None and existing.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document has already been uploaded.",
        )

    if existing is None:
        document = Document(
            user_id=user_id,
            filename=filename,
            file_hash=payload.file_hash,
            cloudinary_public_id=public_id,
        )
        session.add(document)
    else:
        document = existing
        document.filename = filename
        document.cloudinary_url = None
        document.cloudinary_public_id = public_id
        document.status = "pending"
        document.error_message = None
        document.retry_count = 0
        document.upload_timestamp = datetime.now(UTC)

    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document has already been uploaded.",
        ) from error

    await session.refresh(document)

    timestamp = int(time())
    params = {"timestamp": timestamp, "public_id": public_id}
    return UploadSignatureResponse(
        document_id=document.id,
        upload_url=(
            f"https://api.cloudinary.com/v1_1/"
            f"{cloudinary_config['cloud_name']}/raw/upload"
        ),
        cloud_name=cloudinary_config["cloud_name"],
        api_key=cloudinary_config["api_key"],
        timestamp=timestamp,
        public_id=public_id,
        signature=api_sign_request(params, cloudinary_config["api_secret"]),
    )


async def complete_document_upload(
    session: AsyncSession,
    user_id: int,
    document_id: UUID,
    payload: UploadCompleteRequest,
) -> Document:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document.cloudinary_public_id != payload.cloudinary_public_id:
        raise HTTPException(status_code=400, detail="Invalid Cloudinary asset.")
    cloudinary_url = urlparse(str(payload.cloudinary_url))
    if (
        cloudinary_url.scheme != "https"
        or cloudinary_url.hostname != "res.cloudinary.com"
    ):
        raise HTTPException(status_code=400, detail="Invalid Cloudinary URL.")

    document.cloudinary_url = str(payload.cloudinary_url)
    document.status = "pending"
    document.error_message = None
    await session.commit()
    await session.refresh(document)
    return document


async def fail_document_upload(
    session: AsyncSession,
    user_id: int,
    document_id: UUID,
    _error_message: str,
) -> Document:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    document.status = "failed"
    # The client-facing document status is not a debugging channel. Detailed
    # failures belong in server logs, not in the persisted/API-visible message.
    document.error_message = "The upload failed. Please select the file and retry."
    await session.commit()
    await session.refresh(document)
    return document


async def list_user_documents(
    session: AsyncSession,
    user_id: int,
) -> list[Document]:
    documents = await session.scalars(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.upload_timestamp.desc())
    )
    return list(documents)


async def queue_pending_documents(
    session: AsyncSession,
    user_id: int,
) -> list[Document]:
    pending = await session.scalars(
        select(Document)
        .where(Document.user_id == user_id, Document.status == "pending")
        .order_by(Document.upload_timestamp)
        .with_for_update(skip_locked=True)
    )
    documents = list(pending)
    if not documents:
        return []

    queueable: list[tuple[Document, ExtractionRun]] = []
    for document in documents:
        if not document.cloudinary_url:
            document.status = "failed"
            document.error_message = (
                "The upload has not completed, so it cannot be processed."
            )
            continue

        extension = PurePath(document.filename).suffix.lower()
        if extension not in {".xlsx", ".pdf"}:
            document.status = "failed"
            document.error_message = (
                "Unsupported file type. Only .xlsx and .pdf are supported."
            )
            continue
        document.retry_count = 0
        run = await add_extraction_run(session, document)
        queueable.append((document, run))

    if not queueable:
        await session.commit()
        for document in documents:
            await session.refresh(document)
        return documents

    try:
        from workers.extraction import process_document
    except RuntimeError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Document processing is unavailable. Configure REDIS_URL and "
                "start the worker."
            ),
        ) from error

    await session.commit()

    queue_failures = 0
    for document, run in queueable:
        publish_started = perf_counter()
        try:
            await process_document.kiq(str(run.id))
        except Exception as error:
            queue_failures += 1
            logger.exception(
                "event=task_publish_failed task=extraction run_id=%s document_id=%s filename=%r error_type=%s",
                run.id,
                document.id,
                document.filename,
                type(error).__name__,
            )
            await session.rollback()
            persisted_run = await session.scalar(
                select(ExtractionRun)
                .where(ExtractionRun.id == run.id)
                .with_for_update()
            )
            persisted_document = await session.scalar(
                select(Document)
                .where(Document.id == document.id)
                .with_for_update()
            )
            if persisted_run is not None and persisted_run.status == "queued":
                persisted_run.status = "failed"
                persisted_run.error_message = "Could not submit this job to Redis."
                persisted_run.completed_at = datetime.now(UTC)
            if (
                persisted_document is not None
                and persisted_document.status == "processing"
            ):
                persisted_document.status = "pending"
                persisted_document.error_message = (
                    "Could not submit this job to the worker queue. Please try again."
                )
                persisted_document.processing_started_at = None
                persisted_document.next_retry_at = None
            await session.commit()
            continue

        logger.info(
            "event=task_dispatched task=extraction run_id=%s document_id=%s filename=%r queue_publish_ms=%s",
            run.id,
            document.id,
            document.filename,
            int((perf_counter() - publish_started) * 1000),
        )

    for document in documents:
        await session.refresh(document)

    if queue_failures == len(queueable):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not submit processing jobs. Check Redis and try again.",
        )
    return documents
