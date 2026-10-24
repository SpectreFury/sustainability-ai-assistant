"""Persisted evaluation-run creation, summaries, and deterministic scoring."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from evaluations.case_pack import (
    CASE_SET_VERSION,
    EVALUATION_CASES,
    case_set_hash,
    public_case,
)
from models import Document, EvaluationRun, ExtractionRun
from prompts.answer import ANSWER_INSTRUCTIONS
from prompts.fact_extraction import FACT_EXTRACTION_INSTRUCTIONS
from schemas.answers import AnswerContent
from schemas.financial_year import FinancialYearSummaryResponse

_NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?")
_CELL = re.compile(r"^([A-Z]{1,3})(\d+)$", re.IGNORECASE)


async def create_evaluation_run(
    session: AsyncSession, user_id: int
) -> EvaluationRun:
    documents = list(
        (
            await session.scalars(
                select(Document)
                .where(Document.user_id == user_id)
                .order_by(Document.upload_timestamp.desc())
            )
        ).all()
    )
    snapshot: dict[str, dict[str, Any]] = {}
    wanted = {
        filename
        for case in EVALUATION_CASES
        for filename in case["required_documents"]
    }
    for filename in wanted:
        candidates = [
            item for item in documents if item.filename.casefold() == filename.casefold()
        ]
        # Pin the uploaded asset itself. Evaluation re-runs extraction from
        # these exact bytes instead of relying on an older persisted extraction.
        document = next(
            (item for item in candidates if item.cloudinary_url),
            candidates[0] if candidates else None,
        )
        snapshot[filename] = (
            {
                "document_id": str(document.id),
                "file_hash": document.file_hash,
                "status_at_start": document.status,
                "cloudinary_public_id": document.cloudinary_public_id,
                "upload_complete": bool(document.cloudinary_url),
            }
            if document
            else {
                "document_id": None,
                "file_hash": None,
                "status_at_start": "missing",
                "cloudinary_public_id": None,
                "upload_complete": False,
            }
        )

    pinned_document_ids = {
        UUID(details["document_id"])
        for details in snapshot.values()
        if details.get("document_id")
    }
    pinned_extractions: dict[UUID, ExtractionRun] = {}
    if pinned_document_ids:
        extraction_rows = await session.scalars(
            select(ExtractionRun)
            .where(
                ExtractionRun.document_id.in_(pinned_document_ids),
                ExtractionRun.status == "succeeded",
            )
            .order_by(
                ExtractionRun.document_id,
                ExtractionRun.attempt_number.desc(),
                ExtractionRun.completed_at.desc(),
            )
        )
        for extraction_run in extraction_rows:
            pinned_extractions.setdefault(extraction_run.document_id, extraction_run)
    for details in snapshot.values():
        document_id = details.get("document_id")
        extraction_run = (
            pinned_extractions.get(UUID(document_id)) if document_id else None
        )
        details["financial_year_extraction_run_id"] = (
            str(extraction_run.id) if extraction_run else None
        )

    run = EvaluationRun(
        user_id=user_id,
        status="queued",
        current_stage="Queued",
        case_set_version=CASE_SET_VERSION,
        case_set_hash=case_set_hash(),
        answer_prompt_hash=hashlib.sha256(ANSWER_INSTRUCTIONS.encode()).hexdigest(),
        extraction_prompt_hash=hashlib.sha256(
            FACT_EXTRACTION_INSTRUCTIONS.encode()
        ).hexdigest(),
        case_count=len(EVALUATION_CASES),
        completed_count=0,
        document_snapshot=snapshot,
        extraction_results={},
        case_results=[],
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def list_evaluation_runs(
    session: AsyncSession, user_id: int, limit: int = 10
) -> list[EvaluationRun]:
    result = await session.scalars(
        select(EvaluationRun)
        .where(EvaluationRun.user_id == user_id)
        .order_by(EvaluationRun.created_at.desc())
        .limit(limit)
    )
    return list(result.all())


async def get_evaluation_run(
    session: AsyncSession, user_id: int, run_id: UUID
) -> EvaluationRun | None:
    return await session.scalar(
        select(EvaluationRun).where(
            EvaluationRun.user_id == user_id,
            EvaluationRun.id == run_id,
        )
    )


def case_catalog() -> list[dict[str, Any]]:
    return [public_case(case) for case in EVALUATION_CASES]


def run_counts(run: EvaluationRun) -> dict[str, int]:
    results = run.case_results or []
    passed = sum(result.get("passed") is True for result in results)
    evaluated = sum(result.get("passed") is not None for result in results)
    blocked = sum(result.get("status") == "blocked" for result in results)
    errors = sum(result.get("status") == "error" for result in results)
    return {
        "passed_count": passed,
        "evaluated_count": evaluated,
        "blocked_count": blocked,
        "error_count": errors,
    }


def serialize_run_summary(run: EvaluationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "current_stage": run.current_stage,
        "case_set_version": run.case_set_version,
        "model_name": run.model_name,
        "case_count": run.case_count,
        "completed_count": run.completed_count,
        **run_counts(run),
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "error_message": run.error_message,
    }


def serialize_run(run: EvaluationRun) -> dict[str, Any]:
    return {
        **serialize_run_summary(run),
        "case_set_hash": run.case_set_hash,
        "answer_prompt_hash": run.answer_prompt_hash,
        "extraction_prompt_hash": run.extraction_prompt_hash,
        "document_snapshot": _public_document_snapshot(run.document_snapshot or {}),
        "case_results": [
            {
                **result,
                "document_snapshot": _public_document_snapshot(
                    result.get("document_snapshot") or {}
                ),
            }
            for result in (run.case_results or [])
        ],
    }


def _public_document_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Expose run provenance without storage identifiers or extracted source text."""
    allowed = {
        "document_id",
        "file_hash",
        "status_at_start",
        "extraction_model",
        "extraction_pipeline",
        "extraction_prompt_hash",
        "extraction_attempts",
        "financial_year_extraction_run_id",
    }
    return {
        filename: {key: value for key, value in details.items() if key in allowed}
        for filename, details in snapshot.items()
        if isinstance(details, dict)
    }


