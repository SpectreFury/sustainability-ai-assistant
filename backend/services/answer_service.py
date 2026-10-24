"""Generate, ground, and persist answers over a user's processed documents."""

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from fastapi import HTTPException
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
    AnswerToolCallDraft,
)
from schemas.extraction import Locator, Segment
from services.answer_calculations import (
    CalculationError,
    blank_cells_in_expression,
    calculation_matches,
    decimal_text,
    evaluate_expression,
)
from services.llm_observability import (
    capture_content_enabled,
    langfuse_observation,
    update_observation,
)
from services.financial_year_service import (
    get_financial_year_summary,
    summarize_answer_context,
)
from services.source_verification import expand_cell_range, verify_fact_source

logger = logging.getLogger(__name__)

_DEFAULT_ANSWER_MODEL = "gemini-3.5-flash-lite"
_ANSWER_PROMPT_HASH = hashlib.sha256(ANSWER_INSTRUCTIONS.encode("utf-8")).hexdigest()
_ANSWER_CONTEXT_CHAR_BUDGET = 220_000
_MAX_ANSWER_TOOL_ROUNDS = 6
_MAX_ANSWER_TOOL_CALLS = 12
_MAX_FY_TOOL_SOURCES_PER_ORGANISATION = 100
_SOURCE_PREVIEW_MAX_CHARS = 1800
_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_CITATION = re.compile(r"\[(E[1-9][0-9]{0,2})\]")
_CALCULATION_CITATION = re.compile(r"\[(C[1-9][0-9]{0,2})\]")
_CELL_REF = re.compile(r"^([A-Z]{1,3})(\d+)$", re.IGNORECASE)
_SHEET_REFERENCE_IN_EXPRESSION = re.compile(
    r"(?:'([^']+)'|([A-Za-z_][\w .&()-]*?))!\s*\$?[A-Z]{1,3}\$?\d+",
    re.IGNORECASE,
)
_FY_PAIR_IN_QUESTION = re.compile(
    r"\b(?:FY|financial\s+year|fiscal\s+year)\s*['’]?\s*(?:of\s*)?"
    r"(\d{2}|\d{4})\s*[-–—/]\s*(\d{2}|\d{4})\b",
    re.IGNORECASE,
)
_FY_END_YEAR_IN_QUESTION = re.compile(
    r"\bFY\s*['’]?\s*((?:19|20)\d{2})\b", re.IGNORECASE
)


