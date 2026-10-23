from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models import DocumentSegment, ExtractedFact, ExtractionRun
from schemas.extraction import Extraction
from services.text_sanitization import sanitize_json, sanitize_text


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


async def persist_extraction(
    session: AsyncSession,
    document_id: UUID,
    run: ExtractionRun,
    extracted: Extraction,
) -> None:
    """Persist verified facts and their source segments in the worker transaction."""
    segments = [
        DocumentSegment(
            document_id=document_id,
            extraction_run_id=run.id,
            ordinal=segment.ordinal,
            locator=sanitize_json(segment.locator.model_dump(mode="json", exclude_none=True)),
            text=sanitize_text(segment.text) or "",
            cells=sanitize_json(segment.cells),
            scanned=segment.scanned,
        )
        for segment in extracted.segments
    ]
    facts = [
        ExtractedFact(
            document_id=document_id,
            extraction_run_id=run.id,
            key=sanitize_text(fact.key) or "unknown",
            label=sanitize_text(fact.label) or "Unlabelled fact",
            category=fact.category,
            metric=fact.metric,
            series=sanitize_text(fact.series),
            value_text=sanitize_text(fact.value_text) or "",
            value_number=fact.value_number,
            unit=sanitize_text(fact.unit),
            period_start=_as_date(fact.period_start),
            period_end=_as_date(fact.period_end),
            note=sanitize_text(fact.note),
            origin=fact.origin,
            locator=sanitize_json(fact.locator.model_dump(mode="json", exclude_none=True)),
            quote=sanitize_text(fact.quote),
            verified=fact.verified,
            verification=sanitize_text(fact.verification) or "",
            derivation=sanitize_text(fact.derivation),
        )
        for fact in extracted.facts
    ]
    session.add_all([*segments, *facts])