def score_case(
    case: dict[str, Any],
    answer: AnswerContent,
    status: str,
    extraction_pass: bool,
) -> dict[str, Any]:
    answer_text = " ".join(
        [answer.answer]
        + [
            " ".join(
                str(value)
                for value in [item.label, item.value, item.value_text, item.unit, item.period]
                if value
            )
            for item in answer.key_values
        ]
    )
    normalized_answer = _normalize(answer_text)
    numbers = _numbers(answer_text)

    answer_pass = all(
        _decimal_expected(item["value"]) in numbers
        and _unit_present(str(item.get("unit", "")), answer)
        for item in case.get("expected_numeric_values", [])
    )
    answer_pass = answer_pass and all(
        any(_term_matches(normalized_answer, term) for term in group)
        for group in case.get("expected_term_groups", [])
    )
    answer_pass = answer_pass and all(
        _term_occurrences(normalized_answer, item["term"]) >= int(item["count"])
        for item in case.get("expected_term_occurrences", [])
    )
    answer_pass = answer_pass and not any(
        _decimal_expected(value) in numbers
        for value in case.get("forbidden_numeric_values", [])
    )
    answer_pass = answer_pass and all(
        any(
            _answer_value_assertion_matches(item, expected)
            and _answer_value_assertion_cited(item, expected, answer)
            for item in answer.key_values
        )
        for expected in case.get("expected_value_assertions", [])
    )

    evidence_pass = all(
        any(_evidence_matches(item, expected) for item in answer.evidence)
        for expected in case.get("expected_evidence", [])
    )
    for expected in case.get("expected_numeric_values", []):
        expected_number = _decimal_expected(expected["value"])
        supported_value = any(
            item.verified
            and expected_number
            in (_numbers(item.value or "") | _numbers(item.value_text or ""))
            and any(
                cited_id == evidence.id and evidence.verified
                for cited_id in item.evidence_ids
                for evidence in answer.evidence
            )
            for item in answer.key_values
        )
        evidence_pass = evidence_pass and supported_value

    calculation = case.get("calculation")
    if calculation:
        calculation_pass = any(
            item.matches
            and item.result is not None
            and _decimal_expected(item.result) == _decimal_expected(calculation["result"])
            and _unit_present(str(calculation.get("unit", "")), answer, item.unit)
            and all(
                _decimal_expected(operand) in _numbers(item.expression)
                for operand in calculation.get("operands", [])
            )
            and (
                not calculation.get("operator")
                or calculation["operator"] in item.expression
            )
            and all(
                any(
                    evidence.id in item.evidence_ids
                    and _evidence_matches(evidence, expected)
                    for evidence in answer.evidence
                )
                for expected in calculation.get("expected_evidence", [])
            )
            for item in answer.calculations
        )
    else:
        calculation_pass = all(item.matches for item in answer.calculations)

    uncertainty_pass = status == case["expected_status"] and all(
        any(
            _term_matches(_normalize(" ".join(answer.gaps + [answer.answer])), term)
            for term in group
        )
        for group in case.get("uncertainty_terms", [])
    )

    checks = {
        "answer": answer_pass,
        "extraction": extraction_pass,
        "evidence": evidence_pass,
        "calculation": calculation_pass,
        "uncertainty": uncertainty_pass,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "expected_status": case["expected_status"],
        "actual_status": status,
    }


