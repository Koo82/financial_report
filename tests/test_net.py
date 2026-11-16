from __future__ import annotations

import unittest
from http.client import IncompleteRead
from unittest.mock import MagicMock, patch

from financial_report import net


def response(body: bytes) -> MagicMock:
    result = MagicMock()
    result.headers.get_content_charset.return_value = "utf-8"
    result.read.return_value = body
    result.__enter__.return_value = result
    result.__exit__.return_value = False
    return result


class GetTextTests(unittest.TestCase):
    def test_retries_a_truncated_read(self) -> None:
        truncated = response(b"")
        truncated.read.side_effect = IncompleteRead(b"partial", 10)
        complete = response(b'{"ok": true}')

        with patch.object(
            net, "urlopen", side_effect=[truncated, complete]
        ) as opener:
            text = net.get_text(
                "https://example.test/data",
                attempts=2,
                sleep=lambda _: None,
            )

        self.assertEqual(text, '{"ok": true}')
        self.assertEqual(opener.call_count, 2)

    def test_raises_after_repeated_truncation(self) -> None:
        broken = response(b"")
        broken.read.side_effect = IncompleteRead(b"partial", 10)

        with (
            patch.object(net, "urlopen", return_value=broken),
            self.assertRaises(net.FetchError) as caught,
        ):
            net.get_text(
                "https://example.test/data",
                attempts=2,
                sleep=lambda _: None,
            )

        self.assertIn("IncompleteRead", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
