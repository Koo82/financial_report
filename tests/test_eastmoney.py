from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch
from urllib.parse import urlparse

from financial_report import eastmoney
from financial_report.net import FetchError

PAYLOAD = """{
  "rc": 0,
  "data": {
    "code": "GC00Y",
    "name": "COMEX gold",
    "klines": [
      "2026-11-10,3900.0,3994.2",
      "2026-11-11,3990.0,3990.0",
      "2026-11-12,3980.0,3983.1"
    ]
  }
}"""


class ParsePayloadTests(unittest.TestCase):
    def test_parses_close_and_drops_today(self) -> None:
        closes = eastmoney.parse_payload(
            PAYLOAD, today=date(2026, 11, 12)
        )
        self.assertEqual(
            closes,
            {"2026-11-10": 3994.2, "2026-11-11": 3990.0},
        )

    def test_bad_payload_raises(self) -> None:
        with self.assertRaises(eastmoney.EastmoneyError):
            eastmoney.parse_payload('{"rc": 100, "data": null}')
        with self.assertRaises(eastmoney.EastmoneyError):
            eastmoney.parse_payload("<html>blocked</html>")

    def test_rows_with_bad_numbers_are_skipped(self) -> None:
        text = '{"data":{"klines":["2026-11-10,x,","2026-11-11,1,2.5"]}}'
        self.assertEqual(
            eastmoney.parse_payload(text, today=date(2026, 11, 12)),
            {"2026-11-11": 2.5},
        )


class FetchTests(unittest.TestCase):
    def test_rotates_hosts_when_first_is_blocked(self) -> None:
        hosts: list[str] = []

        def fake(url: str, **_: object) -> str:
            host = urlparse(url).netloc
            hosts.append(host)
            if host == "push2his.eastmoney.com":
                raise FetchError("blocked")
            return PAYLOAD

        with patch.object(eastmoney, "get_text", side_effect=fake):
            points = eastmoney.fetch_points(
                days=1200,
                today=date(2026, 11, 12),
                sleep=lambda _: None,
            )

        self.assertIn("push2delay.eastmoney.com", hosts)
        self.assertEqual(
            [point.date for point in points],
            ["2026-11-10", "2026-11-11"],
        )
        self.assertEqual(points[-1].values, {
            "gold": 3990.0,
            "wti": 3990.0,
            "brent": 3990.0,
        })

    def test_all_hosts_failing_raises(self) -> None:
        with (
            patch.object(
                eastmoney, "get_text", side_effect=FetchError("blocked")
            ),
            self.assertRaises(eastmoney.EastmoneyError),
        ):
            eastmoney.fetch_points(
                days=1200,
                today=date(2026, 11, 12),
                sleep=lambda _: None,
            )


if __name__ == "__main__":
    unittest.main()