def score_extraction(case: dict[str, Any], documents: list[Any]) -> bool:
    """Score fresh extraction facts independently from the generated answer."""
    facts = [fact for document in documents for fact in document.facts]
    fact_text = " ".join(
        " ".join(
            str(value)
            for value in [
                fact.get("key"),
                fact.get("label"),
                fact.get("series"),
                fact.get("value_text"),
                fact.get("unit"),
                fact.get("period_start"),
                fact.get("period_end"),
                fact.get("note"),
            ]
            if value
        )
        for fact in facts
    )
    normalized_facts = _normalize(fact_text)

    for expected in case.get("expected_numeric_values", []):
        expected_number = _decimal_expected(expected["value"])
        if not any(
            expected_number
            in (_numbers(str(fact.get("value_number") or "")) | _numbers(str(fact.get("value_text") or "")))
            and _unit_text_present(str(expected.get("unit", "")), " ".join(
                [str(fact.get("unit") or ""), str(fact.get("value_text") or "")]
            ))
            for fact in facts
        ):
            return False

    for expected in case.get("expected_value_assertions", []):
        if not any(
            _fact_value_assertion_matches(document, fact, expected)
            for document in documents
            for fact in document.facts
        ):
            return False

    for group in case.get("expected_term_groups", []):
        if not any(
            _term_matches(normalized_facts, term)
            or (
                term.casefold() == "dash"
                and any(str(fact.get("value_text", "")).strip() in {"-", "–", "—"} for fact in facts)
            )
            for term in group
        ):
            return False

    for expected in case.get("expected_term_occurrences", []):
        if _term_occurrences(normalized_facts, expected["term"]) < int(expected["count"]):
            return False

    for expected in case.get("expected_evidence", []):
        if not any(_fact_location_matches(fact, expected) for fact in facts):
            return False

    for term in case.get("expected_extraction_absent_terms", []):
        if _term_matches(normalized_facts, term):
            return False
    return True