class AnswerRequestError(ValueError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = status_code in {408, 425, 429} or status_code >= 500


class AnswerGenerationError(RuntimeError):
    """An answer model call failed or did not return the required structure."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        cause_type: str | None = None,
        status_code: int | None = None,
        diagnostic: str | None = None,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.cause_type = cause_type
        self.status_code = status_code
        self.diagnostic = diagnostic


class AnswerModelNotConfigured(AnswerGenerationError):
    pass


_RETRYABLE_ANSWER_ERRORS = {
    "ConnectionError",
    "ConnectTimeout",
    "DeadlineExceeded",
    "InternalServerError",
    "JSONDecodeError",
    "OutputParserException",
    "ReadTimeout",
    "ResourceExhausted",
    "ServiceUnavailable",
    "Timeout",
    "TimeoutError",
    "Unavailable",
    "ValidationError",
    "ValueError",
}


def _answer_error_details(error: Exception) -> tuple[bool, str, int | None]:
    """Classify transient provider/structured-output errors without logging payloads."""
    current: BaseException | None = error
    seen: set[int] = set()
    error_types: list[str] = []
    retry_markers: list[str] = []
    status_code: int | None = None
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        error_types.append(type(current).__name__)
        retry_markers.append(type(current).__name__)
        for candidate in (
            getattr(current, "status_code", None),
            getattr(current, "http_status", None),
        ):
            if isinstance(candidate, int):
                status_code = candidate
                break
        response = getattr(current, "response", None)
        response_status = getattr(response, "status_code", None)
        if status_code is None and isinstance(response_status, int):
            status_code = response_status
        code = getattr(current, "code", None)
        if callable(code):
            try:
                code = code()
            except Exception:
                code = None
        if code is not None:
            retry_markers.append(str(code).rsplit(".", 1)[-1])
        current = current.__cause__ or current.__context__

    retryable_status = status_code in {408, 425, 429, 500, 502, 503, 504}
    retryable_names = {
        re.sub(r"[^a-z0-9]", "", name.casefold())
        for name in _RETRYABLE_ANSWER_ERRORS
    }
    retryable_name = any(
        re.sub(r"[^a-z0-9]", "", name.casefold()) in retryable_names
        for name in retry_markers
    )
    return retryable_status or retryable_name, error_types[-1], status_code


def _safe_answer_error_diagnostic(error: BaseException) -> str:
    """Return schema-path diagnostics without including provider/model payloads."""
    current: BaseException | None = error
    seen: set[int] = set()
    paths: list[str] = []
    finish_reason: str | None = None
    error_types: list[str] = []
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        error_types.append(type(current).__name__)
        raw_finish_reason = getattr(current, "finish_reason", None)
        if isinstance(raw_finish_reason, str) and re.fullmatch(
            r"[A-Z0-9_]{1,40}", raw_finish_reason
        ):
            finish_reason = raw_finish_reason
        errors_method = getattr(current, "errors", None)
        if callable(errors_method):
            try:
                details = errors_method(
                    include_input=False,
                    include_context=False,
                    include_url=False,
                )
            except TypeError:
                try:
                    details = errors_method()
                except Exception:
                    details = []
            except Exception:
                details = []
            if isinstance(details, list):
                for detail in details[:12]:
                    if not isinstance(detail, dict):
                        continue
                    location = detail.get("loc")
                    error_type = detail.get("type")
                    if isinstance(location, (tuple, list)):
                        path = ".".join(
                            re.sub(r"[^A-Za-z0-9_-]", "", str(part))
                            for part in location
                        )
                    else:
                        path = "structured_output"
                    kind = (
                        re.sub(r"[^A-Za-z0-9_-]", "", error_type)
                        if isinstance(error_type, str)
                        else "invalid"
                    )
                    paths.append(f"{path or 'structured_output'}:{kind or 'invalid'}")
        current = current.__cause__ or current.__context__
    if paths:
        detail = ", ".join(dict.fromkeys(paths))
    else:
        detail = "cause_chain=" + ">".join(error_types[:5])
    if finish_reason:
        detail += f"; finish_reason={finish_reason}"
    return detail[:1000]


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
    upload_timestamp: datetime | None = None
    extraction_run_id: UUID | None = None


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
    documents = await load_answer_documents_for_user(
        session, user_id, requested_document_ids
    )
    named_documents, explicitly_named = _documents_named_in_question(
        question, documents
    )
    if explicitly_named:
        documents = named_documents
    selected_ids = [document.id for document in documents]
    model_name = answer_model_name()
    if documents:
        initial_tool_results = await _precompute_fy_tool_results(
            session,
            user_id,
            question,
            documents,
        )
        # Finish the database-backed FY read before waiting on Gemini.
        await session.commit()
        content, answer_status = await generate_answer_for_documents(
            question,
            documents,
            trace_context={"origin": "interactive"},
            initial_tool_results=initial_tool_results,
        )
    else:
        answer_status = "insufficient_evidence"
        content = AnswerContent(
            answer=(
                "The specifically named document is not available in the selected "
                "scope, so I cannot answer from it."
                if explicitly_named
                else "No successfully processed documents are in scope, so I cannot "
                "answer from your sources."
            ),
            key_values=[],
            calculations=[],
            evidence=[],
            gaps=[
                "The specifically named document is not available in the selected scope."
                if explicitly_named
                else "Select at least one successfully processed document."
            ],
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
    question: str,
    documents: list[AnswerDocument],
    trace_context: dict[str, str] | None = None,
    initial_tool_results: list[dict[str, Any]] | None = None,
) -> tuple[AnswerContent, AnswerStatus]:
    content, status = await generate_answer(
        question, documents, trace_context, initial_tool_results
    )
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
    return os.getenv("ANSWER_GENERATION_MODEL", "").strip() or _DEFAULT_ANSWER_MODEL


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
    claim = object_schema(
        {
            "text": string,
            "evidence_ids": string_list,
            "calculation_ids": string_list,
        },
        ["text", "evidence_ids", "calculation_ids"],
    )
    tool_call = object_schema(
        {
            "name": {
                "type": "string",
                "enum": ["calculate", "financial_year_totals"],
            },
            "expression": string,
            "financial_year": string,
            "metric": string,
            "document_id": string,
        },
        ["name", "expression", "financial_year", "metric", "document_id"],
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
            "claims": {"type": "array", "items": claim},
            "key_values": {"type": "array", "items": key_value},
            "calculations": {"type": "array", "items": calculation},
            "evidence": {"type": "array", "items": evidence},
            "gaps": string_list,
            "tool_calls": {"type": "array", "items": tool_call},
        },
        [
            "status",
            "claims",
            "key_values",
            "calculations",
            "evidence",
            "gaps",
            "tool_calls",
        ],
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
    legacy_answer = re.sub(
        r"\[([^\]\s]+)\]",
        lambda match: "["
        + normalize_reference(match[1], evidence_aliases, "E", evidence_count)
        + "]",
        str(payload.get("answer", "")),
    )

    claims: list[dict[str, object]] = []
    rendered_claims: list[str] = []
    for raw_claim in payload.get("claims") or []:
        item = dict(raw_claim)
        evidence_ids = list(
            dict.fromkeys(
                normalize_reference(reference, evidence_aliases, "E", evidence_count)
                for reference in item.get("evidence_ids", [])
            )
        )
        calculation_ids = list(
            dict.fromkeys(
                normalize_reference(reference, calculation_aliases, "C", calculation_count)
                for reference in item.get("calculation_ids", [])
            )
        )
        # Citation tokens are added from the structured ID lists below, never
        # trusted from free-form model prose.
        text = re.sub(r"\[(?:E|C)\d+\]", "", str(item.get("text", ""))).strip()
        references = [*evidence_ids, *calculation_ids]
        rendered_claims.append(
            f"{text} {' '.join(f'[{reference}]' for reference in references)}".strip()
        )
        claims.append(
            {
                "text": text,
                "evidence_ids": evidence_ids,
                "calculation_ids": calculation_ids,
            }
        )

    key_values = []
    for raw_item in payload.get("key_values") or []:
        item = dict(raw_item)
        raw_value = item.get("value")
        value_text = str(item.get("value_text") or "").strip()
        if raw_value is None or not str(raw_value).strip():
            item["value"] = None
        else:
            value_candidate = str(raw_value).strip()
            try:
                numeric_value = Decimal(value_candidate.replace(",", ""))
            except InvalidOperation:
                # Models sometimes put display text such as "No data" in the
                # numeric field. Keep that text for display and leave the
                # machine-readable numeric value empty instead of rejecting
                # the entire answer.
                item["value"] = None
                if not value_text:
                    item["value_text"] = value_candidate
            else:
                if numeric_value.is_finite():
                    item["value"] = format(numeric_value, "f")
                else:
                    item["value"] = None
                    if not value_text:
                        item["value_text"] = value_candidate
        if not str(item.get("value_text") or "").strip():
            # An empty placeholder is not a source value; omitting the key
            # figure is safer than inventing display text.
            continue
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
    payload["claims"] = claims
    payload["answer"] = (
        " ".join(rendered_claims)
        if rendered_claims
        else legacy_answer or ("Deterministic tool requested." if payload.get("tool_calls") else "")
    )
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
                upload_timestamp=document.upload_timestamp,
                extraction_run_id=run.id,
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


def _context_with_tool_results(
    context: str,
    tool_history: list[dict[str, Any]],
) -> str:
    if not tool_history:
        return context
    return (
        context
        + "\n\n<kuki_deterministic_tool_results>\n"
        + json.dumps(tool_history, ensure_ascii=False, separators=(",", ":"), default=str)
        + "\n</kuki_deterministic_tool_results>"
    )


def _question_financial_years(question: str) -> list[str]:
    """Return explicitly requested Indian FYs in normalized YYYY-YY form."""
    years: list[str] = []
    for match in _FY_PAIR_IN_QUESTION.finditer(question):
        raw_start, raw_end = match.groups()
        start_year = int(raw_start)
        if len(raw_start) == 2:
            start_year += 2000
        expected_end = start_year + 1
        end_year = int(raw_end)
        if len(raw_end) == 2:
            end_year += (expected_end // 100) * 100
            if end_year < expected_end:
                end_year += 100
        normalized = f"{start_year}-{end_year % 100:02d}"
        if normalized not in years:
            years.append(normalized)

    if years:
        return years[:4]

    # Indian usage often names an FY by its ending year (for example, FY 2025
    # means 1 April 2024 through 31 March 2025). Only accept the explicit FY
    # abbreviation here so a general calendar year is never reinterpreted.
    for match in _FY_END_YEAR_IN_QUESTION.finditer(question):
        ending_year = int(match.group(1))
        if ending_year > 1:
            normalized = f"{ending_year - 1}-{ending_year % 100:02d}"
            if normalized not in years:
                years.append(normalized)
    return years[:4]


def _question_metric_filter(question: str) -> str | None:
    matched = _question_metrics(question)
    return matched[0] if len(matched) == 1 else None


def _question_metrics(question: str) -> list[str]:
    normalized = question.casefold()
    matched: list[str] = []
    if "electricity" in normalized or re.search(r"\b(?:kwh|kvah)\b|\bgrid\s+power\b", normalized):
        matched.append("electricity")
    if "water" in normalized or re.search(r"\bkl\b|\bm3\b|m³", normalized):
        matched.append("water")
    if "waste" in normalized:
        matched.append("waste")
    if "fuel" in normalized:
        matched.append("fuel")
    if re.search(r"\bemissions?\b|\bco2\b|\bghg\b", normalized):
        matched.append("emissions")
    return matched


_FY_METRIC_GAP_TERMS = {
    "electricity": ("electricity", "grid supply", "solar", "wind", "renewable", "kwh", "kvah"),
    "water": ("water", "m³", "m3", " kl "),
    "waste": ("waste", "kg", "tonne"),
    "fuel": ("fuel", "diesel", "petrol", "litre", "liter"),
    "emissions": ("emission", "co2", "ghg", "tco2"),
}


def _gap_matches_metrics(gap: str, metrics: list[str] | None) -> bool:
    if not metrics:
        return True
    normalized = f" {gap.casefold()} "
    named = {
        metric
        for metric, terms in _FY_METRIC_GAP_TERMS.items()
        if any(term in normalized for term in terms)
    }
    return not named or bool(named.intersection(metrics))


def _documents_named_in_question(
    question: str,
    documents: list[AnswerDocument],
) -> tuple[list[AnswerDocument], bool]:
    normalized = question.casefold()
    named = [
        document
        for document in documents
        if document.filename.casefold() in normalized
    ]
    if named:
        return named, True
    mentions_filename = re.search(
        r"\b[\w .()&_-]+\.(?:xlsx|xls|csv|pdf|docx)\b", question, re.IGNORECASE
    )
    return ([], True) if mentions_filename else (documents, False)


async def _precompute_fy_tool_results(
    session: AsyncSession,
    user_id: int,
    question: str,
    documents: list[AnswerDocument],
) -> list[dict[str, Any]] | None:
    financial_years = _question_financial_years(question)
    if not financial_years:
        return None

    scoped_documents, explicitly_named = _documents_named_in_question(question, documents)
    requested_metrics = _question_metrics(question) or None
    tool_metric = requested_metrics[0] if requested_metrics and len(requested_metrics) == 1 else ""
    results: list[dict[str, Any]] = []
    if not scoped_documents:
        for financial_year in financial_years:
            call = AnswerToolCallDraft(
                name="financial_year_totals",
                financial_year=financial_year,
                metric=tool_metric,
            )
            results.append(
                {
                    "tool_call": call.model_dump(mode="json"),
                    "tool_result": {
                        "error": (
                            "The specifically named document is not available in the selected scope."
                            if explicitly_named
                            else "No processed documents are in scope."
                        )
                    },
                    "trigger": "database_financial_year_summary",
                }
            )
        return results

    documents_by_organisation: dict[str, list[AnswerDocument]] = {}
    for document in scoped_documents:
        name = (document.organisation or "").strip().casefold()
        key = name or f"__unassigned__:{document.id}"
        documents_by_organisation.setdefault(key, []).append(document)

    for financial_year in financial_years:
        call = AnswerToolCallDraft(
            name="financial_year_totals",
            financial_year=financial_year,
            metric=tool_metric,
        )
        organisations: list[dict[str, Any]] = []
        all_gaps: list[str] = []
        error_result: dict[str, Any] | None = None
        for organisation_key, organisation_documents in documents_by_organisation.items():
            run_ids = {
                document.id: document.extraction_run_id
                for document in organisation_documents
                if document.extraction_run_id is not None
            }
            try:
                summary = await get_financial_year_summary(
                    session,
                    user_id,
                    financial_year,
                    organisation_key,
                    [document.id for document in organisation_documents],
                    True,
                    pinned_extraction_run_ids=run_ids or None,
                )
            except HTTPException as error:
                detail = error.detail if isinstance(error.detail, str) else str(error.detail)
                error_result = {"error": detail}
                break

            metrics = [
                metric
                for metric in summary.metrics
                if requested_metrics is None or metric.metric in requested_metrics
            ]
            sources = [
                source
                for source in summary.sources
                if requested_metrics is None or source.metric in requested_metrics
            ]
            metric_data = [metric for metric in metrics if metric.value is not None]
            has_data = bool(metric_data) or any(metric.status == "conflict" for metric in metrics)
            if not has_data:
                coverage = "no_data"
            elif all(metric.months_covered == 12 for metric in metric_data) and not any(
                metric.status == "conflict" for metric in metrics
            ):
                coverage = "complete"
            else:
                coverage = "partial"

            gaps = [
                gap
                for gap in summary.gaps
                if _gap_matches_metrics(gap, requested_metrics)
            ]
            all_gaps.extend(gaps)
            organisation_label = next(
                (
                    option.label
                    for option in summary.organisation_options
                    if option.value == summary.organisation
                ),
                organisation_key,
            )
            organisations.append(
                {
                    "organisation": organisation_label,
                    "coverage_status": coverage,
                    "metrics": [
                        metric.model_dump(mode="json", exclude_none=True)
                        for metric in metrics
                    ],
                    "sources": [
                        source.model_dump(mode="json", exclude_none=True)
                        for source in sources
                    ],
                    "gaps": gaps,
                }
            )
            source_count = len(organisations[-1]["sources"])
            organisations[-1]["source_record_count"] = source_count
            if source_count > _MAX_FY_TOOL_SOURCES_PER_ORGANISATION:
                organisations[-1]["sources"] = organisations[-1]["sources"][
                    :_MAX_FY_TOOL_SOURCES_PER_ORGANISATION
                ]
                note = (
                    f"The deterministic total used {source_count} source records; "
                    f"the tool returned the first {_MAX_FY_TOOL_SOURCES_PER_ORGANISATION} locations."
                )
                organisations[-1]["gaps"].append(note)
                all_gaps.append(note)

        result_payload = error_result or {
            "financial_year": financial_year,
            "organisations": organisations,
            "gaps": list(dict.fromkeys(all_gaps)),
        }
        results.append(
            {
                "tool_call": call.model_dump(mode="json"),
                "tool_result": result_payload,
                "trigger": "database_financial_year_summary",
            }
        )
    return results


def _segments_for_calculation(
    expression: str,
    documents: list[AnswerDocument],
    document_id: str = "",
) -> tuple[list[Segment], list[AnswerDocument]]:
    """Resolve worksheet references to one selected workbook before arithmetic."""
    scoped_documents = documents
    if document_id:
        try:
            parsed_document_id = UUID(document_id)
        except ValueError as error:
            raise CalculationError("The requested document id is invalid") from error
        scoped_documents = [
            document for document in documents if document.id == parsed_document_id
        ]
        if not scoped_documents:
            raise CalculationError("The requested document is outside the selected scope")

    sheet_names = list(
        dict.fromkeys(
            (match.group(1) or match.group(2) or "").strip().casefold()
            for match in _SHEET_REFERENCE_IN_EXPRESSION.finditer(expression)
        )
    )
    if sheet_names:
        matches = [
            document
            for document in scoped_documents
            if all(
                any(
                    segment.locator.sheet
                    and segment.locator.sheet.casefold() == sheet_name
                    for segment in document.segments
                )
                for sheet_name in sheet_names
            )
        ]
        if not matches:
            raise CalculationError(
                "The worksheet references are not all present in one selected document"
            )
        if len(matches) > 1:
            raise CalculationError(
                "The worksheet references match multiple selected documents; retry with document_id"
            )
        scoped_documents = matches

    segments = [
        segment for document in scoped_documents for segment in document.segments
    ]
    return segments, scoped_documents


def _filter_fy_result_metrics(
    result: dict[str, Any],
    requested_metrics: list[str],
) -> dict[str, Any]:
    """Narrow an all-metrics FY result without recalculating or mixing totals."""
    if "error" in result:
        return result
    filtered = dict(result)
    filtered_organisations: list[dict[str, Any]] = []
    all_gaps: list[str] = []
    for organisation in result.get("organisations", []):
        if not isinstance(organisation, dict):
            continue
        item = dict(organisation)
        item["metrics"] = [
            metric
            for metric in organisation.get("metrics", [])
            if isinstance(metric, dict) and metric.get("metric") in requested_metrics
        ]
        item["sources"] = [
            source
            for source in organisation.get("sources", [])
            if isinstance(source, dict) and source.get("metric") in requested_metrics
        ]
        item["gaps"] = [
            gap
            for gap in organisation.get("gaps", [])
            if isinstance(gap, str) and _gap_matches_metrics(gap, requested_metrics)
        ]
        data_metrics = [metric for metric in item["metrics"] if metric.get("value") is not None]
        has_data = bool(data_metrics) or any(
            metric.get("status") == "conflict" for metric in item["metrics"]
        )
        if not has_data:
            item["coverage_status"] = "no_data"
        elif all(metric.get("months_covered") == 12 for metric in data_metrics) and not any(
            metric.get("status") == "conflict" for metric in item["metrics"]
        ):
            item["coverage_status"] = "complete"
        else:
            item["coverage_status"] = "partial"
        item["source_record_count"] = len(item["sources"])
        filtered_organisations.append(item)
        all_gaps.extend(item["gaps"])
    filtered["organisations"] = filtered_organisations
    filtered["gaps"] = list(dict.fromkeys(all_gaps))
    return filtered


def _execute_answer_tool(
    call: AnswerToolCallDraft,
    documents: list[AnswerDocument],
) -> dict[str, Any]:
    if call.name == "calculate":
        expression = call.expression.strip()
        if not expression:
            return {"error": "The calculate tool needs an expression."}

        document_id = call.document_id.strip()
        try:
            segments, scoped_documents = _segments_for_calculation(
                expression, documents, document_id
            )
            value = evaluate_expression(expression, segments)
        except CalculationError as error:
            return {"error": str(error), "expression": expression}
        result: dict[str, Any] = {
            "expression": expression,
            "result": decimal_text(value),
            "document_ids": [str(document.id) for document in scoped_documents],
            "note": "Exact arithmetic result. Use cited source evidence to state the unit.",
        }
        blank_count, blank_preview = blank_cells_in_expression(expression, segments)
        if blank_count:
            result["blank_cell_count"] = blank_count
            result["blank_cells"] = blank_preview
            result["warning"] = (
                f"The calculation excluded {blank_count} blank or absent cell(s); "
                "they were not treated as zero."
            )
        return result

    if call.name == "financial_year_totals":
        financial_year = call.financial_year.strip()
        if not financial_year:
            return {"error": "The financial_year_totals tool needs a financial year."}
        metric = call.metric.strip().casefold() or None
        if metric and metric not in {"electricity", "water", "waste", "fuel", "emissions"}:
            return {"error": "Choose electricity, water, waste, fuel, or emissions as the metric."}
        try:
            summary = summarize_answer_context(documents, financial_year, metric)
        except ValueError as error:
            return {"error": str(error)}

        for organisation in summary["organisations"]:
            sources = organisation.get("sources", [])
            source_count = len(sources)
            organisation["source_record_count"] = source_count
            if source_count > _MAX_FY_TOOL_SOURCES_PER_ORGANISATION:
                organisation["sources"] = sources[:_MAX_FY_TOOL_SOURCES_PER_ORGANISATION]
                note = (
                    f"The deterministic total used {source_count} source records; "
                    f"the tool returned the first {_MAX_FY_TOOL_SOURCES_PER_ORGANISATION} locations."
                )
                organisation.setdefault("gaps", []).append(note)
                summary.setdefault("gaps", []).append(note)
        return summary

    return {"error": "Unknown deterministic tool."}


async def generate_answer(
    question: str,
    documents: list[AnswerDocument],
    trace_context: dict[str, str] | None = None,
    initial_tool_results: list[dict[str, Any]] | None = None,
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
    capture_content = capture_content_enabled()
    document_ids = [str(document.id) for document in documents]
    trace_metadata = {
        "provider": "google",
        "model": model_name,
        "prompt_hash": _ANSWER_PROMPT_HASH,
        "document_ids": document_ids,
        "document_count": len(documents),
        "context_char_count": len(context),
        "trace_context": trace_context or {"origin": "interactive"},
    }
    trace_input: dict[str, Any] = {
        "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "document_ids": document_ids,
        "document_count": len(documents),
        "context_char_count": len(context),
    }
    generation_input: dict[str, Any] = {
        "question_sha256": trace_input["question_sha256"],
        "document_ids": document_ids,
        "prompt_hash": _ANSWER_PROMPT_HASH,
        "context_char_count": len(context),
    }
    if capture_content:
        generation_input.update(
            {"instructions": ANSWER_INSTRUCTIONS, "context": context}
        )
    try:
        with langfuse_observation(
            as_type="span",
            name="sustainability-question-answer",
            input=trace_input,
            metadata=trace_metadata,
        ) as trace:
            model = ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=api_key,
                max_output_tokens=12_000,
            ).with_structured_output(
                gemini_answer_schema(),
                method="json_schema",
                include_raw=True,
            )
            tool_history: list[dict[str, Any]] = []
            tool_result_cache: dict[str, dict[str, Any]] = {}
            tool_call_count = 0
            tool_round_count = 0
            interactive_answer_path = (
                trace_context is not None
                and trace_context.get("origin") == "interactive"
            )

            if initial_tool_results is None and not interactive_answer_path:
                # Evaluation answers do not have a live database session, so
                # they calculate from their pinned in-memory extraction facts.
                metric_filter = _question_metric_filter(question)
                initial_tool_results = []
                for financial_year in _question_financial_years(question):
                    call = AnswerToolCallDraft(
                        name="financial_year_totals",
                        financial_year=financial_year,
                        metric=metric_filter or "",
                    )
                    initial_tool_results.append(
                        {
                            "tool_call": call.model_dump(mode="json"),
                            "tool_result": _execute_answer_tool(call, documents),
                            "trigger": "pinned_in_memory_facts",
                        }
                    )
            elif initial_tool_results is None:
                initial_tool_results = []

            for entry in initial_tool_results:
                call_payload = entry["tool_call"]
                result_payload = entry["tool_result"]
                tool_call_count += 1
                tool_trace_input: dict[str, Any] = (
                    {"tool_call": call_payload}
                    if capture_content
                    else {
                        "tool": call_payload.get("name", "unknown"),
                        "arguments_sha256": hashlib.sha256(
                            json.dumps(call_payload, sort_keys=True).encode("utf-8")
                        ).hexdigest(),
                    }
                )
                with langfuse_observation(
                    as_type="span",
                    name=f"deterministic-{call_payload.get('name', 'tool')}",
                    input=tool_trace_input,
                    metadata={
                        "tool": call_payload.get("name", "unknown"),
                        "trigger": entry.get("trigger", "explicit_financial_year_in_question"),
                        "trace_context": trace_context or {"origin": "interactive"},
                    },
                ) as tool_observation:
                    tool_trace_output: Any = (
                        result_payload
                        if capture_content
                        else {
                            "succeeded": "error" not in result_payload,
                            "result_sha256": hashlib.sha256(
                                json.dumps(
                                    result_payload, sort_keys=True, default=str
                                ).encode("utf-8")
                            ).hexdigest(),
                        }
                    )
                    update_observation(tool_observation, output=tool_trace_output)
                cache_key = json.dumps(call_payload, sort_keys=True)
                tool_result_cache[cache_key] = result_payload
                tool_history.append({"tool_call": call_payload, "tool_result": result_payload})

            for round_number in range(_MAX_ANSWER_TOOL_ROUNDS + 1):
                round_context = _context_with_tool_results(context, tool_history)
                current_generation_input = dict(generation_input)
                current_generation_input["tool_result_count"] = len(tool_history)
                if capture_content:
                    current_generation_input["context"] = round_context
                else:
                    current_generation_input["round_context_char_count"] = len(round_context)

                requested_tools: list[AnswerToolCallDraft] = []
                final_answer: tuple[AnswerContent, AnswerStatus] | None = None
                with langfuse_observation(
                    as_type="generation",
                    name=f"gemini-evidence-based-answer-round-{round_number + 1}",
                    model=model_name,
                    input=current_generation_input,
                    metadata={
                        "provider": "google",
                        "prompt_hash": _ANSWER_PROMPT_HASH,
                        "round": round_number + 1,
                        "trace_context": trace_context or {"origin": "interactive"},
                    },
                ) as generation:
                    try:
                        result = await model.ainvoke(
                            [
                                SystemMessage(content=ANSWER_INSTRUCTIONS),
                                HumanMessage(content=round_context),
                            ]
                        )
                        raw_message = None
                        if isinstance(result, dict) and "parsed" in result:
                            if result.get("parsing_error") is not None:
                                validation_error = ValueError(
                                    "Gemini returned invalid structured answer output"
                                )
                                raw_message = result.get("raw")
                                response_metadata = getattr(
                                    raw_message, "response_metadata", {}
                                )
                                finish_reason = (
                                    response_metadata.get("finish_reason")
                                    if isinstance(response_metadata, dict)
                                    else None
                                )
                                if isinstance(finish_reason, str) and re.fullmatch(
                                    r"[A-Z0-9_]{1,40}", finish_reason
                                ):
                                    validation_error.finish_reason = finish_reason
                                parsing_error = result["parsing_error"]
                                if isinstance(parsing_error, BaseException):
                                    raise validation_error from parsing_error
                                raise validation_error
                            draft = _answer_draft_from_gemini(result.get("parsed"))
                            raw_message = result.get("raw")
                        else:
                            draft = _answer_draft_from_gemini(result)

                        usage = _answer_token_usage(raw_message)
                        if usage:
                            update_observation(generation, usage_details=usage)
                        if draft.tool_calls:
                            requested_tools = draft.tool_calls
                            tool_output: Any = (
                                [call.model_dump(mode="json") for call in requested_tools]
                                if capture_content
                                else {"tool_call_count": len(requested_tools)}
                            )
                            update_observation(
                                generation,
                                output={"tool_calls_requested": tool_output},
                            )
                        else:
                            attempted_expressions = {
                                str(entry["tool_call"].get("expression", "")).strip()
                                for entry in tool_history
                                if entry["tool_call"].get("name") == "calculate"
                            }
                            missing_calculations = [
                                calculation
                                for calculation in draft.calculations
                                if calculation.expression.strip()
                                not in attempted_expressions
                            ]
                            if missing_calculations:
                                requested_tools = [
                                    AnswerToolCallDraft(
                                        name="calculate",
                                        expression=calculation.expression,
                                    )
                                    for calculation in missing_calculations
                                ]
                                update_observation(
                                    generation,
                                    output={
                                        "tool_calls_requested": (
                                            [
                                                call.model_dump(mode="json")
                                                for call in requested_tools
                                            ]
                                            if capture_content
                                            else {"tool_call_count": len(requested_tools)}
                                        ),
                                        "reason": "Recomputing model-proposed calculations before finalizing.",
                                    },
                                )
                            else:
                                content, status = _validate_draft(
                                    draft, documents, model_name
                                )
                                content, status = _apply_tool_result_quality(
                                    content, status, tool_history
                                )
                                final_answer = (content, status)
                                generation_output: Any = (
                                    content.model_dump(mode="json")
                                    if capture_content
                                    else {
                                        "status": status,
                                        "answer_char_count": len(content.answer),
                                        "key_value_count": len(content.key_values),
                                        "calculation_count": len(content.calculations),
                                        "evidence_count": len(content.evidence),
                                        "gap_count": len(content.gaps),
                                    }
                                )
                                update_observation(generation, output=generation_output)
                    except Exception as error:
                        _trace_answer_error(trace, generation, error)
                        raise

                if final_answer is not None:
                    content, status = final_answer
                    update_observation(
                        trace,
                        output={
                            "status": status,
                            "model": model_name,
                            "key_value_count": len(content.key_values),
                            "calculation_count": len(content.calculations),
                            "evidence_count": len(content.evidence),
                            "gap_count": len(content.gaps),
                            "tool_rounds": tool_round_count,
                        },
                    )
                    return content, status

                if tool_round_count >= _MAX_ANSWER_TOOL_ROUNDS:
                    raise AnswerGenerationError(
                        "The answer requested too many deterministic tool rounds."
                    )
                tool_round_count += 1
                for call in requested_tools:
                    call_payload = call.model_dump(mode="json")
                    cache_key = json.dumps(call_payload, sort_keys=True)
                    cached_result = tool_result_cache.get(cache_key)
                    if cached_result is None and call.name == "financial_year_totals":
                        requested_metric = call.metric.strip().casefold()
                        matching_result = next(
                            (
                                entry
                                for entry in tool_history
                                if entry.get("tool_call", {}).get("name")
                                == "financial_year_totals"
                                and entry.get("tool_call", {}).get("financial_year", "").casefold()
                                == call.financial_year.strip().casefold()
                                and (
                                    not entry.get("tool_call", {}).get("metric", "").strip()
                                    or entry.get("tool_call", {}).get("metric", "").casefold()
                                    == requested_metric
                                )
                            ),
                            None,
                        )
                        if matching_result is not None:
                            cached_result = matching_result.get("tool_result", {})
                            if requested_metric and isinstance(cached_result, dict):
                                cached_result = _filter_fy_result_metrics(
                                    cached_result, [requested_metric]
                                )
                            tool_result_cache[cache_key] = cached_result
                    if cached_result is not None:
                        result_payload = cached_result
                    elif interactive_answer_path and call.name == "financial_year_totals":
                        result_payload = {
                            "error": (
                                "No database-calculated result is available for that "
                                "financial-year scope. Use the FY result already supplied, "
                                "or state the specific Indian financial year you want."
                            )
                        }
                    elif tool_call_count >= _MAX_ANSWER_TOOL_CALLS:
                        result_payload = {
                            "error": "The answer reached its deterministic tool-call limit."
                        }
                    else:
                        tool_call_count += 1
                        tool_trace_input: dict[str, Any] = (
                            {"tool_call": call_payload}
                            if capture_content
                            else {
                                "tool": call.name,
                                "arguments_sha256": hashlib.sha256(
                                    json.dumps(call_payload, sort_keys=True).encode("utf-8")
                                ).hexdigest(),
                            }
                        )
                        with langfuse_observation(
                            as_type="span",
                            name=f"deterministic-{call.name}",
                            input=tool_trace_input,
                            metadata={
                                "tool": call.name,
                                "trace_context": trace_context or {"origin": "interactive"},
                            },
                        ) as tool_observation:
                            result_payload = _execute_answer_tool(call, documents)
                            tool_trace_output: Any = (
                                result_payload
                                if capture_content
                                else {
                                    "succeeded": "error" not in result_payload,
                                    "result_sha256": hashlib.sha256(
                                        json.dumps(
                                            result_payload,
                                            sort_keys=True,
                                            default=str,
                                        ).encode("utf-8")
                                    ).hexdigest(),
                                }
                            )
                            update_observation(tool_observation, output=tool_trace_output)
                        tool_result_cache[cache_key] = result_payload

                    history_entry = {
                        "tool_call": call_payload,
                        "tool_result": result_payload,
                    }
                    tool_history.append(history_entry)

            raise AnswerGenerationError(
                "Gemini did not finish the answer after receiving deterministic tool results."
            )
    except AnswerGenerationError:
        raise
    except Exception as error:
        retryable, cause_type, status_code = _answer_error_details(error)
        diagnostic = _safe_answer_error_diagnostic(error)
        logger.warning(
            "Answer generation failed | error_type=%s cause_type=%s status_code=%s retryable=%s diagnostic=%s",
            type(error).__name__,
            cause_type,
            status_code,
            retryable,
            diagnostic,
        )
        raise AnswerGenerationError(
            "The answer could not be generated. Please try again.",
            retryable=retryable,
            cause_type=cause_type,
            status_code=status_code,
            diagnostic=diagnostic,
        ) from error


def _answer_token_usage(raw_message: Any) -> dict[str, int] | None:
    if raw_message is None:
        return None
    usage = getattr(raw_message, "usage_metadata", None)
    if not isinstance(usage, dict):
        return None
    aliases = {
        "input": usage.get("input_tokens"),
        "output": usage.get("output_tokens"),
        "total": usage.get("total_tokens"),
    }
    return (
        {key: int(value) for key, value in aliases.items() if value is not None}
        or None
    )


def _trace_answer_error(
    trace: Any | None,
    generation: Any | None,
    error: Exception,
) -> None:
    attributes = {
        "level": "ERROR",
        "status_message": type(error).__name__,
    }
    update_observation(generation, **attributes)
    update_observation(trace, **attributes)


def _apply_tool_result_quality(
    content: AnswerContent,
    status: AnswerStatus,
    tool_history: list[dict[str, Any]],
) -> tuple[AnswerContent, AnswerStatus]:
    """Carry deterministic calculation warnings and FY limits into answer status."""
    calculation_warnings = [
        entry["tool_result"].get("warning")
        for entry in tool_history
        if entry.get("tool_call", {}).get("name") == "calculate"
        and isinstance(entry.get("tool_result"), dict)
        and isinstance(entry["tool_result"].get("warning"), str)
    ]
    fy_results = [
        entry.get("tool_result")
        for entry in tool_history
        if entry.get("tool_call", {}).get("name") == "financial_year_totals"
        and isinstance(entry.get("tool_result"), dict)
    ]
    if not fy_results and not calculation_warnings:
        return content, status

    gaps = list(content.gaps)
    gaps.extend(warning for warning in calculation_warnings if warning.strip())
    has_usable_value = False
    has_conflict = False
    has_incomplete_coverage = bool(calculation_warnings)
    for result in fy_results:
        tool_error = result.get("error")
        if isinstance(tool_error, str) and tool_error.strip():
            gaps.append(f"The financial-year calculation could not be completed: {tool_error.strip()}")
            has_incomplete_coverage = True
        for gap in result.get("gaps", []):
            if isinstance(gap, str) and gap.strip():
                gaps.append(gap.strip())
        for organisation in result.get("organisations", []):
            if not isinstance(organisation, dict):
                continue
            if organisation.get("coverage_status") == "partial":
                has_incomplete_coverage = True
            for metric in organisation.get("metrics", []):
                if not isinstance(metric, dict):
                    continue
                value = metric.get("value")
                metric_status = metric.get("status")
                label = str(metric.get("label") or metric.get("metric") or "Resource")
                period = str(result.get("financial_year") or "the selected financial year")
                if value is not None:
                    has_usable_value = True
                if metric_status == "conflict":
                    has_conflict = True
                    gaps.append(
                        f"{label} has conflicting source values for FY {period}; the conflicting values were excluded."
                    )
                elif metric_status == "no_data":
                    gaps.append(
                        f"No usable {label.casefold()} quantity records were found for FY {period}."
                    )
                    has_incomplete_coverage = True
            for gap in organisation.get("gaps", []):
                if isinstance(gap, str) and gap.strip():
                    gaps.append(gap.strip())

    if fy_results and not has_usable_value and status != "insufficient_evidence":
        status = "insufficient_evidence"
    elif has_conflict and status != "insufficient_evidence":
        status = "conflicting_evidence"
    elif has_incomplete_coverage and status == "answered":
        status = "partial"
    content.gaps = list(dict.fromkeys(gaps))
    return content, status


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
    known_calculation_ids = {calculation.id for calculation in draft.calculations}
    referenced_calculation_ids = set(_CALCULATION_CITATION.findall(draft.answer))
    for claim in draft.claims:
        referenced_ids.update(claim.evidence_ids)
        referenced_calculation_ids.update(claim.calculation_ids)
        if not claim.evidence_ids and not claim.calculation_ids:
            missing_support = True
    if (
        not referenced_ids
        and not referenced_calculation_ids
        and draft.status != "insufficient_evidence"
    ):
        missing_support = True
    if missing_support:
        gaps.append(
            "One or more answer claims did not include a linked source or calculation."
        )
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
    unknown_calculation_ids = referenced_calculation_ids - known_calculation_ids
    if unknown_ids:
        gaps.append(
            "Some answer references had no matching source: "
            + ", ".join(sorted(unknown_ids))
            + "."
        )
    if unknown_calculation_ids:
        gaps.append(
            "Some answer references had no matching calculation: "
            + ", ".join(sorted(unknown_calculation_ids))
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
            cited_documents = list(
                dict.fromkeys(
                    evidence.document_id
                    for evidence_id in item.evidence_ids
                    if (evidence := evidence_by_id.get(evidence_id)) is not None
                )
            )
            calculation_documents = (
                [documents_by_id[document_id] for document_id in cited_documents]
                if cited_documents
                else documents
            )
            calculation_segments, _ = _segments_for_calculation(
                item.expression, calculation_documents
            )
            computed = evaluate_expression(
                item.expression,
                calculation_segments,
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
        or unknown_calculation_ids
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
