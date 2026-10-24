import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Document, ExtractedFact, ExtractionRun
from schemas.financial_year import (
    FinancialYearDocumentOption,
    FinancialYearExcludedDocument,
    FinancialYearMetric,
    FinancialYearMonth,
    FinancialYearOption,
    FinancialYearOrganisationOption,
    FinancialYearSource,
    FinancialYearSummaryResponse,
)

_UNASSIGNED = "__unassigned__"
_NUMBER = re.compile(r"(?<![\w/])[+-]?\d[\d,]*(?:\.\d+)?")
_MONTHS = tuple(calendar.month_abbr[month] for month in range(1, 13))
_FY_MONTHS = tuple(range(4, 13)) + tuple(range(1, 4))
_METRIC_LABELS = {
    "electricity": "Electricity",
    "water": "Water",
    "waste": "Waste",
    "fuel": "Fuel",
    "emissions": "Emissions",
}
_DEFAULT_METRICS = ("electricity", "water", "waste")


@dataclass
class _DocumentFacts:
    document: Document
    run: ExtractionRun | None
    facts: list[ExtractedFact]


@dataclass
class _Candidate:
    document: Document
    fact: ExtractedFact
    value: Decimal
    unit: str
    metric: str
    start: date
    end: date
    treatment: str = "excluded"
    reason: str = ""

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _financial_year_start(value: str) -> int:
    match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", value.strip())
    if not match:
        raise HTTPException(status_code=422, detail="Use an Indian financial year such as 2025-26.")
    start_year = int(match.group(1))
    suffix = match.group(2)
    expected_end = start_year + 1
    supplied_end = int(suffix)
    valid_end = supplied_end == expected_end if len(suffix) == 4 else supplied_end == expected_end % 100
    if not valid_end:
        raise HTTPException(status_code=422, detail="A financial year must span April through March.")
    if start_year < 1 or expected_end > 9999:
        raise HTTPException(status_code=422, detail="The selected financial year is outside the supported range.")
    return start_year


def _fy_for_day(value: date) -> int:
    return value.year if value.month >= 4 else value.year - 1


def _fy_label(start_year: int) -> str:
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _decimal(value: Decimal | None, text: str | None = None) -> Decimal | None:
    if value is not None and value.is_finite():
        return value
    if not text:
        return None
    matches = _NUMBER.findall(text)
    if len(matches) != 1:
        return None
    try:
        parsed = Decimal(matches[0].replace(",", ""))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _decimal_text(value: Decimal) -> str:
    """Render exact Decimal digits without the database column's trailing scale."""
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _effective_value(fact: ExtractedFact) -> Decimal | None:
    if fact.reviewed_value_text is not None:
        return _decimal(fact.reviewed_value_number, fact.reviewed_value_text)
    return _decimal(fact.value_number, fact.value_text)


def _effective_label(fact: ExtractedFact) -> str:
    return fact.reviewed_label or fact.label


def _add_year_range(years: set[int], start: date | None, end: date | None) -> None:
    if start is None and end is None:
        return
    first_year = _fy_for_day(start or end)
    last_year = _fy_for_day(end or start)
    if last_year >= first_year:
        years.update(range(first_year, last_year + 1))


def _fact_in_years(fact: ExtractedFact, years: set[int]) -> None:
    _add_year_range(years, fact.period_start, fact.period_end)


def _document_organisation_key(document: Document) -> str:
    normalized = (document.entity_name or "").strip().casefold()
    return normalized or f"{_UNASSIGNED}:{document.id}"


def _safe_metadata_date(metadata: dict, key: str) -> date | None:
    return _as_date(metadata.get(key))


def _locator(fact: ExtractedFact) -> dict:
    locator = fact.locator if isinstance(fact.locator, dict) else {}
    return {
        "page": locator.get("page"),
        "sheet": locator.get("sheet"),
        "cell_range": locator.get("cell_range"),
    }


def _overlaps(left: _Candidate, right: _Candidate) -> bool:
    return left.start <= right.end and right.start <= left.end


def _month_index(value: date) -> int:
    return _FY_MONTHS.index(value.month)


def _month_label(month: int) -> str:
    return _MONTHS[month - 1]


def _series_key(fact: ExtractedFact) -> str:
    return (fact.series or "").strip().casefold()


