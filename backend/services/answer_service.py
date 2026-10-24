"""Generate, ground, and persist answers over a user's processed documents."""

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AnswerRecord, Document, DocumentSegment, ExtractedFact, ExtractionRun
from prompts.answer import ANSWER_INSTRUCTIONS
from schemas.answers import (
    AnswerCalculation,
    AnswerContent,
    AnswerDraft,
    AnswerEvidence,
    AnswerKeyValue,
    AnswerKeyValueDraft,
    AnswerRecordResponse,
    AnswerStatus,
)
from schemas.extraction import Locator, Segment
from services.answer_calculations import (
    CalculationError,
    calculation_matches,
    decimal_text,
    evaluate_expression,
)
from services.source_verification import expand_cell_range, verify_fact_source

logger = logging.getLogger(__name__)

_DEFAULT_ANSWER_MODEL = "gemini-3.5-flash-lite"
_ANSWER_CONTEXT_CHAR_BUDGET = 220_000
_SOURCE_PREVIEW_MAX_CHARS = 1800
_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CITATION = re.compile(r"\[(E[1-9][0-9]{0,2})\]")
_CELL_REF = re.compile(r"^([A-Z]{1,3})(\d+)$", re.IGNORECASE)


class AnswerRequestError(ValueError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class AnswerGenerationError(RuntimeError):
    """An answer model call failed or did not return the required structure."""


class AnswerModelNotConfigured(AnswerGenerationError):
    pass


@dataclass
class AnswerDocument:
    id: UUID
    filename: str
    doc_type: str
    organisation: str | None
    summary: str | None
    period_start: str | None
    period_end: str | None
    issues: list[str]
    facts: list[dict]
    segments: list[Segment]


async def create_answer(
    session: AsyncSession,
    user_id: int,
    question: str,
    requested_document_ids: list[UUID],
) -> AnswerRecordResponse:
    selected_ids, content, answer_status = await generate_answer_for_user(
        session, user_id, question, requested_document_ids
    )

    row = AnswerRecord(
        user_id=user_id,
        question=question,
        document_ids=selected_ids,
        status=answer_status,
        response=content.model_dump(mode="json"),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _answer_record_response(row)


async def generate_answer_for_user(
    session: AsyncSession,
    user_id: int,
    question: str,
    requested_document_ids: list[UUID],
) -> tuple[list[UUID], AnswerContent, AnswerStatus]:
    """Run the production answer path without adding a user-visible history row."""
    documents = await load_answer_documents_for_user(
        session, user_id, requested_document_ids
    )
    selected_ids = [document.id for document in documents]
    model_name = answer_model_name()
    if documents:
        content, answer_status = await generate_answer_for_documents(question, documents)
    else:
        answer_status = "insufficient_evidence"
        content = AnswerContent(
            answer=(
                "No successfully processed documents are in scope, so I cannot "
                "answer from your sources."
            ),
            key_values=[],
            calculations=[],
            evidence=[],
            gaps=["Select at least one successfully processed document."],
            model=model_name,
        )
    return selected_ids, content, answer_status


async def load_answer_documents_for_user(
    session: AsyncSession,
    user_id: int,
    requested_document_ids: list[UUID],
) -> list[AnswerDocument]:
    documents = await _load_answer_documents(
        session,
        user_id,
        requested_document_ids,
    )
    # End the read transaction before waiting on the remote Gemini request.
    await session.commit()
    return documents


async def generate_answer_for_documents(
    question: str, documents: list[AnswerDocument]
) -> tuple[AnswerContent, AnswerStatus]:
    content, status = await generate_answer(question, documents)
    return content, _content_status(content, status)


async def list_user_answers(
    session: AsyncSession, user_id: int, limit: int = 20
) -> list[AnswerRecordResponse]:
    result = await session.execute(
        select(AnswerRecord)
        .where(AnswerRecord.user_id == user_id)
        .order_by(AnswerRecord.created_at.desc())
        .limit(limit)
    )
    return [_answer_record_response(row) for row in result.scalars().all()]


def answer_model_name() -> str:
    return os.getenv("ANSWER_MODEL", "").strip() or _DEFAULT_ANSWER_MODEL


def gemini_answer_schema() -> dict:
    """A flat, Gemini-compatible response schema without unions or references."""
    string = {"type": "string"}
    string_list = {"type": "array", "items": string}

    def object_schema(properties: dict, required: list[str]) -> dict:
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    key_value = object_schema(
        {
            "label": string,
            "value": string,
            "value_text": string,
            "unit": string,
            "period": string,
            "origin": {"type": "string", "enum": ["reported", "calculated"]},
            "evidence_ids": string_list,
            "calculation_id": string,
        },
        [
            "label",
            "value",
            "value_text",
            "unit",
            "period",
            "origin",
            "evidence_ids",
            "calculation_id",
        ],
    )
    calculation = object_schema(
        {
            "id": string,
            "description": string,
            "expression": string,
            "result": string,
            "unit": string,
            "evidence_ids": string_list,
        },
        ["id", "description", "expression", "result", "unit", "evidence_ids"],
    )
    evidence = object_schema(
        {
            "id": string,
            "document_id": string,
            # Use page=0 for spreadsheets; the server normalizes it to None.
            "page": {"type": "integer"},
            "sheet": string,
            "cell_range": string,
            "quote": string,
        },
        ["id", "document_id", "page", "sheet", "cell_range", "quote"],
    )
    return object_schema(
        {
            "status": {
                "type": "string",
                "enum": [
                    "answered",
                    "partial",
                    "insufficient_evidence",
                    "conflicting_evidence",
                ],
            },
            "answer": string,
            "key_values": {"type": "array", "items": key_value},
            "calculations": {"type": "array", "items": calculation},
            "evidence": {"type": "array", "items": evidence},
            "gaps": string_list,
        },
        ["status", "answer", "key_values", "calculations", "evidence", "gaps"],
    )


def _answer_draft_from_gemini(value: object) -> AnswerDraft:
    if isinstance(value, AnswerDraft):
        return value
    if not isinstance(value, dict):
        raise ValueError("Gemini returned an invalid answer object")

    payload = dict(value)
    evidence_aliases: dict[str, str] = {}
    for index, raw_item in enumerate(payload.get("evidence") or [], start=1):
        item = dict(raw_item)
        raw_id = str(item.get("id", ""))
        normalized_id = f"E{index}"
        if raw_id:
            evidence_aliases[raw_id.casefold()] = normalized_id
        item["id"] = normalized_id
        payload.setdefault("evidence", [])[index - 1] = item

    calculation_aliases: dict[str, str] = {}
    for index, raw_item in enumerate(payload.get("calculations") or [], start=1):
        item = dict(raw_item)
        raw_id = str(item.get("id", ""))
        normalized_id = f"C{index}"
        if raw_id:
            calculation_aliases[raw_id.casefold()] = normalized_id
        item["id"] = normalized_id
        payload.setdefault("calculations", [])[index - 1] = item

    def normalize_reference(reference: object, aliases: dict[str, str], prefix: str, count: int) -> str:
        raw_reference = str(reference)
        if raw_reference.casefold() in aliases:
            return aliases[raw_reference.casefold()]
        match = re.fullmatch(rf"{prefix}(\d+)", raw_reference, re.IGNORECASE)
        if match and 1 <= int(match[1]) <= count:
            return f"{prefix}{int(match[1])}"
        return raw_reference

    evidence_count = len(payload.get("evidence") or [])
    calculation_count = len(payload.get("calculations") or [])
    payload["answer"] = re.sub(
        r"\[([^\]\s]+)\]",
        lambda match: "["
        + normalize_reference(match[1], evidence_aliases, "E", evidence_count)
        + "]",
        str(payload.get("answer", "")),
    )

    key_values = []
    for raw_item in payload.get("key_values") or []:
        item = dict(raw_item)
        item["value"] = item.get("value") or None
        item["unit"] = item.get("unit") or None
        item["period"] = item.get("period") or None
        calculation_id = item.get("calculation_id")
        item["calculation_id"] = (
            normalize_reference(calculation_id, calculation_aliases, "C", calculation_count)
            if calculation_id
            else None
        )
        item["evidence_ids"] = [
            normalize_reference(reference, evidence_aliases, "E", evidence_count)
            for reference in item.get("evidence_ids", [])
        ]
        key_values.append(item)
    calculations = []
    for raw_item in payload.get("calculations") or []:
        item = dict(raw_item)
        item["unit"] = item.get("unit") or None
        item["evidence_ids"] = [
            normalize_reference(reference, evidence_aliases, "E", evidence_count)
            for reference in item.get("evidence_ids", [])
        ]
        calculations.append(item)
    evidence = []
    for raw_item in payload.get("evidence") or []:
        item = dict(raw_item)
        item["page"] = item.get("page") or None
        item["sheet"] = item.get("sheet") or None
        item["cell_range"] = item.get("cell_range") or None
        evidence.append(item)
    payload["key_values"] = key_values
    payload["calculations"] = calculations
    payload["evidence"] = evidence
    return AnswerDraft.model_validate(payload)


async def _load_answer_documents(
    session: AsyncSession,
    user_id: int,
    requested_document_ids: list[UUID],
) -> list[AnswerDocument]:
    if requested_document_ids:
        result = await session.execute(
            select(Document).where(
                Document.user_id == user_id,
                Document.id.in_(requested_document_ids),
            ).order_by(Document.upload_timestamp)
        )
        owned_documents = result.scalars().all()
        if len(owned_documents) != len(requested_document_ids):
            raise AnswerRequestError(
                "One or more selected documents were not found.", 404
            )
        not_ready = [document for document in owned_documents if document.status != "success"]
        if not_ready:
            raise AnswerRequestError(
                "All selected documents must be successfully processed.", 409
            )
        documents = owned_documents
    else:
        result = await session.execute(
            select(Document)
            .where(Document.user_id == user_id, Document.status == "success")
            .order_by(Document.upload_timestamp)
        )
        documents = result.scalars().all()

    if not documents:
        return []

    document_by_id = {document.id: document for document in documents}
    run_query = (
        select(ExtractionRun)
        .where(
            ExtractionRun.document_id.in_(document_by_id),
            ExtractionRun.status == "succeeded",
        )
        .order_by(
            ExtractionRun.document_id,
            ExtractionRun.attempt_number.desc(),
            ExtractionRun.completed_at.desc(),
        )
    )
    run_result = await session.execute(run_query)
    latest_runs: dict[UUID, ExtractionRun] = {}
    for run in run_result.scalars().all():
        latest_runs.setdefault(run.document_id, run)

    missing_runs = set(document_by_id) - set(latest_runs)
    if missing_runs:
        raise AnswerRequestError(
            "A selected document has no completed extraction to search.", 409
        )

    run_ids = [run.id for run in latest_runs.values()]
    facts_result = await session.execute(
        select(ExtractedFact)
        .where(ExtractedFact.extraction_run_id.in_(run_ids))
        .order_by(ExtractedFact.created_at, ExtractedFact.key)
    )
    segments_result = await session.execute(
        select(DocumentSegment)
        .where(DocumentSegment.extraction_run_id.in_(run_ids))
        .order_by(DocumentSegment.document_id, DocumentSegment.ordinal)
    )

    facts_by_run: dict[UUID, list[dict]] = {run_id: [] for run_id in run_ids}
    for fact in facts_result.scalars().all():
        facts_by_run[fact.extraction_run_id].append(_fact_for_context(fact))

    segments_by_run: dict[UUID, list[Segment]] = {run_id: [] for run_id in run_ids}
    for segment in segments_result.scalars().all():
        segments_by_run[segment.extraction_run_id].append(
            Segment.model_validate(
                {
                    "ordinal": segment.ordinal,
                    "locator": segment.locator,
                    "text": segment.text,
                    "cells": segment.cells,
                    "scanned": segment.scanned,
                }
            )
        )

    answer_documents: list[AnswerDocument] = []
    for document in documents:
        run = latest_runs[document.id]
        metadata = run.result_metadata or {}
        extraction_issues = metadata.get("issues")
        answer_documents.append(
            AnswerDocument(
                id=document.id,
                filename=document.filename,
                doc_type=document.document_kind,
                organisation=document.entity_name,
                summary=metadata.get("summary"),
                period_start=_date_text(metadata.get("period_start")),
                period_end=_date_text(metadata.get("period_end")),
                issues=(
                    [str(issue) for issue in extraction_issues]
                    if isinstance(extraction_issues, list)
                    else []
                ),
                facts=facts_by_run[run.id],
                segments=segments_by_run[run.id],
            )
        )
    return answer_documents


def _date_text(value: object) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value
    return None


def _fact_for_context(fact: ExtractedFact) -> dict:
    has_review = (
        fact.reviewed_label is not None or fact.reviewed_value_text is not None
    )
    value_text = (
        fact.reviewed_value_text
        if fact.reviewed_value_text is not None
        else fact.value_text
    )
    value_number = (
        fact.reviewed_value_number
        if fact.reviewed_value_text is not None
        else fact.value_number
    )
    return {
        "key": fact.key,
        "label": fact.reviewed_label or fact.label,
        "category": fact.category,
        "metric": fact.metric,
        "series": fact.series,
        "value_text": value_text,
        "value_number": (
            format(value_number, "f") if value_number is not None else None
        ),
        "unit": fact.unit,
        "period_start": _date_text(fact.period_start),
        "period_end": _date_text(fact.period_end),
        "note": fact.note,
        "origin": fact.origin,
        "locator": fact.locator,
        "quote": fact.quote,
        "verified": (
            fact.reviewed_verified
            if has_review and fact.reviewed_verified is not None
            else fact.verified
        ),
        "verification": (
            fact.reviewed_verification or fact.verification
            if has_review
            else fact.verification
        ),
        "derivation": fact.derivation,
    }


def _keywords(value: str) -> set[str]:
    return {word for word in _WORD.findall(value.casefold()) if len(word) > 2}


def _selected_segments(
    question: str, documents: list[AnswerDocument]
) -> dict[UUID, list[Segment]]:
    all_segments = [
        (document, segment)
        for document in documents
        for segment in document.segments
    ]
    total_chars = sum(
        len(segment.text) + len(json.dumps(segment.cells or {}, ensure_ascii=False))
        for _, segment in all_segments
    )
    if total_chars <= _ANSWER_CONTEXT_CHAR_BUDGET:
        return {
            document.id: list(document.segments) for document in documents
        }

    terms = _keywords(question)
    ranked = sorted(
        all_segments,
        key=lambda pair: len(
            terms
            & _keywords(
                pair[1].text
                + " "
                + " ".join(f"{key} {value}" for key, value in (pair[1].cells or {}).items())
            )
        ),
        reverse=True,
    )
    selected: dict[UUID, list[Segment]] = {document.id: [] for document in documents}
    selected_keys: set[tuple[UUID, int]] = set()
    used = 0

    def size(segment: Segment) -> int:
        return len(segment.text) + len(
            json.dumps(segment.cells or {}, ensure_ascii=False)
        )

    # Keep at least the most relevant segment for each selected document.
    for document in documents:
        first = next((pair for pair in ranked if pair[0].id == document.id), None)
        if first and size(first[1]) <= _ANSWER_CONTEXT_CHAR_BUDGET:
            selected[document.id].append(first[1])
            selected_keys.add((document.id, first[1].ordinal))
            used += size(first[1])

    for document, segment in ranked:
        key = (document.id, segment.ordinal)
        if key in selected_keys:
            continue
        if used + size(segment) > _ANSWER_CONTEXT_CHAR_BUDGET:
            continue
        selected[document.id].append(segment)
        selected_keys.add(key)
        used += size(segment)

    for document_id in selected:
        selected[document_id].sort(key=lambda segment: segment.ordinal)
    return selected


def _build_context(question: str, documents: list[AnswerDocument]) -> str:
    segments_by_document = _selected_segments(question, documents)
    payload = {
        "question": question,
        "documents": [
            {
                "id": str(document.id),
                "filename": document.filename,
                "document_kind": document.doc_type,
                "organisation": document.organisation,
                "period_start": document.period_start,
                "period_end": document.period_end,
                "summary": document.summary,
                "issues_noted_during_extraction": document.issues,
                "facts": document.facts,
                "source_segments": [
                    {
                        "ordinal": segment.ordinal,
                        "locator": segment.locator.model_dump(
                            mode="json", exclude_none=True
                        ),
                        "text": segment.text,
                        "cells": segment.cells,
                        "scanned": segment.scanned,
                    }
                    for segment in segments_by_document[document.id]
                ],
            }
            for document in documents
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


async def generate_answer(
    question: str, documents: list[AnswerDocument]
) -> tuple[AnswerContent, AnswerStatus]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise AnswerModelNotConfigured(
            "Set GEMINI_API_KEY to enable document answers."
        )

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    model_name = answer_model_name()
    context = _build_context(question, documents)
    try:
        model = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            max_output_tokens=12_000,
        ).with_structured_output(
            gemini_answer_schema(),
            method="json_schema",
            include_raw=True,
        )
        result = await model.ainvoke(
            [
                SystemMessage(content=ANSWER_INSTRUCTIONS),
                HumanMessage(content=context),
            ]
        )
        if isinstance(result, dict) and "parsed" in result:
            if result.get("parsing_error") is not None:
                raise ValueError("Gemini returned invalid structured answer output")
            draft = _answer_draft_from_gemini(result.get("parsed"))
        else:
            draft = _answer_draft_from_gemini(result)
        return _validate_draft(draft, documents, model_name)
    except AnswerGenerationError:
        raise
    except Exception as error:
        logger.warning(
            "Answer generation failed (%s): %s",
            type(error).__name__,
            str(error)[:600],
        )
        raise AnswerGenerationError(
            "The answer could not be generated. Please try again."
        ) from error


def _validate_draft(
    draft: AnswerDraft,
    documents: list[AnswerDocument],
    model_name: str,
) -> tuple[AnswerContent, AnswerStatus]:
    documents_by_id = {document.id: document for document in documents}
    verified_evidence: list[AnswerEvidence] = []
    evidence_by_id: dict[str, AnswerEvidence] = {}
    gaps = list(draft.gaps)
    missing_support = False

    for candidate in draft.evidence:
        if candidate.id in evidence_by_id:
            missing_support = True
            gaps.append(
                f"Repeated citation id {candidate.id} was ignored; check the source references."
            )
            continue
        document = documents_by_id.get(candidate.document_id)
        locator = Locator(
            page=candidate.page,
            sheet=candidate.sheet,
            cell_range=candidate.cell_range,
        )
        if document is None:
            is_verified, reason = False, "Cites a document outside the selected scope"
            preview = ""
        else:
            is_verified, reason = verify_fact_source(
                document.segments,
                locator,
                candidate.quote,
                structured=True,
            )
            preview = _source_preview(document, locator, candidate.quote)
        evidence = AnswerEvidence(
            id=candidate.id,
            document_id=candidate.document_id,
            filename=document.filename if document else "Unknown document",
            locator=locator,
            locator_label=locator.label(),
            quote=candidate.quote,
            source_preview=preview,
            verified=is_verified,
            verification=reason,
        )
        evidence_by_id[evidence.id] = evidence
        verified_evidence.append(evidence)

    known_ids = set(evidence_by_id)
    referenced_ids = set(_CITATION.findall(draft.answer))
    missing_support = missing_support or (
        not bool(_CITATION.search(draft.answer))
        and draft.status != "insufficient_evidence"
    )
    if missing_support:
        gaps.append("The answer narrative did not include an inline source citation.")
    for key_value in draft.key_values:
        referenced_ids.update(key_value.evidence_ids)
        if not key_value.evidence_ids:
            missing_support = True
            gaps.append(f"{key_value.label} has no linked source evidence.")
        if key_value.calculation_id and key_value.calculation_id not in {
            calculation.id for calculation in draft.calculations
        }:
            missing_support = True
            gaps.append(
                f"{key_value.label} references a calculation that was not returned."
            )
    for calculation in draft.calculations:
        referenced_ids.update(calculation.evidence_ids)
        if not calculation.evidence_ids:
            missing_support = True
            gaps.append(f"Calculation {calculation.id} has no linked source evidence.")

    unknown_ids = referenced_ids - known_ids
    if unknown_ids:
        gaps.append(
            "Some answer references had no matching source: "
            + ", ".join(sorted(unknown_ids))
            + "."
        )
    unverified_used = sorted(
        evidence_id
        for evidence_id in referenced_ids & known_ids
        if not evidence_by_id[evidence_id].verified
    )
    if unverified_used:
        gaps.append(
            "These cited source locations could not be confirmed: "
            + ", ".join(unverified_used)
            + "."
        )
    unverified_evidence = [
        evidence.id for evidence in verified_evidence if not evidence.verified
    ]
    if unverified_evidence and not unverified_used:
        gaps.append(
            "Some listed source locations could not be confirmed: "
            + ", ".join(sorted(unverified_evidence))
            + "."
        )

    calculations: list[AnswerCalculation] = []
    for item in draft.calculations:
        stated = Decimal(item.result)
        try:
            computed = evaluate_expression(
                item.expression,
                [segment for document in documents for segment in document.segments],
            )
            matches = calculation_matches(computed, stated)
            verification = (
                "Recomputed from selected source values and matches."
                if matches
                else f"Recomputed as {decimal_text(computed)}, which differs from the stated result."
            )
        except CalculationError as error:
            computed = None
            matches = False
            verification = str(error)
        if not matches:
            gaps.append(f"Calculation {item.id} could not be confirmed: {verification}")
        calculations.append(
            AnswerCalculation(
                id=item.id,
                description=item.description,
                expression=item.expression,
                result=decimal_text(stated),
                computed=decimal_text(computed) if computed is not None else None,
                matches=matches,
                unit=item.unit,
                evidence_ids=item.evidence_ids,
                verification=verification,
            )
        )

    calculations_by_id = {calculation.id: calculation for calculation in calculations}
    key_values: list[AnswerKeyValue] = []
    for item in draft.key_values:
        is_verified, verification = _verify_key_value(
            item,
            documents_by_id,
            evidence_by_id,
            calculations_by_id,
        )
        if not is_verified:
            missing_support = True
            gaps.append(f"Key figure {item.label} could not be confirmed: {verification}")
        key_values.append(
            AnswerKeyValue(
                label=item.label,
                value=item.value,
                value_text=item.value_text,
                unit=item.unit,
                period=item.period,
                origin=item.origin,
                evidence_ids=item.evidence_ids,
                calculation_id=item.calculation_id,
                verified=is_verified,
                verification=verification,
            )
        )

    status = draft.status
    has_unverified_calculation = any(not calculation.matches for calculation in calculations)
    if status == "answered" and (
        missing_support
        or unknown_ids
        or unverified_used
        or unverified_evidence
        or has_unverified_calculation
    ):
        status = "partial"
    if status in ("answered", "partial") and not verified_evidence:
        status = "insufficient_evidence"
        if "The answer did not include a source location that could be checked." not in gaps:
            gaps.append("The answer did not include a source location that could be checked.")

    content = AnswerContent(
        answer=draft.answer,
        key_values=key_values,
        calculations=calculations,
        evidence=verified_evidence,
        gaps=list(dict.fromkeys(gaps)),
        model=model_name,
    )
    return content, status


def _content_status(content: AnswerContent, status: AnswerStatus) -> AnswerStatus:
    """Keep the status conservative when saved calculations are not reproducible."""
    if status == "answered" and any(not calculation.matches for calculation in content.calculations):
        return "partial"
    return status


def _verify_key_value(
    item: AnswerKeyValueDraft,
    documents: dict[UUID, AnswerDocument],
    evidence_by_id: dict[str, AnswerEvidence],
    calculations_by_id: dict[str, AnswerCalculation],
) -> tuple[bool, str]:
    cited = [evidence_by_id[evidence_id] for evidence_id in item.evidence_ids if evidence_id in evidence_by_id]
    confirmed_sources = [evidence for evidence in cited if evidence.verified]
    if not confirmed_sources:
        return False, "No cited source location was confirmed."

    if item.origin == "calculated":
        calculation = calculations_by_id.get(item.calculation_id or "")
        if calculation is None:
            return False, "No matching checked calculation was returned."
        if not calculation.matches or calculation.computed is None:
            return False, f"Calculation {calculation.id} did not reproduce its stated result."
        if item.value is None:
            return False, "The calculated figure has no numeric value to compare."
        if not set(item.evidence_ids).intersection(calculation.evidence_ids):
            return False, "The key figure and calculation do not cite the same evidence."
        if not calculation_matches(Decimal(calculation.computed), Decimal(item.value)):
            return False, "The key figure differs from the independently recomputed result."
        return True, f"Matches checked calculation {calculation.id}."

    expected = Decimal(item.value) if item.value is not None else None
    for evidence in confirmed_sources:
        document = documents.get(evidence.document_id)
        if document is None:
            continue
        is_supported, reason = verify_fact_source(
            document.segments,
            evidence.locator,
            evidence.quote,
            expected,
            structured=True,
        )
        if is_supported:
            return True, f"Supported by {evidence.id}: {reason}"
    return False, "The cited quote does not establish this reported value."


def _source_preview(
    document: AnswerDocument, locator: Locator, quote: str
) -> str:
    matching_segments = [
        segment
        for segment in document.segments
        if (locator.page is not None and segment.locator.page == locator.page)
        or (
            locator.sheet is not None
            and segment.locator.sheet == locator.sheet
            and (
                locator.cell_range is None
                or bool(
                    set(expand_cell_range(locator.cell_range))
                    & set(segment.cells or {})
                )
            )
        )
    ]
    if not matching_segments:
        return "Source preview is unavailable."

    segment = matching_segments[0]
    if segment.scanned and not segment.text.strip():
        return "Text is unavailable for this scanned page."

    if locator.sheet and segment.cells and locator.cell_range:
        references = expand_cell_range(locator.cell_range)
        if references and len(references) <= 250:
            requested_rows = {
                match.group(2)
                for reference in references
                if (match := _CELL_REF.fullmatch(reference))
            }
            row_references = [
                reference
                for reference in segment.cells
                if (match := _CELL_REF.fullmatch(reference))
                and match.group(2) in requested_rows
            ]
            row_references.sort(key=_cell_sort_key)
            lines = [
                f"{reference}={segment.cells[reference]}"
                for reference in row_references[:60]
            ]
            if lines:
                return "\n".join(lines)[:_SOURCE_PREVIEW_MAX_CHARS]

    source_text = segment.text.strip()
    folded_source = source_text.casefold()
    start = folded_source.find(quote.casefold()) if quote else -1
    if start >= 0:
        start = max(0, start - 400)
        end = min(len(source_text), start + _SOURCE_PREVIEW_MAX_CHARS)
        return source_text[start:end]
    return source_text[:_SOURCE_PREVIEW_MAX_CHARS]


def _cell_sort_key(reference: str) -> tuple[int, int]:
    match = _CELL_REF.fullmatch(reference)
    if not match:
        return (0, 0)
    from openpyxl.utils import column_index_from_string

    return int(match.group(2)), column_index_from_string(match.group(1).upper())


def _answer_record_response(row: AnswerRecord) -> AnswerRecordResponse:
    return AnswerRecordResponse(
        id=row.id,
        question=row.question,
        document_ids=row.document_ids,
        status=row.status,
        answer=AnswerContent.model_validate(row.response),
        created_at=row.created_at,
    )