def score_financial_year_summary(
    case: dict[str, Any],
    summary: FinancialYearSummaryResponse,
    extraction_pass: bool,
) -> dict[str, Any]:
    expected = case["financial_year_expected"]
    candidates = [
        metric
        for metric in summary.metrics
        if metric.metric == expected["metric"]
        and all(
            _term_matches(
                _normalize(" ".join([metric.label, metric.series or ""])),
                term,
            )
            for term in expected.get("series_terms", [])
        )
    ]
    metric = candidates[0] if len(candidates) == 1 else None
    no_data_metrics = {
        item.metric: item
        for item in summary.metrics
        if item.metric in set(expected.get("no_data_metrics", []))
    }
    answer_pass = bool(
        summary.financial_year == expected["financial_year"]
        and summary.coverage_status == "partial"
        and metric is not None
        and metric.value == expected["value"]
        and metric.unit == expected["unit"]
        and metric.months_covered == expected["months_covered"]
        and all(
            item in no_data_metrics
            and no_data_metrics[item].status == "no_data"
            and no_data_metrics[item].value is None
            for item in expected.get("no_data_metrics", [])
        )
    )

    evidence_pass = all(
        any(_financial_year_source_matches(source, assertion) for source in summary.sources)
        for assertion in case.get("expected_value_assertions", [])
    )
    if metric is not None:
        primary_values = [
            _decimal_expected(source.value)
            for source in summary.sources
            if source.metric == expected["metric"]
            and source.unit == expected["unit"]
            and source.treatment == "primary"
            and all(
                _term_matches(
                    _normalize(" ".join([source.label, source.series or ""])), term
                )
                for term in expected.get("series_terms", [])
            )
        ]
        calculated_total = sum(primary_values, Decimal("0"))
        calculation_pass = (
            len(primary_values) == expected["months_covered"]
            and calculated_total == _decimal_expected(expected["value"])
            and metric.calculation is not None
            and _decimal_expected(metric.value or "") == calculated_total
        )
        covered_months = [month.label for month in metric.months if month.covered]
        missing_months = [month.label for month in metric.months if not month.covered]
        uncertainty_pass = (
            summary.coverage_status == case["expected_status"]
            and covered_months == expected["covered_months"]
            and missing_months == expected["missing_months"]
            and all(month.value is None for month in metric.months if not month.covered)
            and any("missing months are not treated as zero" in gap.casefold() for gap in summary.gaps)
            and all(
                any(
                    f"no usable {item} records" in gap.casefold() and "not zero" in gap.casefold()
                    for gap in summary.gaps
                )
                for item in expected.get("no_data_metrics", [])
            )
        )
    else:
        calculation_pass = False
        uncertainty_pass = False

    checks = {
        "answer": answer_pass,
        "extraction": extraction_pass,
        "evidence": evidence_pass,
        "calculation": calculation_pass,
        "uncertainty": uncertainty_pass,
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "expected_status": case["expected_status"],
        "actual_status": summary.coverage_status,
        "metric_label": metric.label if metric is not None else None,
        "metric_value": metric.value if metric is not None else None,
        "metric_unit": metric.unit if metric is not None else None,
        "period_label": metric.period_label if metric is not None else None,
        "months_covered": metric.months_covered if metric is not None else 0,
    }


def _financial_year_source_matches(source: Any, expected: dict[str, Any]) -> bool:
    if (
        not source.verified
        or source.filename.casefold() != expected["filename"].casefold()
        or _decimal_expected(source.value) != _decimal_expected(expected["value"])
        or not _unit_text_present(
            str(expected.get("unit", "")),
            " ".join([source.value_text or "", source.unit or ""]),
        )
    ):
        return False
    locator = source.locator
    if "page" in expected:
        return locator.page == expected["page"]
    return (
        locator.sheet == expected.get("sheet")
        and expected.get("cell", "").upper()
        in _expand_cells(locator.cell_range or "")
    )


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.%₹]+", " ", value.casefold())).strip()


def _term_pattern(term: str) -> re.Pattern[str]:
    normalized = _normalize(term)
    escaped = re.escape(normalized).replace(r"\ ", r"\s*")
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


def _term_matches(normalized_text: str, term: str) -> bool:
    return bool(_term_pattern(term).search(normalized_text))


def _term_occurrences(normalized_text: str, term: str) -> int:
    return len(list(_term_pattern(term).finditer(normalized_text)))


