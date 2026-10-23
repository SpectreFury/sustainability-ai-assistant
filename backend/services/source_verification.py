import re
import unicodedata
from decimal import Decimal, InvalidOperation

from openpyxl.utils import column_index_from_string, get_column_letter

from schemas.extraction import Locator, Segment

_NUMBER = re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?")
_CELL_REF = re.compile(r"^([A-Z]{1,3})(\d+)$", re.IGNORECASE)


def _normalize_source_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[‐-―−]", "-", text)
    text = re.sub(r"[‘’`]", "'", text).replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", "", text)


def _numbers_in_text(text: str) -> list[Decimal]:
    numbers: list[Decimal] = []
    for match in _NUMBER.findall(text):
        try:
            numbers.append(Decimal(match.replace(",", "")))
        except InvalidOperation:
            continue
    return numbers


def _numbers_match(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= Decimal("0.005")


def expand_cell_range(cell_range: str) -> list[str]:
    parts = cell_range.replace("$", "").upper().split(":")
    if len(parts) == 1:
        return parts if _CELL_REF.fullmatch(parts[0]) else []
    first, last = (_CELL_REF.fullmatch(part) for part in parts[:2])
    if first is None or last is None:
        return []
    column_start, column_end = sorted(
        (column_index_from_string(first[1]), column_index_from_string(last[1]))
    )
    row_start, row_end = sorted((int(first[2]), int(last[2])))
    return [
        f"{get_column_letter(column)}{row}"
        for row in range(row_start, row_end + 1)
        for column in range(column_start, column_end + 1)
    ]


def _find_source_segments(segments: list[Segment], locator: Locator) -> list[Segment]:
    if locator.page is not None:
        return [segment for segment in segments if segment.locator.page == locator.page]
    if not locator.sheet:
        return []
    sheet_segments = [
        segment
        for segment in segments
        if segment.locator.sheet == locator.sheet and segment.cells is not None
    ]
    if not locator.cell_range:
        return sheet_segments
    references = set(expand_cell_range(locator.cell_range))
    return [
        segment for segment in sheet_segments if references & set(segment.cells or {})
    ]


def _cell_values_for_range(
    segments: list[Segment], sheet: str, cell_range: str
) -> list[float | str]:
    references = expand_cell_range(cell_range)
    values: dict[str, float | str] = {}
    for segment in segments:
        if segment.locator.sheet == sheet and segment.cells:
            values.update(segment.cells)
    return [values[reference] for reference in references if reference in values]


_CELL_TOKEN = re.compile(
    r"(?<![A-Za-z])([A-Z]{1,3}\d+)=(.*?)(?=\s*(?:\||\.\.\.|…|\n|$))",
    re.IGNORECASE,
)


def parse_cell_number(value: float | str | int | Decimal) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = value.strip().replace(",", "").removesuffix("%").strip()
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _same_cell_value(quoted: str, actual: float | str) -> bool:
    actual_number = parse_cell_number(actual)
    quoted_number = parse_cell_number(quoted)
    if actual_number is not None and quoted_number is not None:
        return _numbers_match(quoted_number, actual_number)
    return _normalize_source_text(quoted) == _normalize_source_text(str(actual))


def _verify_cell_quote(
    segments: list[Segment], locator: Locator, quote: str
) -> tuple[bool, str] | None:
    tokens = _CELL_TOKEN.findall(quote)
    if not tokens:
        return None
    allowed = {
        reference.upper() for reference in expand_cell_range(locator.cell_range or "")
    }
    cells: dict[str, float | str] = {}
    for segment in segments:
        if segment.locator.sheet == locator.sheet and segment.cells:
            cells.update({key.upper(): value for key, value in segment.cells.items()})
    for raw_reference, quoted_value in tokens:
        reference = raw_reference.upper()
        if reference not in allowed:
            return False, f"{reference} is outside {locator.label()}"
        if reference not in cells:
            return False, f"{locator.sheet}!{reference} is empty"
        if not _same_cell_value(quoted_value, cells[reference]):
            return False, f"{locator.sheet}!{reference} holds {cells[reference]}, not {quoted_value}"
    return True, f"All {len(tokens)} quoted cells match {locator.label()}"


def _verify_quote_lines(text: str, quote: str) -> bool:
    lines = [line for line in quote.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    page = _normalize_source_text(text)
    substantial = [line for line in lines if len(line.split()) >= 3]
    return bool(substantial) and all(_normalize_source_text(line) in page for line in lines)


def verify_fact_source(
    segments: list[Segment],
    locator: Locator,
    quote: str | None,
    value: Decimal | float | int | None = None,
    *,
    structured: bool = False,
) -> tuple[bool, str]:
    found = _find_source_segments(segments, locator)
    if not found:
        return False, f"No {locator.label()} in this document"
    if any(segment.scanned for segment in found):
        return False, f"{locator.label()} is a scanned page; read from the image, not checkable"

    expected = parse_cell_number(value) if value is not None else None
    if locator.sheet and locator.cell_range:
        values = _cell_values_for_range(segments, locator.sheet, locator.cell_range)
        if not values:
            return False, f"{locator.label()} is empty"
        numeric_values = [
            number
            for item in values
            if (number := parse_cell_number(item)) is not None
        ]
        if structured:
            if quote and (cell_check := _verify_cell_quote(segments, locator, quote)):
                valid, reason = cell_check
                if not valid or expected is None or any(
                    _numbers_match(number, expected) for number in numeric_values
                ):
                    return valid, reason
        if expected is not None:
            if any(_numbers_match(number, expected) for number in numeric_values):
                return True, f"Value found in {locator.label()}"
            return False, f"{locator.label()} holds {_summarize_values(values)}, not {expected:g}"
        if quote and any(
            _normalize_source_text(quote) in _normalize_source_text(str(item))
            for item in values
        ):
            return True, f"Quote matches {locator.label()}"
        quoted_numbers = _numbers_in_text(quote or "")
        if quoted_numbers and all(
            any(_numbers_match(quoted, number) for number in numeric_values)
            for quoted in quoted_numbers
        ):
            return True, f"Numbers in quote match {locator.label()}"
        return False, f"Quote not found in {locator.label()}"

    text = "\n".join(segment.text for segment in found)
    page_numbers = _numbers_in_text(text)
    if structured and expected is not None:
        expected = abs(expected)
    if quote:
        quoted_numbers = _numbers_in_text(quote)
        if _normalize_source_text(quote) in _normalize_source_text(text):
            if (
                expected is None
                or any(_numbers_match(number, expected) for number in quoted_numbers)
                or any(_numbers_match(number, expected) for number in page_numbers)
            ):
                return True, f"Quote found on {locator.label()}"
            return False, f"Quote found on {locator.label()} but the value {expected:g} is not"
        if structured and _verify_quote_lines(text, quote):
            if expected is None or any(
                _numbers_match(number, expected) for number in page_numbers
            ):
                return True, f"Quote found line by line on {locator.label()} (multi-column layout)"
        if quoted_numbers and all(
            any(_numbers_match(quoted, number) for number in page_numbers)
            for quoted in quoted_numbers
        ):
            return True, f"Quote paraphrased; its numbers appear on {locator.label()}"
    if expected is not None and any(
        _numbers_match(number, expected) for number in page_numbers
    ):
        return True, f"Value appears on {locator.label()} (quote not verbatim)"
    return False, f"Quote not found on {locator.label()}"


def _summarize_values(values: list[float | str]) -> str:
    shown = ", ".join(str(value) for value in values[:4])
    return shown + ("…" if len(values) > 4 else "")
