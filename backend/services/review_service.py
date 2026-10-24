import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import PurePath
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Document, DocumentSegment, ExtractedFact, ExtractionRun, User
from schemas.extraction import Locator, Segment
from schemas.review import (
    DocumentReviewResponse,
    ReviewFactResponse,
    ReviewFactsUpdateRequest,
    ReviewSegmentResponse,
    decimal_text,
)
from services.source_verification import verify_fact_source
from utils.cloudinary import create_signed_raw_download_url

_NUMBER = re.compile(r"(?<![\w/])[+-]?\d[\d,]*(?:\.\d+)?")
_NUMERIC_CATEGORIES = {"consumption", "meter_reading", "amount", "quantity", "rate"}


async def get_document_review(
    session: AsyncSession,
    user_id: int,
    document_id: UUID,
) -> DocumentReviewResponse:
    document = await _owned_document(session, user_id, document_id)
    run = await _latest_successful_run(session, document.id)
    return await _review_response(session, document, run)


async def save_document_review_facts(
    session: AsyncSession,
    user_id: int,
    document_id: UUID,
    payload: ReviewFactsUpdateRequest,
) -> DocumentReviewResponse:
    document = await _owned_document(session, user_id, document_id)
    run = await _latest_successful_run(session, document.id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is not ready for review yet.",
        )

    fact_ids = [item.id for item in payload.facts]
    result = await session.execute(
        select(ExtractedFact).where(
            ExtractedFact.document_id == document.id,
            ExtractedFact.extraction_run_id == run.id,
            ExtractedFact.id.in_(fact_ids),
        )
    )
    facts = {fact.id: fact for fact in result.scalars().all()}
    if len(facts) != len(fact_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more facts do not belong to this document.",
        )

    segments_result = await session.execute(
        select(DocumentSegment)
        .where(
            DocumentSegment.document_id == document.id,
            DocumentSegment.extraction_run_id == run.id,
        )
        .order_by(DocumentSegment.ordinal)
    )
    segments = [
        Segment(
            ordinal=segment.ordinal,
            locator=segment.locator,
            text=segment.text,
            cells=segment.cells,
            scanned=segment.scanned,
        )
        for segment in segments_result.scalars().all()
    ]
    now = datetime.now(UTC)

    for update in payload.facts:
        fact = facts[update.id]
        if fact.origin != "reported":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Calculated values cannot be edited as reported facts.",
            )

        label = update.label.strip()
        value_text = update.value_text.strip()
        fact.reviewed_label = label if label != fact.label else None
        fact.reviewed_value_text = value_text if value_text != fact.value_text else None

        if fact.reviewed_value_text is not None:
            value_number = _parse_single_number(value_text)
            fact.reviewed_value_number = value_number
            fact.reviewed_verified, fact.reviewed_verification = _verify_reviewed_value(
                fact,
                segments,
                value_text,
                value_number,
            )
        elif fact.reviewed_label is not None:
            fact.reviewed_value_number = None
            fact.reviewed_verified = fact.verified
            fact.reviewed_verification = fact.verification
        else:
            fact.reviewed_value_number = None
            fact.reviewed_verified = None
            fact.reviewed_verification = None

        edited = fact.reviewed_label is not None or fact.reviewed_value_text is not None
        fact.edited_by_user_id = user_id if edited else None
        fact.edited_at = now if edited else None

    await _recompute_per_day_facts(session, document.id, run.id)
    document.reviewed_at = None
    document.reviewed_by_user_id = None
    await session.commit()
    await session.refresh(document)
    run = await _latest_successful_run(session, document.id)
    return await _review_response(session, document, run)


async def mark_document_reviewed(
    session: AsyncSession,
    user_id: int,
    document_id: UUID,
) -> DocumentReviewResponse:
    document = await _owned_document(session, user_id, document_id)
    run = await _latest_successful_run(session, document.id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is not ready for review yet.",
        )

    document.reviewed_at = datetime.now(UTC)
    document.reviewed_by_user_id = user_id
    await session.commit()
    await session.refresh(document)
    return await _review_response(session, document, run)


async def _owned_document(
    session: AsyncSession,
    user_id: int,
    document_id: UUID,
) -> Document:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


async def _latest_successful_run(
    session: AsyncSession,
    document_id: UUID,
) -> ExtractionRun | None:
    return await session.scalar(
        select(ExtractionRun)
        .where(
            ExtractionRun.document_id == document_id,
            ExtractionRun.status == "succeeded",
        )
        .order_by(ExtractionRun.attempt_number.desc(), ExtractionRun.completed_at.desc())
        .limit(1)
    )


