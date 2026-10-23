from datetime import date


def financial_year_start_year(value: date) -> int:
    """Return the starting calendar year for India's April–March financial year."""
    return value.year if value.month >= 4 else value.year - 1


def financial_year_label(start_year: int) -> str:
    return f"FY {start_year}-{(start_year + 1) % 100:02d}"


def financial_year_bounds(start_year: int) -> tuple[date, date]:
    """Return inclusive dates for the financial year starting April 1."""
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def financial_year_for_period(
    period_start: date | None,
    period_end: date | None,
) -> int | None:
    """Return an FY only when the entire reporting period falls within one FY."""
    if period_start is None or period_end is None or period_end < period_start:
        return None
    start_year = financial_year_start_year(period_start)
    if financial_year_start_year(period_end) != start_year:
        return None
    return start_year