def _is_annual_total(candidate: _Candidate, fy_start: date, fy_end: date) -> bool:
    if candidate.start != fy_start or candidate.end != fy_end:
        return False
    text = f"{candidate.fact.key} {candidate.fact.label} {candidate.fact.series or ''}".casefold().replace("_", " ")
    return bool(re.search(r"\b(total|subtotal|annual|yearly|summary)\b", text))


def _source_preference(candidate: _Candidate) -> tuple[int, int, datetime, str]:
    is_workbook = candidate.document.document_kind == "consumption_workbook"
    verified = candidate.fact.reviewed_verified if candidate.fact.reviewed_verified is not None else candidate.fact.verified
    return (
        0 if is_workbook else 1,
        0 if verified else 1,
        candidate.document.upload_timestamp,
        candidate.document.filename.casefold(),
    )


def _period_label(covered: set[int]) -> str:
    if not covered:
        return "No period coverage"
    ordered = sorted(covered)
    if ordered == list(range(ordered[0], ordered[-1] + 1)):
        first_month = _FY_MONTHS[ordered[0]]
        last_month = _FY_MONTHS[ordered[-1]]
        if len(ordered) == 1:
            return f"{_month_label(first_month)} only"
        return f"{_month_label(first_month)}–{_month_label(last_month)} only"
    return f"{len(covered)} of 12 months"


def _source(candidate: _Candidate) -> FinancialYearSource:
    fact = candidate.fact
    return FinancialYearSource(
        fact_id=fact.id,
        document_id=candidate.document.id,
        filename=candidate.document.filename,
        label=_effective_label(fact),
        metric=fact.metric,
        series=fact.series,
        unit=fact.unit,
        value=_decimal_text(candidate.value),
        value_text=(fact.reviewed_value_text if fact.reviewed_value_text is not None else fact.value_text),
        period_start=fact.period_start,
        period_end=fact.period_end,
        locator=_locator(fact),
        quote=fact.quote,
        verified=(
            fact.reviewed_verified
            if fact.reviewed_value_text is not None and fact.reviewed_verified is not None
            else fact.verified
        ),
        treatment=candidate.treatment,
        reason=candidate.reason,
    )


def _classify_candidates(candidates: list[_Candidate], fy_start: date, fy_end: date) -> tuple[list[_Candidate], list[_Candidate], list[str]]:
    gaps: list[str] = []
    in_scope: list[_Candidate] = []
    for candidate in candidates:
        if candidate.start < fy_start or candidate.end > fy_end:
            candidate.treatment = "excluded"
            candidate.reason = "The reported period extends beyond this financial year and cannot be split from the source."
            gaps.append(
                f"{candidate.document.filename} covers dates outside the selected financial year; "
                "the value was not prorated."
            )
            continue
        in_scope.append(candidate)

    # Two different reported values for the same exact period remain unresolved.
    by_period: dict[tuple[date, date], list[_Candidate]] = {}
    for candidate in in_scope:
        by_period.setdefault((candidate.start, candidate.end), []).append(candidate)
    conflicting_ids: set[UUID] = set()
    for (start, end), period_candidates in by_period.items():
        if len({item.value for item in period_candidates}) > 1:
            conflicting_ids.update(item.fact.id for item in period_candidates)
            label = _METRIC_LABELS.get(period_candidates[0].metric, period_candidates[0].metric.title())
            gaps.append(
                f"{label} sources report different values for the same period, "
                f"{start.isoformat()} to {end.isoformat()}; those versions were not added."
            )

    ordered = sorted(
        in_scope,
        key=lambda item: (
            item.days,
            item.start,
            item.end,
            *_source_preference(item),
            str(item.fact.id),
        ),
    )
    accepted: list[_Candidate] = []
    for candidate in ordered:
        if candidate.fact.id in conflicting_ids:
            candidate.treatment = "excluded"
            candidate.reason = "Conflicting reported values exist for this exact period; a source was not selected."
            continue
        overlap = next((item for item in accepted if _overlaps(candidate, item)), None)
        if overlap is None:
            candidate.treatment = "primary"
            candidate.reason = "Included in the financial-year total."
            accepted.append(candidate)
            continue
        if candidate.start == overlap.start and candidate.end == overlap.end and candidate.value == overlap.value:
            candidate.treatment = "corroboration"
            candidate.reason = "The period and reported value match an included source; this record is not added twice."
        else:
            candidate.treatment = "excluded"
            if candidate.days > overlap.days:
                candidate.reason = "Overlaps more detailed included periods; it was not added twice."
            else:
                candidate.reason = "Overlaps an included source period and needs review before it can be combined."
    return accepted, in_scope, gaps