async def _review_response(
    session: AsyncSession,
    document: Document,
    run: ExtractionRun | None,
) -> DocumentReviewResponse:
    metadata = (run.result_metadata or {}) if run is not None else {}
    facts: list[ReviewFactResponse] = []
    segments: list[ReviewSegmentResponse] = []

    if run is not None:
        fact_result = await session.execute(
            select(ExtractedFact)
            .where(
                ExtractedFact.document_id == document.id,
                ExtractedFact.extraction_run_id == run.id,
            )
            .order_by(ExtractedFact.created_at, ExtractedFact.key)
        )
        for fact in fact_result.scalars().all():
            has_review = (
                fact.reviewed_label is not None
                or fact.reviewed_value_text is not None
            )
            facts.append(
                ReviewFactResponse(
                    id=fact.id,
                    key=fact.key,
                    label=fact.reviewed_label or fact.label,
                    original_label=fact.label,
                    category=fact.category,
                    metric=fact.metric,
                    series=fact.series,
                    value_text=(
                        fact.reviewed_value_text
                        if fact.reviewed_value_text is not None
                        else fact.value_text
                    ),
                    original_value_text=fact.value_text,
                    value_number=decimal_text(
                        fact.reviewed_value_number
                        if fact.reviewed_value_text is not None
                        else fact.value_number
                    ),
                    original_value_number=decimal_text(fact.value_number),
                    unit=fact.unit,
                    period_start=fact.period_start,
                    period_end=fact.period_end,
                    note=fact.note,
                    origin=fact.origin,
                    locator=Locator.model_validate(fact.locator),
                    quote=fact.quote,
                    verified=(
                        fact.reviewed_verified
                        if has_review and fact.reviewed_verified is not None
                        else fact.verified
                    ),
                    verification=(
                        fact.reviewed_verification or fact.verification
                        if has_review
                        else fact.verification
                    ),
                    derivation=fact.derivation,
                    edited=has_review,
                )
            )

        segment_result = await session.execute(
            select(DocumentSegment)
            .where(
                DocumentSegment.document_id == document.id,
                DocumentSegment.extraction_run_id == run.id,
            )
            .order_by(DocumentSegment.ordinal)
        )
        segments = [
            ReviewSegmentResponse(
                ordinal=segment.ordinal,
                locator=Locator.model_validate(segment.locator),
                text=segment.text,
                cells=segment.cells,
                scanned=segment.scanned,
            )
            for segment in segment_result.scalars().all()
        ]

    reviewer = None
    if document.reviewed_by_user_id is not None:
        reviewer = await session.scalar(
            select(User.username).where(User.id == document.reviewed_by_user_id)
        )

    file_url = _signed_file_url(document)
    return DocumentReviewResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        upload_timestamp=document.upload_timestamp,
        document_kind=document.document_kind,
        organisation=document.entity_name,
        title=_metadata_text(metadata, "title"),
        issuer=_metadata_text(metadata, "issuer"),
        period_start=_metadata_date(metadata.get("period_start")),
        period_end=_metadata_date(metadata.get("period_end")),
        page_count=_metadata_int(metadata.get("page_count")),
        summary=_metadata_text(metadata, "summary"),
        issues=[str(issue) for issue in metadata.get("issues", []) if issue],
        reviewed_at=document.reviewed_at,
        reviewed_by=reviewer,
        file_url=file_url,
        facts=facts,
        segments=segments,
    )


def _metadata_text(metadata: dict, key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if isinstance(value, str) and value.strip() else None


def _metadata_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _metadata_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _signed_file_url(document: Document) -> str | None:
    extension = PurePath(document.filename).suffix.casefold().removeprefix(".")
    if extension not in {"pdf", "xlsx"}:
        return None
    try:
        return create_signed_raw_download_url(document.cloudinary_public_id, extension)
    except RuntimeError:
        return None


def _parse_single_number(value: str) -> Decimal | None:
    matches = _NUMBER.findall(value)
    if len(matches) != 1:
        return None
    try:
        number = Decimal(matches[0].replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


async def _recompute_per_day_facts(
    session: AsyncSession,
    document_id: UUID,
    run_id: UUID,
) -> None:
    result = await session.execute(
        select(ExtractedFact).where(
            ExtractedFact.document_id == document_id,
            ExtractedFact.extraction_run_id == run_id,
        )
    )
    facts = list(result.scalars().all())
    by_key = {fact.key: fact for fact in facts}
    for derived in facts:
        if derived.origin != "calculated" or not derived.key.endswith("_per_day"):
            continue
        source = by_key.get(derived.key.removesuffix("_per_day"))
        if source is None:
            continue
        source_value = (
            source.reviewed_value_number
            if source.reviewed_value_text is not None
            else source.value_number
        )
        if source_value is None:
            derived.value_number = None
            derived.value_text = "Unable to calculate"
            derived.verified = False
            derived.verification = "The reviewed source value is not numeric"
            derived.derivation = "The reviewed source value is not numeric"
            continue
        if source.period_start is None or source.period_end is None:
            continue
        period_days = (source.period_end - source.period_start).days + 1
        if period_days <= 0:
            continue
        per_day = (source_value / Decimal(period_days)).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        derived.value_number = per_day
        derived.value_text = f"{per_day:,.2f} {source.unit or ''}".strip()
        derived.unit = f"{source.unit}/day" if source.unit else None
        derived.derivation = (
            f"{source_value} ÷ {period_days} days "
            f"({source.period_start.isoformat()} to {source.period_end.isoformat()}, inclusive)"
        )
        derived.verified = (
            source.reviewed_verified
            if source.reviewed_value_text is not None
            and source.reviewed_verified is not None
            else source.verified
        )
        derived.verification = "Derived from the reviewed reported value"


def _verify_reviewed_value(
    fact: ExtractedFact,
    segments: list[Segment],
    value_text: str,
    value_number: Decimal | None,
) -> tuple[bool, str]:
    locator = Locator.model_validate(fact.locator)
    numeric_value = fact.value_number is not None or fact.category in _NUMERIC_CATEGORIES
    if numeric_value:
        if value_number is None:
            return False, "Edited value is not a single unambiguous number"
        verified, reason = verify_fact_source(
            segments,
            locator,
            fact.quote,
            value_number,
            structured=True,
        )
        if not verified:
            return verified, reason
        quoted_numbers = _NUMBER.findall(fact.quote or "")
        try:
            quote_matches = any(
                Decimal(number.replace(",", "")) == value_number
                for number in quoted_numbers
            )
        except InvalidOperation:
            quote_matches = False
        if not quote_matches:
            return False, "Edited number does not appear in the cited source quote"
        return True, "Edited number appears in the cited source quote"

    if not fact.quote:
        return False, "Edited value has no source quote to check"
    if value_text.casefold() in fact.quote.casefold():
        return True, "Edited value appears in the cited source text"
    return False, "Edited value was not found in the cited source text"