def _decimal_expected(value: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return Decimal("NaN")


def _numbers(value: str) -> set[Decimal]:
    output: set[Decimal] = set()
    for match in _NUMBER.findall(value):
        try:
            number = Decimal(match.replace(",", ""))
        except InvalidOperation:
            continue
        if number.is_finite():
            output.add(number)
    return output


def _unit_present(unit: str, answer: AnswerContent, candidate_unit: str | None = None) -> bool:
    if not unit:
        return True
    unit_text = " ".join(
        [
            answer.answer,
            *(item.value_text or "" for item in answer.key_values),
            *(item.unit or "" for item in answer.key_values),
            candidate_unit or "",
        ]
    ).casefold()
    return _unit_text_present(unit, unit_text)


def _unit_text_present(unit: str, unit_text: str) -> bool:
    if not unit:
        return True
    aliases = {
        "inr": ["inr", "₹", "rs."],
        "inr/cu.m": ["inr/cu.m", "₹/cu.m", "per cu.m", "/cu.m"],
        "cu.m": ["cu.m", "cubic meter", "cubic metre", "m³", "m3"],
        "kg": ["kg", "kilogram"],
        "tonnes": ["tonnes", "tonne", "metric tons", "metric tonnes"],
        "%": ["%", "percent", "percentage"],
        "kwh": ["kwh"],
    }
    candidates = aliases.get(unit.casefold(), [unit.casefold()])
    return any(item in unit_text for item in candidates)


def _fact_location_matches(fact: dict[str, Any], expected: dict[str, Any]) -> bool:
    if not fact.get("verified"):
        return False
    locator = fact.get("locator") or {}
    if "page" in expected:
        return locator.get("page") == expected["page"]
    return (
        locator.get("sheet") == expected.get("sheet")
        and expected.get("cell", "").upper() in _expand_cells(locator.get("cell_range", ""))
    )


def _answer_value_assertion_matches(item: Any, expected: dict[str, Any]) -> bool:
    label = _normalize(str(item.label))
    value_text = " ".join([str(item.value or ""), str(item.value_text or "")])
    return (
        _decimal_expected(expected["value"]) in _numbers(value_text)
        and _unit_text_present(str(expected.get("unit", "")), " ".join([value_text, str(item.unit or "")]))
        and all(_term_matches(label, term) for term in expected.get("label_terms", []))
    )


def _answer_value_assertion_cited(
    item: Any, expected: dict[str, Any], answer: AnswerContent
) -> bool:
    if not (expected.get("sheet") or expected.get("page")):
        return True
    evidence_expectation = {
        key: expected[key]
        for key in ("filename", "page", "sheet", "cell")
        if key in expected
    }
    return any(
        evidence.id in item.evidence_ids
        and _evidence_matches(evidence, evidence_expectation)
        and all(
            _term_matches(_normalize(evidence.quote), term)
            for term in expected.get("source_terms", [])
        )
        for evidence in answer.evidence
    )


def _fact_value_assertion_matches(
    document: Any, fact: dict[str, Any], expected: dict[str, Any]
) -> bool:
    label = _normalize(
        " ".join(
            str(fact.get(key) or "")
            for key in ("key", "label", "series")
        )
    )
    value_text = " ".join(
        [str(fact.get("value_number") or ""), str(fact.get("value_text") or "")]
    )
    quote = _normalize(str(fact.get("quote") or ""))
    location = {
        key: expected[key]
        for key in ("filename", "page", "sheet", "cell")
        if key in expected
    }
    return (
        document.filename.casefold() == expected["filename"].casefold()
        and bool(fact.get("verified"))
        and _decimal_expected(expected["value"]) in _numbers(value_text)
        and _unit_text_present(
            str(expected.get("unit", "")),
            " ".join([value_text, str(fact.get("unit") or "")]),
        )
        and all(_term_matches(label, term) for term in expected.get("label_terms", []))
        and all(_term_matches(quote, term) for term in expected.get("source_terms", []))
        and _fact_location_matches(fact, location)
    )


def _evidence_matches(evidence: Any, expected: dict[str, Any]) -> bool:
    if not evidence.verified or evidence.filename.casefold() != expected["filename"].casefold():
        return False
    locator = evidence.locator
    if "page" in expected:
        return locator.page == expected["page"]
    if locator.sheet != expected.get("sheet"):
        return False
    references = _expand_cells(locator.cell_range or "")
    return expected.get("cell", "").upper() in references


def _expand_cells(cell_range: str) -> set[str]:
    parts = cell_range.replace("$", "").upper().split(":")
    first = _CELL.fullmatch(parts[0]) if parts else None
    last = _CELL.fullmatch(parts[-1]) if len(parts) > 1 else first
    if not first or not last:
        return set()
    start_col, end_col = sorted((_column_number(first[1]), _column_number(last[1])))
    start_row, end_row = sorted((int(first[2]), int(last[2])))
    return {
        f"{_column_name(column)}{row}"
        for row in range(start_row, end_row + 1)
        for column in range(start_col, end_col + 1)
    }


def _column_number(column: str) -> int:
    value = 0
    for character in column.upper():
        value = value * 26 + ord(character) - ord("A") + 1
    return value


def _column_name(number: int) -> str:
    output = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        output = chr(ord("A") + remainder) + output
    return output