def _build_metric(
    metric: str,
    unit: str | None,
    series: str | None,
    candidates: list[_Candidate],
    fy_start: date,
    fy_end: date,
) -> tuple[FinancialYearMetric, list[str]]:
    included, in_scope, gaps = _classify_candidates(candidates, fy_start, fy_end)
    month_values: dict[int, str] = {}
    covered: set[int] = set()
    for candidate in included:
        month = date(candidate.start.year, candidate.start.month, 1)
        while month <= candidate.end:
            if fy_start <= month <= fy_end:
                index = _month_index(month)
                covered.add(index)
                last_day = calendar.monthrange(month.year, month.month)[1]
                if candidate.start == month and candidate.end.day == last_day and candidate.end.month == month.month:
                    month_values[index] = _decimal_text(candidate.value)
            if month.month == 12:
                month = date(month.year + 1, 1, 1)
            else:
                month = date(month.year, month.month + 1, 1)

    missing_indices = [index for index in range(12) if index not in covered]
    if missing_indices:
        missing = ", ".join(_month_label(_FY_MONTHS[index]) for index in missing_indices)
        label = _METRIC_LABELS.get(metric, metric.title())
        if included:
            gaps.append(f"{label} has no usable source values for {missing}; missing months are not treated as zero.")

    value = sum((item.value for item in included), Decimal("0")) if included else None
    has_conflict = any(item.treatment == "excluded" and "Conflicting" in item.reason for item in in_scope)
    if not included:
        status = "conflict" if has_conflict else "no_data"
        method = "No usable source values"
    elif has_conflict:
        status = "conflict"
        method = "Partial sum; conflicting periods excluded"
    elif all(item.start.day == 1 and item.end.day == calendar.monthrange(item.end.year, item.end.month)[1] and item.start.month == item.end.month for item in included):
        status = "calculated" if len(included) > 1 else "reported"
        method = "Calculated monthly sum" if len(included) > 1 else "Source-reported monthly value"
    elif len(included) == 1:
        status = "reported"
        method = "Source-reported period value"
    else:
        status = "calculated"
        method = "Calculated sum of non-overlapping reported periods"

    calculation = None
    if value is not None and len(included) > 1:
        calculation = (
            " + ".join(_decimal_text(item.value) for item in included)
            + f" = {_decimal_text(value)}"
            + (f" {unit}" if unit else "")
        )

    if value is not None:
        for candidate in in_scope:
            if candidate.treatment != "excluded" or candidate.start != fy_start or candidate.end != fy_end:
                continue
            if candidate.value == value and included:
                candidate.treatment = "corroboration"
                candidate.reason = "The reported full-year total matches the included detailed periods; it is not added twice."
            elif included:
                gaps.append(
                    f"{candidate.document.filename} reports {_decimal_text(candidate.value)} {unit or ''} "
                    f"for the full financial year, while included detailed periods sum to "
                    f"{_decimal_text(value)} {unit or ''}; the overlapping annual value was excluded."
                )
    notes: list[str] = []
    if included and any(item.start != date(item.start.year, item.start.month, 1) or item.end.day != calendar.monthrange(item.end.year, item.end.month)[1] or item.start.month != item.end.month for item in included):
        if len(included) == 1:
            notes.append("Period coverage is shown; the source does not provide a monthly split.")
    if has_conflict:
        notes.append("Conflicting source values remain unresolved and are excluded from the sum.")

    source_ids = list(dict.fromkeys(item.document.id for item in included))
    months = [
        FinancialYearMonth(
            label=_month_label(_FY_MONTHS[index]),
            covered=index in covered,
            value=month_values.get(index),
        )
        for index in range(12)
    ]
    label = _METRIC_LABELS.get(metric, metric.title())
    return (
        FinancialYearMetric(
            metric=metric,
            label=label,
            series=series,
            unit=unit,
            value=_decimal_text(value) if value is not None else None,
            status=status,
            period_label=_period_label(covered),
            method=method,
            calculation=calculation,
            months_covered=len(covered),
            months=months,
            source_document_ids=source_ids,
            note=" ".join(notes) or None,
        ),
        gaps,
    )


