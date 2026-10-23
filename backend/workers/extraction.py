import logging
from uuid import UUID

from sqlalchemy import delete

from broker import broker
from db import SessionLocal
from models import Document, ExtractedRecord
from services.extraction import download_document, extract_document

logger = logging.getLogger(__name__)


@broker.task
async def process_document(document_id: str) -> None:
    try:
        parsed_document_id = UUID(document_id)
    except ValueError:
        logger.error("Received an invalid document id for extraction: %s", document_id)
        return

    try:
        async with SessionLocal() as session:
            document = await session.get(Document, parsed_document_id)
            if document is None or document.status != "processing":
                return
            cloudinary_url = document.cloudinary_url
            filename = document.filename
            file_hash = document.file_hash

        if not cloudinary_url:
            raise ValueError("Document has no stored file URL.")

        content = await download_document(cloudinary_url, file_hash)
        document_type, metrics = await extract_document(filename, content)

        async with SessionLocal() as session:
            document = await session.get(Document, parsed_document_id)
            if document is None or document.status != "processing":
                return

            await session.execute(
                delete(ExtractedRecord).where(
                    ExtractedRecord.document_id == parsed_document_id
                )
            )
            session.add_all(
                ExtractedRecord(
                    document_id=parsed_document_id,
                    document_type=document_type,
                    metric_name=metric.metric_name,
                    metric_value=metric.metric_value,
                    unit=metric.unit,
                    billing_period_start=metric.billing_period_start,
                    billing_period_end=metric.billing_period_end,
                    financial_year=metric.financial_year,
                    source_reference=metric.source_reference,
                )
                for metric in metrics
            )
            document.status = "success"
            document.error_message = None
            await session.commit()
    except Exception as error:
        logger.exception("Extraction failed for document %s", document_id)
        await _mark_failed(parsed_document_id, error)


async def _mark_failed(document_id: UUID, error: Exception) -> None:
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None or document.status != "processing":
            return
        message = str(error).strip() or "Document extraction failed."
        document.status = "failed"
        document.error_message = message[:2000]
        await session.commit()
