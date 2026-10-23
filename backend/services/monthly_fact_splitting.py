import calendar
import re
from datetime import date
from decimal import Decimal

from schemas.extraction import Fact, Locator, Segment
from services.source_verification import (
    expand_cell_range,
    parse_cell_number,
    verify_fact_source,
)

_MONTHS = {
    name.lower(): month
    for month in range(1, 13)
    for name in (calendar.month_name[month], calendar.month_abbr[month])
}
_ISO_MONTH = re.compile(r"^(\d{4})-(\d{2})-\d{2}")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_CELL_REF = re.compile(r"^([A-Z]{1,3})(\d+)$")


def _cell_parts(reference: str) -> tuple[str, int]:
    match = _CELL_REF.fullmatch(reference)
    if not match:
        raise ValueError(f"Invalid spreadsheet reference: {reference}")
    return match.group(1), int(match.group(2))


def _row_month(row: list[float | str], year: int | None) -> tuple[int, int] | None:
    found: tuple[int, int] | None = None
    for value in row:
        if not isinstance(value, str):
            continue
        if match := _ISO_MONTH.match(value):
            return int(match[1]), int(match[2])
        months = {
            _MONTHS[word]
            for word in re.split(r"[\s\-/'.,]+", value.lower())
            if word in _MONTHS
        }
        if len(months) > 1:
            return None
        if months and not found:
            named_year = _YEAR.search(value)
            selected_year = int(named_year[0]) if named_year else year
            if selected_year:
                found = (selected_year, months.pop())
    return found


def _per_cell(fact: Fact, rows: dict[str, dict[int, list[tuple[str, float | str]]]], segments: list[Segment]) -> list[Fact] | None:
    locator = fact.locator
    if fact.origin != "reported" or fact.value_number is not None:
        return None
    if not locator.sheet or not locator.cell_range:
        return None
    sheet_rows = rows.get(locator.sheet)
    references = expand_cell_range(locator.cell_range)
    if not sheet_rows or len(references) < 2:
        return None
    if len({_cell_parts(reference)[0] for reference in references}) != 1:
        return None

    year = None
    if fact.period_start:
        try:
            year = date.fromisoformat(fact.period_start).year
        except ValueError:
            return None
    split: list[Fact] = []
    for reference in references:
        row_number = _cell_parts(reference)[1]
        row = sheet_rows.get(row_number, [])
        cell_value = next((value for cell, value in row if cell == reference), None)
        number = parse_cell_number(cell_value) if cell_value is not None else None
        when = _row_month([value for cell, value in row if cell != reference], year)
        if number is None or when is None:
            return None
        target_year, month = when
        rendered = str(number.normalize())
        locator_for_cell = Locator(sheet=locator.sheet, cell_range=reference)
        verified, reason = verify_fact_source(
            segments, locator_for_cell, rendered, number
        )
        split.append(
            fact.model_copy(
                update={
                    "key": f"{fact.key}_{target_year}_{month:02d}",
                    "label": f"{fact.label}, {calendar.month_abbr[month]} {target_year}",
                    "series": fact.series or fact.label,
                    "value_text": f"{rendered} {fact.unit}".strip(),
                    "value_number": number,
                    "period_start": date(target_year, month, 1).isoformat(),
                    "period_end": date(
                        target_year, month, calendar.monthrange(target_year, month)[1]
                    ).isoformat(),
                    "locator": locator_for_cell,
                    "quote": rendered,
                    "verified": verified,
                    "verification": reason,
                }
            )
        )
    return split


def split_monthly_column_facts(
    facts: list[Fact], segments: list[Segment]
) -> list[Fact]:
    rows: dict[str, dict[int, list[tuple[str, float | str]]]] = {}
    for segment in segments:
        if not segment.cells or not segment.locator.sheet:
            continue
        sheet_rows = rows.setdefault(segment.locator.sheet, {})
        for reference, value in segment.cells.items():
            sheet_rows.setdefault(_cell_parts(reference)[1], []).append((reference, value))
    if not rows:
        return facts
    result: list[Fact] = []
    for fact in facts:
        result.extend(_per_cell(fact, rows, segments) or [fact])
    return result
