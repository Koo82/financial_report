from __future__ import annotations

import unittest

from financial_report import frankfurter


class ParseFrankfurterTests(unittest.TestCase):
    def test_latest_shape_converts_cross_rates(self) -> None:
        payload = {
            "amount": 1.0,
            "base": "KRW",
            "date": "2026-11-10",
            "rates": {"JPY": 0.11813, "USD": 0.00074682},
        }
        points = frankfurter.parse_payload(payload)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].date, "2026-11-10")
        self.assertAlmostEqual(points[0].usd_krw, 1339.01, places=2)
        self.assertAlmostEqual(points[0].jpy_krw_100, 846.52, places=2)

    def test_range_shape_is_sorted(self) -> None:
        payload = {
            "base": "KRW",
            "rates": {
                "2026-11-10": {"JPY": 0.11813, "USD": 0.00074682},
                "2026-11-09": {"JPY": 0.11728, "USD": 0.00074251},
            },
        }
        points = frankfurter.parse_payload(payload)
        self.assertEqual([p.date for p in points], ["2026-11-09", "2026-11-10"])

    def test_invalid_rows_are_skipped(self) -> None:
        payload = {
            "rates": {
                "2026-11-10": {"JPY": 0, "USD": 0.00074682},
                "bad-date": {"JPY": 0.11813, "USD": 0.00074682},
                "2026-11-11": {"JPY": 0.11813},
            }
        }
        with self.assertRaises(frankfurter.FrankfurterError):
            frankfurter.parse_payload(payload)

    def test_missing_rates_raises(self) -> None:
        with self.assertRaises(frankfurter.FrankfurterError):
            frankfurter.parse_payload({"error": "nope"})


if __name__ == "__main__":
    unittest.main()
