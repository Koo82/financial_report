from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from financial_report import sina

ROW = (
    '{{"date":"{date}","open":"1.0","high":"2.0",'
    '"low":"0.5","close":"{close}","volume":"0"}}'
)


def payload(rows: list[tuple[str, str]]) -> str:
    body = ",".join(ROW.format(date=day, close=close) for day, close in rows)
    return (
        "/*<script>location.href='//sina.com';</script>*/\n"
        f"var _GC=([{body}]);"
    )


def symbol_of(url: str) -> str:
    return parse_qs(urlparse(url).query)["symbol"][0]


class ParsePayloadTests(unittest.TestCase):
    def test_parses_jsonp_and_closes(self) -> None:
        text = payload([
            ("2026-11-10", "101.5"),
            ("2026-11-11", "102.25"),
        ])
        self.assertEqual(
            sina.parse_payload(text),
            {"2026-11-10": 101.5, "2026-11-11": 102.25},
        )

    def test_invalid_rows_are_skipped(self) -> None:
        text = payload([
            ("bad", "1.0"),
            ("2026-11-10", "0"),
            ("2026-11-11", "102.25"),
        ])
        self.assertEqual(sina.parse_payload(text), {"2026-11-11": 102.25})

    def test_malformed_response_raises(self) -> None:
        with self.assertRaises(sina.SinaError):
            sina.parse_payload("<html>blocked</html>")

    def test_empty_response_raises(self) -> None:
        with self.assertRaises(sina.SinaError):
            sina.parse_payload("var _GC=([]);")


class FetchTests(unittest.TestCase):
    def test_drops_today_and_aligns_all_symbols(self) -> None:
        closes = {
            "GC": [("2026-11-10", "3994.2"), ("2026-11-11", "3990.0"), ("2026-11-12", "3983.1")],
            "CL": [("2026-11-10", "86.43"), ("2026-11-11", "86.42"), ("2026-11-12", "86.19")],
            "OIL": [("2026-11-10", "91.96"), ("2026-11-11", "92.58"), ("2026-11-12", "92.41")],
        }

        def fake(url: str, **_: object) -> str:
            return payload(closes[symbol_of(url)])

        with patch.object(sina, "get_text", side_effect=fake):
            points = sina.fetch_points(
                days=1200,
                today=date(2026, 11, 12),
                sleep=lambda _: None,
            )

        self.assertEqual([point.date for point in points], [
            "2026-11-10",
            "2026-11-11",
        ])
        self.assertEqual(points[-1].values, {
            "gold": 3990.0,
            "wti": 86.42,
            "brent": 92.58,
        })

    def test_dates_missing_from_one_symbol_are_dropped(self) -> None:
        closes = {
            "GC": [("2026-11-10", "3994.2"), ("2026-11-11", "3990.0")],
            "CL": [("2026-11-11", "86.42")],
            "OIL": [("2026-11-10", "91.96"), ("2026-11-11", "92.58")],
        }

        def fake(url: str, **_: object) -> str:
            return payload(closes[symbol_of(url)])

        with patch.object(sina, "get_text", side_effect=fake):
            points = sina.fetch_points(
                days=1200,
                today=date(2026, 11, 12),
                sleep=lambda _: None,
            )

        self.assertEqual([point.date for point in points], ["2026-11-11"])


if __name__ == "__main__":
    unittest.main()
