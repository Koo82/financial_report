from __future__ import annotations

import re
import unittest
from datetime import date
from unittest.mock import patch

from financial_report import treasury

MODERN_CSV = """Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
11/10/2026,4.05,4.16,4.21,4.30,4.28,4.38,4.56,4.73,4.74,4.81,4.89,4.98,5.39,5.35
11/09/2026,4.04,4.13,4.19,4.24,4.20,4.26,4.38,4.56,4.58,4.67,4.76,4.88,5.29,5.26
11/06/2026,4.02,4.07,4.15,4.19,4.19,4.23,4.33,4.51,4.59,4.64,4.74,4.86,5.29,5.26
"""

OLDER_CSV = """Date,"1 Mo","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
12/29/2023,5.60,5.59,5.40,5.41,5.26,4.79,4.23,4.01,3.84,3.88,3.88,4.20,4.03
"""


class ParseCsvTests(unittest.TestCase):
    def test_parses_columns_by_name_and_sorts(self) -> None:
        points = treasury.parse_csv(MODERN_CSV)
        self.assertEqual(
            [point.date for point in points],
            ["2026-11-06", "2026-11-09", "2026-11-10"],
        )
        self.assertEqual(points[-1].values, {
            "us5y": 4.81,
            "us10y": 4.98,
            "us30y": 5.35,
        })

    def test_handles_older_header_without_extra_column(self) -> None:
        points = treasury.parse_csv(OLDER_CSV)
        self.assertEqual(points[0].values, {
            "us5y": 3.84,
            "us10y": 3.88,
            "us30y": 4.03,
        })

    def test_rows_missing_a_yield_are_skipped(self) -> None:
        rows = MODERN_CSV.splitlines()
        rows[1] = rows[1].replace(",4.81,", ",,")
        points = treasury.parse_csv("\n".join(rows))
        self.assertNotIn("2026-11-10", [point.date for point in points])

    def test_unexpected_header_raises(self) -> None:
        with self.assertRaises(treasury.TreasuryError):
            treasury.parse_csv("Date,5 Yr\n11/10/2026,4.81\n")

    def test_empty_csv_raises(self) -> None:
        with self.assertRaises(treasury.TreasuryError):
            treasury.parse_csv("Date,\"5 Yr\",\"10 Yr\",\"30 Yr\"\n")


class FetchTests(unittest.TestCase):
    def test_fetches_every_year_in_the_window(self) -> None:
        calls: list[int] = []

        def fake(url: str, **_: object) -> str:
            year = int(re.search(r"\.csv/(\d{4})/", url).group(1))
            calls.append(year)
            month, day = (11, 10) if year == 2026 else (12, 29)
            return (
                'Date,"5 Yr","10 Yr","30 Yr"\n'
                f"{month:02d}/{day:02d}/{year},4.1,4.2,4.3\n"
            )

        with patch.object(treasury, "get_text", side_effect=fake):
            points = treasury.fetch_points(
                days=1200,
                today=date(2026, 11, 12),
                sleep=lambda _: None,
            )

        self.assertEqual(calls, [2023, 2024, 2025, 2026])
        self.assertEqual(len(points), 4)
        self.assertEqual(points[-1].date, "2026-11-10")

    def test_only_recent_year_is_requested_for_short_window(self) -> None:
        calls: list[int] = []

        def fake(url: str, **_: object) -> str:
            calls.append(int(re.search(r"\.csv/(\d{4})/", url).group(1)))
            return 'Date,"5 Yr","10 Yr","30 Yr"\n11/10/2026,4.1,4.2,4.3\n'

        with patch.object(treasury, "get_text", side_effect=fake):
            points = treasury.fetch_points(
                days=30,
                today=date(2026, 11, 12),
                sleep=lambda _: None,
            )

        self.assertEqual(calls, [2026])
        self.assertEqual(len(points), 1)


if __name__ == "__main__":
    unittest.main()