def _meter_reading_gaps(
    metric: str,
    unit: str | None,
    docs: list[_DocumentFacts],
    candidates: list[_Candidate],
    fy_start: date,
    fy_end: date,
) -> list[str]:
    if metric != "water" or not unit:
        return []
    gaps: list[str] = []
    for document_facts in docs:
        if document_facts.run is None:
            continue
        facts = [
            fact
            for fact in document_facts.facts
            if fact.metric == metric and fact.unit == unit and fact.category == "meter_reading"
        ]
        previous = [
            fact for fact in facts
            if "previous" in f"{fact.key} {_effective_label(fact)}".casefold()
        ]
        current = [
            fact for fact in facts
            if "current" in f"{fact.key} {_effective_label(fact)}".casefold()
        ]
        if len(previous) != 1 or len(current) != 1:
            continue
        readings = (previous[0], current[0])
        if any(
            fact.period_start is None
            or fact.period_start < fy_start
            or fact.period_start > fy_end
            for fact in readings
        ):
            continue
        text = " ".join(f"{fact.key} {fact.label}" for fact in document_facts.facts).casefold()
        if "multiplier" in text or "multiplying factor" in text:
            continue
        previous_value = _effective_value(previous[0])
        current_value = _effective_value(current[0])
        if previous_value is None or current_value is None:
            continue
        billed = [
            item for item in candidates
            if item.document.id == document_facts.document.id
            and item.fact.category == "consumption"
            and item.unit == unit
        ]
        if len(billed) != 1:
            continue
        meter_delta = current_value - previous_value
        difference = billed[0].value - meter_delta
        if difference:
            gaps.append(
                f"{document_facts.document.filename} reports {_decimal_text(billed[0].value)} {unit} billed, "
                f"while its meter readings differ by {_decimal_text(meter_delta)} {unit} "
                f"({_decimal_text(abs(difference))} {unit} difference)."
            )
    return gaps


