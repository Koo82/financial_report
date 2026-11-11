from __future__ import annotations

import unittest
from datetime import datetime

from financial_report import yahoo
from financial_report.store import KST


def chart_payload(timestamps: list[float], closes: list[float | None]) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "USDKRW=X"},
                    "timestamp": timestamps,
                    "indicators": {"quote": [{"close": closes}]},
                }
            ],
            "error": None,
        }
    }


def stamp(year: int, month: int, day: int) -> float:
    return datetime(year, month, day, 9, 0, tzinfo=KST).timestamp()


class ParseChartPayloadTests(unittest.TestCase):
    def test_dates_are_kst_and_nulls_skipped(self) -> None:
        payload = chart_payload(
            [stamp(2026, 11, 9), stamp(2026, 11, 10), stamp(2026, 11, 11)],
            [1339.5, None, 1341.2],
        )
        series = yahoo.parse_chart_payload(payload)
        self.assertEqual(list(series), ["2026-11-09", "2026-11-11"])
        self.assertEqual(series["2026-11-11"], 1341.2)

    def test_duplicate_day_keeps_latest_bar(self) -> None:
        payload = chart_payload(
            [stamp(2026, 11, 10), stamp(2026, 11, 10)],
            [1300.0, 1310.0],
        )
        series = yahoo.parse_chart_payload(payload)
        self.assertEqual(series, {"2026-11-10": 1310.0})

    def test_bad_payload_raises(self) -> None:
        with self.assertRaises(yahoo.YahooError):
            yahoo.parse_chart_payload({"chart": {"result": []}})
        with self.assertRaises(yahoo.YahooError):
            yahoo.parse_chart_payload(chart_payload([stamp(2026, 11, 9)], [None]))


class AlignSeriesTests(unittest.TestCase):
    def test_forward_fills_and_converts_jpy_to_100(self) -> None:
        points = yahoo.align_series(
            {"2026-11-09": 1300.0, "2026-11-10": 1310.0},
            {"2026-11-09": 8.0, "2026-11-11": 8.2},
        )
        self.assertEqual(
            [p.date for p in points], ["2026-11-09", "2026-11-10", "2026-11-11"]
        )
        self.assertEqual(points[0].jpy_krw_100, 800.0)
        self.assertEqual(points[1].jpy_krw_100, 800.0)  # carried forward
        self.assertEqual(points[2].usd_krw, 1310.0)  # carried forward
        self.assertEqual(points[2].jpy_krw_100, 820.0)

    def test_disjoint_series(self) -> None:
        self.assertEqual(yahoo.align_series({}, {"2026-11-10": 8.0}), [])


if __name__ == "__main__":
    unittest.main()
