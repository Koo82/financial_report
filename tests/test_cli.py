from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from financial_report import cli, store


def point(
    day: str = "2026-11-10", usd: float = 1310.0, jpy: float = 810.0
) -> store.Point:
    return store.Point(day, usd, jpy)


class BuildSourcesTests(unittest.TestCase):
    def _calls(self, existing: dict | None, days: int | None):
        with (
            patch.object(cli.yahoo, "fetch_points", return_value=[]) as yahoo_fetch,
            patch.object(
                cli.frankfurter, "fetch_points", return_value=[]
            ) as frankfurter_fetch,
        ):
            sources = dict(cli.build_sources(existing, days))
            sources["yahoo"]()
            sources["frankfurter"]()
        return yahoo_fetch, frankfurter_fetch

    def test_first_run_backfills_three_years(self) -> None:
        yahoo_fetch, _ = self._calls(None, None)
        yahoo_fetch.assert_called_once_with(days=cli.BOOTSTRAP_DAYS)
        self.assertEqual(cli.BOOTSTRAP_DAYS, 1200)

    def test_incremental_run_is_short(self) -> None:
        existing = {"points": [point().as_dict()]}
        yahoo_fetch, _ = self._calls(existing, None)
        yahoo_fetch.assert_called_once_with(days=cli.INCREMENTAL_DAYS)
        self.assertEqual(cli.INCREMENTAL_DAYS, 14)

    def test_explicit_days_overrides_default(self) -> None:
        existing = {"points": [point().as_dict()]}
        yahoo_fetch, _ = self._calls(existing, 1200)
        yahoo_fetch.assert_called_once_with(days=1200)


class RunFetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "rates.json"
        self.now = datetime(2026, 11, 11, 11, 30, tzinfo=store.KST)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_falls_back_to_second_source(self) -> None:
        def broken() -> list[store.Point]:
            raise RuntimeError("429")

        sources = [("yahoo", broken), ("frankfurter", lambda: [point()])]
        code = cli.run_fetch(self.path, sources, now=self.now)
        self.assertEqual(code, 0)
        payload = store.load(self.path)
        assert payload is not None
        self.assertEqual(payload["source"], "frankfurter")
        self.assertEqual(payload["points"][-1]["usdKrw"], 1310.0)

    def test_failure_does_not_touch_existing_file(self) -> None:
        payload = store.merge(None, [point()], "yahoo", updated_at=self.now)
        store.save(self.path, payload)
        before = self.path.read_bytes()

        def broken() -> list[store.Point]:
            raise RuntimeError("down")

        code = cli.run_fetch(
            self.path,
            [("yahoo", broken), ("frankfurter", broken)],
            now=self.now,
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_skip_if_fresh_avoids_fetch(self) -> None:
        payload = store.merge(None, [point()], "yahoo", updated_at=self.now)
        store.save(self.path, payload)

        def unexpected() -> list[store.Point]:
            raise AssertionError("should not be called")

        code = cli.run_fetch(
            self.path,
            [("yahoo", unexpected)],
            skip_if_fresh=180,
            now=self.now,
        )
        self.assertEqual(code, 0)

    def test_force_overrides_freshness(self) -> None:
        payload = store.merge(None, [point()], "yahoo", updated_at=self.now)
        store.save(self.path, payload)
        code = cli.run_fetch(
            self.path,
            [("yahoo", lambda: [point(usd=1320.0)])],
            skip_if_fresh=180,
            force=True,
            now=self.now,
        )
        self.assertEqual(code, 0)
        updated = store.load(self.path)
        assert updated is not None
        self.assertEqual(updated["points"][-1]["usdKrw"], 1320.0)

    def test_dry_run_does_not_write(self) -> None:
        code = cli.run_fetch(
            self.path,
            [("yahoo", lambda: [point()])],
            dry_run=True,
            now=self.now,
        )
        self.assertEqual(code, 0)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
