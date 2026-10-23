from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models import ExtractedRecord, ExtractionRun, SourceEvidence
from services.fact_extraction import ExtractedDocument
from services.text_sanitization import sanitize_json, sanitize_text


async def persist_extracted_facts(
    session: AsyncSession,
    document_id: UUID,
    run: ExtractionRun,
    document_kind: str,
    extracted: ExtractedDocument,
) -> None:
    evidence_rows = [
        SourceEvidence(
            id=uuid4(),
            document_id=document_id,
            extraction_run_id=run.id,
            evidence_kind=evidence.evidence_kind,
            page_number=evidence.page_number,
            printed_page_label=sanitize_text(evidence.printed_page_label),
            sheet_name=sanitize_text(evidence.sheet_name),
            cell_reference=sanitize_text(evidence.cell_reference),
            range_reference=sanitize_text(evidence.range_reference),
            quote=sanitize_text(evidence.quote),
            bounding_box=sanitize_json(evidence.bounding_box),
            source_metadata=sanitize_json(evidence.source_metadata),
        )
        for evidence in extracted.source_evidence
    ]
    fact_rows: list[ExtractedRecord] = []
    for fact in extracted.facts:
        evidence = SourceEvidence(
            id=uuid4(),
            document_id=document_id,
            extraction_run_id=run.id,
            evidence_kind=fact.evidence.evidence_kind,
            page_number=fact.evidence.page_number,
            printed_page_label=sanitize_text(fact.evidence.printed_page_label),
            sheet_name=sanitize_text(fact.evidence.sheet_name),
            cell_reference=sanitize_text(fact.evidence.cell_reference),
            range_reference=sanitize_text(fact.evidence.range_reference),
            quote=sanitize_text(fact.evidence.quote),
            bounding_box=sanitize_json(fact.evidence.bounding_box),
            source_metadata=sanitize_json(fact.evidence.source_metadata),
        )
        evidence_rows.append(evidence)
        fact_rows.append(
            ExtractedRecord(
                id=fact.id,
                document_id=document_id,
                extraction_run_id=run.id,
                source_evidence_id=evidence.id,
                document_type=sanitize_text(document_kind) or "unknown",
                fact_kind=fact.fact_kind,
                metric_name=sanitize_text(fact.metric_name) or "unknown",
                metric_value=fact.metric_value,
                raw_value=sanitize_text(fact.raw_value),
                value_text=sanitize_text(fact.value_text),
                value_date=fact.value_date,
                unit=sanitize_text(fact.unit),
                currency_code=sanitize_text(fact.currency_code),
                value_origin=fact.value_origin,
                aggregation_role=fact.aggregation_role,
                billing_period_start=(
                    fact.period_start.isoformat() if fact.period_start else None
                ),
                billing_period_end=(
                    fact.period_end.isoformat() if fact.period_end else None
                ),
                period_start=fact.period_start,
                period_end=fact.period_end,
                period_grain=fact.period_grain,
                financial_year=sanitize_text(fact.financial_year),
                financial_year_start_year=fact.financial_year_start_year,
                description=sanitize_text(fact.description),
                dimensions=sanitize_json(fact.dimensions),
                confidence=fact.confidence,
                calculation_method=sanitize_text(fact.calculation_method),
                derived_from=[str(value) for value in fact.derived_from],
                source_reference=(
                    sanitize_text(fact.source_reference) or "Source unavailable"
                )[:255],
            )
        )

    # The fact rows contain FKs to these evidence rows, so persist the parent rows
    # first instead of relying on ORM mapper ordering between unrelated instances.
    session.add_all(evidence_rows)
    await session.flush()
    session.add_all(fact_rows)