async def get_financial_year_summary(
    session: AsyncSession,
    user_id: int,
    financial_year: str | None,
    organisation: str | None,
    document_ids: list[UUID] | None,
    selected_document_scope: bool,
) -> FinancialYearSummaryResponse:
    documents_result = await session.execute(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.upload_timestamp.desc(), Document.filename)
    )
    all_documents = list(documents_result.scalars().all())
    document_by_id = {document.id: document for document in all_documents}

    runs_by_document: dict[UUID, ExtractionRun] = {}
    if document_by_id:
        runs_result = await session.execute(
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
        for run in runs_result.scalars().all():
            runs_by_document.setdefault(run.document_id, run)

    facts_by_run: dict[UUID, list[ExtractedFact]] = {run.id: [] for run in runs_by_document.values()}
    if facts_by_run:
        facts_result = await session.execute(
            select(ExtractedFact)
            .where(ExtractedFact.extraction_run_id.in_(facts_by_run))
            .order_by(ExtractedFact.created_at, ExtractedFact.key)
        )
        for fact in facts_result.scalars().all():
            facts_by_run.setdefault(fact.extraction_run_id, []).append(fact)

    document_facts = [
        _DocumentFacts(
            document=document,
            run=runs_by_document.get(document.id),
            facts=facts_by_run.get(runs_by_document[document.id].id, []) if document.id in runs_by_document else [],
        )
        for document in all_documents
    ]

    years_by_organisation: dict[str, set[int]] = {}
    for item in document_facts:
        document_years: set[int] = set()
        for fact in item.facts:
            _fact_in_years(fact, document_years)
        if item.run:
            metadata = item.run.result_metadata or {}
            start = _safe_metadata_date(metadata, "period_start")
            end = _safe_metadata_date(metadata, "period_end")
            _add_year_range(document_years, start, end)
        years_by_organisation.setdefault(
            _document_organisation_key(item.document), set()
        ).update(document_years)

    options_by_org: dict[str, str] = {}
    for document in all_documents:
        key = _document_organisation_key(document)
        label = (document.entity_name or "").strip() or f"Organisation not stated · {document.filename}"
        options_by_org.setdefault(key, label)
    organisation_options = [
        FinancialYearOrganisationOption(value=key, label=label)
        for key, label in sorted(options_by_org.items(), key=lambda item: item[1].casefold())
    ]
    selected_org = organisation
    if selected_org is None and organisation_options:
        selected_org = organisation_options[0].value
    if selected_org is not None and selected_org not in options_by_org:
        raise HTTPException(status_code=422, detail="Select an organisation from your documents.")

    available_years = years_by_organisation.get(selected_org or "", set())
    if not available_years:
        available_years = set().union(*years_by_organisation.values()) if years_by_organisation else set()
    if available_years:
        ordered_years = sorted(available_years)
    else:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        ordered_years = [_fy_for_day(today)]
    year_options = [
        FinancialYearOption(value=_fy_label(year), label=f"FY {_fy_label(year)}")
        for year in reversed(ordered_years)
    ]
    selected_year_start = _financial_year_start(financial_year) if financial_year else ordered_years[-1]
    if selected_year_start not in ordered_years:
        year_options.insert(
            0,
            FinancialYearOption(
                value=_fy_label(selected_year_start),
                label=f"FY {_fy_label(selected_year_start)}",
            ),
        )
    fy_start = date(selected_year_start, 4, 1)
    fy_end = date(selected_year_start + 1, 3, 31)

    org_documents = [
        item for item in document_facts
        if selected_org is not None and _document_organisation_key(item.document) == selected_org
    ]
    valid_scope_ids = {item.document.id for item in org_documents}
    requested_ids = set(document_ids or [])
    if selected_document_scope:
        selected_ids = requested_ids
    elif document_ids is None:
        selected_ids = valid_scope_ids
    else:
        selected_ids = requested_ids
    if any(document_id not in document_by_id for document_id in selected_ids):
        raise HTTPException(status_code=404, detail="One or more selected documents were not found.")
    if any(document_id not in valid_scope_ids for document_id in selected_ids):
        raise HTTPException(status_code=422, detail="Selected documents must belong to the chosen organisation.")
    scoped_docs = [item for item in org_documents if item.document.id in selected_ids]

    document_options = [
        FinancialYearDocumentOption(
            id=item.document.id,
            filename=item.document.filename,
            status=item.document.status,
            organisation=item.document.entity_name,
            has_successful_extraction=item.run is not None,
            selected=item.document.id in selected_ids,
        )
        for item in org_documents
    ]

    candidates_by_group: dict[tuple[str, str, str], list[_Candidate]] = {}
    candidate_by_fact_id: dict[UUID, _Candidate] = {}
    source_records: list[FinancialYearSource] = []
    gaps: list[str] = []
    excluded_docs: list[FinancialYearExcludedDocument] = []

    for item in document_facts:
        document = item.document
        if _document_organisation_key(document) != selected_org:
            excluded_docs.append(
                FinancialYearExcludedDocument(
                    id=document.id,
                    filename=document.filename,
                    organisation=document.entity_name,
                    status=document.status,
                    reason="Different organisation; kept outside this summary scope.",
                )
            )
            continue
        if document.id not in selected_ids:
            excluded_docs.append(
                FinancialYearExcludedDocument(
                    id=document.id,
                    filename=document.filename,
                    organisation=document.entity_name,
                    status=document.status,
                    reason="Outside the selected document scope.",
                )
            )
            continue
        if item.run is None:
            reason = {
                "pending": "Document is waiting to be processed; no usable facts are available yet.",
                "processing": "Document is still processing; no completed extraction is available yet.",
                "failed": "Document processing failed; no usable extracted facts are available.",
            }.get(document.status, "No completed extraction is available.")
            excluded_docs.append(
                FinancialYearExcludedDocument(
                    id=document.id,
                    filename=document.filename,
                    organisation=document.entity_name,
                    status=document.status,
                    reason=reason,
                )
            )
            continue

        doc_has_relevant_source = False
        for fact in item.facts:
            if fact.metric not in _METRIC_LABELS:
                continue
            if fact.category == "meter_reading":
                if fact.period_start and fy_start <= fact.period_start <= fy_end:
                    value = _effective_value(fact)
                    if value is not None:
                        source_records.append(
                            FinancialYearSource(
                                fact_id=fact.id,
                                document_id=document.id,
                                filename=document.filename,
                                label=_effective_label(fact),
                                metric=fact.metric,
                                series=fact.series,
                                unit=fact.unit,
                                value=_decimal_text(value),
                                value_text=(fact.reviewed_value_text if fact.reviewed_value_text is not None else fact.value_text),
                                period_start=fact.period_start,
                                period_end=fact.period_end,
                                locator=_locator(fact),
                                quote=fact.quote,
                                verified=fact.reviewed_verified if fact.reviewed_verified is not None else fact.verified,
                                treatment="supporting",
                                reason="Meter reading check only; it is not added as consumption.",
                            )
                        )
                continue
            if fact.category not in {"consumption", "quantity"}:
                continue
            if fact.origin != "reported":
                continue
            start = fact.period_start
            end = fact.period_end
            if start is None or end is None or end < start:
                if start is None or start <= fy_end and (end is None or end >= fy_start):
                    gaps.append(f"{document.filename} has a {fact.metric} value without a clear period and it was not included.")
                continue
            if end < fy_start or start > fy_end:
                continue
            doc_has_relevant_source = True
            unit = (fact.unit or "").strip()
            value = _effective_value(fact)
            if not unit:
                gaps.append(f"{document.filename} reports {fact.metric} without a unit; that value was not combined.")
                continue
            if "/" in unit or re.search(r"\bper\b", unit.casefold()):
                gaps.append(f"{document.filename} reports {fact.metric} in a rate or intensity unit ({unit}); it was not totalled.")
                continue
            if value is None:
                gaps.append(f"{document.filename} reports {fact.metric} without a usable numeric value; it was not included.")
                continue
            candidate = _Candidate(
                document=document,
                fact=fact,
                value=value,
                unit=unit,
                metric=fact.metric,
                start=start,
                end=end,
            )
            candidates_by_group.setdefault((fact.metric, unit, _series_key(fact)), []).append(candidate)
            candidate_by_fact_id[fact.id] = candidate

        if not doc_has_relevant_source and not any(source.document_id == document.id for source in source_records):
            excluded_docs.append(
                FinancialYearExcludedDocument(
                    id=document.id,
                    filename=document.filename,
                    organisation=document.entity_name,
                    status=document.status,
                    reason="No usable physical quantity facts cover this financial year.",
                )
            )

    candidates_by_resource: dict[tuple[str, str], list[_Candidate]] = {}
    for (metric, unit, _series), candidates in candidates_by_group.items():
        candidates_by_resource.setdefault((metric, unit), []).extend(candidates)
    for resource_candidates in candidates_by_resource.values():
        resource_candidates.sort(
            key=lambda item: (
                item.days,
                item.start,
                item.end,
                *_source_preference(item),
                str(item.fact.id),
            )
        )
        annual_totals = [
            candidate for candidate in resource_candidates
            if _is_annual_total(candidate, fy_start, fy_end)
            and any(
                other.document.id == candidate.document.id
                and other.fact.id != candidate.fact.id
                and fy_start <= other.start
                and other.end <= fy_end
                and other.days < candidate.days
                and _overlaps(other, candidate)
                for other in resource_candidates
            )
        ]
        for candidate in annual_totals:
            candidate.treatment = "excluded"
            candidate.reason = "Full-year total overlaps more detailed records from the same source; it is not added twice."
        seen: list[_Candidate] = []
        for candidate in resource_candidates:
            if candidate.treatment == "excluded" and candidate.reason:
                continue
            match = next(
                (
                    item for item in seen
                    if _series_key(item.fact) != _series_key(candidate.fact)
                    and item.start == candidate.start
                    and item.end == candidate.end
                    and item.value == candidate.value
                ),
                None,
            )
            if match:
                candidate.treatment = "corroboration"
                candidate.reason = "The period and reported value match another named series; this record is not added twice."
            else:
                seen.append(candidate)

    metric_groups: dict[str, list[tuple[str, str | None, list[_Candidate]]]] = {}
    for (metric, unit, _series), candidates in candidates_by_group.items():
        primary_candidates = [
            item for item in candidates
            if item.treatment != "corroboration"
            and not (item.treatment == "excluded" and item.reason)
        ]
        if primary_candidates:
            display_series = next(
                (item.fact.series.strip() for item in candidates if item.fact.series and item.fact.series.strip()),
                None,
            )
            metric_groups.setdefault(metric, []).append((unit, display_series, primary_candidates))
    metrics: list[FinancialYearMetric] = []
    for metric in (*_DEFAULT_METRICS, "fuel", "emissions"):
        groups = sorted(metric_groups.get(metric, []), key=lambda item: (item[0].casefold(), (item[1] or "").casefold()))
        if not groups:
            metrics.append(
                FinancialYearMetric(
                    metric=metric,
                    label=_METRIC_LABELS[metric],
                    series=None,
                    unit=None,
                    value=None,
                    status="no_data",
                    period_label="No usable records",
                    method="No usable source values",
                    calculation=None,
                    months_covered=0,
                    months=[
                        FinancialYearMonth(label=_month_label(month), covered=False, value=None)
                        for month in _FY_MONTHS
                    ],
                    source_document_ids=[],
                )
            )
            continue
        for unit, series, candidates in groups:
            metric_summary, metric_gaps = _build_metric(metric, unit, series, candidates, fy_start, fy_end)
            metrics.append(metric_summary)
            gaps.extend(metric_gaps)
            meter_gaps = _meter_reading_gaps(metric, unit, scoped_docs, candidates, fy_start, fy_end)
            gaps.extend(meter_gaps)
            if meter_gaps:
                note = f"Billed value retained. {meter_gaps[0]}"
                metric_summary.note = f"{metric_summary.note} {note}".strip() if metric_summary.note else note

    for annual in candidate_by_fact_id.values():
        if annual.treatment != "excluded" or not _is_annual_total(annual, fy_start, fy_end):
            continue
        detailed = [
            item for item in candidate_by_fact_id.values()
            if item.document.id == annual.document.id
            and item.metric == annual.metric
            and item.unit == annual.unit
            and item.fact.id != annual.fact.id
            and item.days < annual.days
            and item.treatment == "primary"
        ]
        if not detailed:
            continue
        detailed_total = sum((item.value for item in detailed), Decimal("0"))
        if detailed_total == annual.value:
            annual.treatment = "corroboration"
            annual.reason = "The full-year total matches detailed source records; it is not added twice."
        else:
            gaps.append(
                f"{annual.document.filename} reports {_decimal_text(annual.value)} {annual.unit} for the full financial year, "
                f"while its included detailed records sum to {_decimal_text(detailed_total)} {annual.unit}; "
                "the full-year figure was excluded because the periods overlap."
            )

    for candidate in candidate_by_fact_id.values():
        source_records.append(_source(candidate))
    # Put reported sources in document order and then by their source period.
    source_records.sort(
        key=lambda source: (
            document_by_id[source.document_id].upload_timestamp,
            source.period_start or date.min,
            source.filename.casefold(),
            str(source.fact_id),
        )
    )
    unique_gaps = list(dict.fromkeys(gaps))
    for metric in metrics:
        if metric.value is None and metric.metric in _DEFAULT_METRICS and not any(
            f.metric == metric.metric and f.unit is not None for f in metrics
        ):
            unique_gaps.append(f"No usable {metric.label.casefold()} records are available for this financial year; this is not zero.")

    primary_documents = {
        source.document_id for source in source_records if source.treatment == "primary"
    }
    corroborating_documents = {
        source.document_id for source in source_records if source.treatment == "corroboration"
    }
    has_any_data = any(metric.value is not None or metric.status == "conflict" for metric in metrics)
    coverage_metrics = [
        metric for metric in metrics
        if metric.metric in _DEFAULT_METRICS or metric.value is not None
    ]
    has_complete_coverage = has_any_data and all(
        metric.months_covered == 12 for metric in coverage_metrics
    )
    coverage_status = "no_data" if not has_any_data else "complete" if has_complete_coverage else "partial"

    return FinancialYearSummaryResponse(
        financial_year=_fy_label(selected_year_start),
        financial_year_start=fy_start,
        financial_year_end=fy_end,
        financial_year_options=year_options,
        organisation=selected_org,
        organisation_options=organisation_options,
        documents=document_options,
        selected_document_ids=[item.document.id for item in scoped_docs],
        primary_source_count=len(primary_documents),
        corroborating_source_count=len(corroborating_documents - primary_documents),
        coverage_status=coverage_status,
        metrics=metrics,
        sources=source_records,
        excluded_documents=excluded_docs,
        gaps=list(dict.fromkeys(unique_gaps)),
    )
