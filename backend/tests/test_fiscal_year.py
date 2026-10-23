import unittest
from datetime import date

from services.fiscal_year import (
    financial_year_bounds,
    financial_year_for_period,
    financial_year_label,
    financial_year_start_year,
)


class FiscalYearTests(unittest.TestCase):
    def test_april_first_starts_new_financial_year(self) -> None:
        self.assertEqual(financial_year_start_year(date(2025, 3, 31)), 2024)
        self.assertEqual(financial_year_start_year(date(2025, 4, 1)), 2025)

    def test_label_and_bounds(self) -> None:
        self.assertEqual(financial_year_label(2024), "FY 2024-25")
        self.assertEqual(
            financial_year_bounds(2024),
            (date(2024, 4, 1), date(2025, 3, 31)),
        )

    def test_period_is_assigned_only_when_contained_in_one_fy(self) -> None:
        self.assertEqual(
            financial_year_for_period(date(2024, 4, 1), date(2025, 3, 31)),
            2024,
        )
        self.assertIsNone(
            financial_year_for_period(date(2025, 3, 1), date(2025, 4, 30))
        )

    def test_invalid_or_incomplete_period_has_no_fy(self) -> None:
        self.assertIsNone(financial_year_for_period(None, date(2025, 1, 1)))
        self.assertIsNone(
            financial_year_for_period(date(2025, 1, 2), date(2025, 1, 1))
        )


if __name__ == "__main__":
    unittest.main()
