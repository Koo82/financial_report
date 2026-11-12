from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from financial_report import markets, store, timeseries


def yields_points() -> list[timeseries.SeriesPoint]:
    return [
        timeseries.SeriesPoint(
            "2026-11-10",
            {"us5y": 4.81, "us10y": 4.98, "us30y": 5.35},
        )
    ]


def futures_points() -> list[timeseries.SeriesPoint]:
    return [
        timeseries.SeriesPoint(
            "2026-11-11",
            {"gold": 3994.2, "wti": 86.42, "brent": 92.58},
        )
    ]


class RunFetchMarketsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.now = datetime(2026, 11, 12, 11, 30, tzinfo=store.KST)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_writes_each_group(self) -> None:
        code = markets.run_fetch_markets(
            self.data_dir,
            ("yields", "futures"),
            now=self.now,
            sources_by_group={
                "yields": [("fake-yields", yields_points)],
                "futures": [("fake-futures", futures_points)],
            },
        )

        self.assertEqual(code, 0)
        yields = timeseries.load(self.data_dir / "yields.json")
        futures = timeseries.load(self.data_dir / "futures.json")
        assert yields and futures
        self.assertEqual(yields["source"], "fake-yields")
        self.assertEqual(futures["source"], "fake-futures")
        self.assertEqual(yields["points"][0]["us10y"], 4.98)

    def test_falls_back_to_the_second_source(self) -> None:
        def broken() -> list[timeseries.SeriesPoint]:
            raise RuntimeError("blocked")

        code = markets.run_fetch_markets(
            self.data_dir,
            ("yields",),
            now=self.now,
            sources_by_group={
                "yields": [
                    ("treasury", broken),
                    ("backup", yields_points),
                ]
            },
        )

        self.assertEqual(code, 0)
        payload = timeseries.load(self.data_dir / "yields.json")
        assert payload
        self.assertEqual(payload["source"], "backup")

    def test_failed_group_keeps_existing_file(self) -> None:
        original = timeseries.merge(
            None,
            yields_points(),
            "original",
            markets.GROUPS["yields"].series,
            kind="yields",
            updated_at=self.now,
        )
        timeseries.save(self.data_dir / "yields.json", original)

        def broken() -> list[timeseries.SeriesPoint]:
            raise RuntimeError("blocked")

        code = markets.run_fetch_markets(
            self.data_dir,
            ("yields",),
            now=self.now,
            sources_by_group={"yields": [("treasury", broken)]},
        )

        self.assertEqual(code, 1)
        payload = timeseries.load(self.data_dir / "yields.json")
        assert payload
        self.assertEqual(payload, original)

    def test_fresh_group_is_skipped(self) -> None:
        original = timeseries.merge(
            None,
            yields_points(),
            "original",
            markets.GROUPS["yields"].series,
            kind="yields",
            updated_at=self.now,
        )
        timeseries.save(self.data_dir / "yields.json", original)
        fetch = Mock()

        code = markets.run_fetch_markets(
            self.data_dir,
            ("yields",),
            skip_if_fresh=180,
            now=self.now,
            sources_by_group={"yields": [("treasury", fetch)]},
        )

        self.assertEqual(code, 0)
        fetch.assert_not_called()

    def test_force_overrides_fresh_check(self) -> None:
        original = timeseries.merge(
            None,
            yields_points(),
            "original",
            markets.GROUPS["yields"].series,
            kind="yields",
            updated_at=self.now,
        )
        timeseries.save(self.data_dir / "yields.json", original)

        code = markets.run_fetch_markets(
            self.data_dir,
            ("yields",),
            skip_if_fresh=180,
            force=True,
            now=self.now,
            sources_by_group={"yields": [("backup", yields_points)]},
        )

        self.assertEqual(code, 0)
        payload = timeseries.load(self.data_dir / "yields.json")
        assert payload
        self.assertEqual(payload["source"], "backup")

    def test_corrupt_file_is_reported_without_crashing(self) -> None:
        (self.data_dir / "yields.json").write_text("{not json")

        code = markets.run_fetch_markets(
            self.data_dir,
            ("yields",),
            now=self.now,
            sources_by_group={"yields": [("backup", yields_points)]},
        )

        self.assertEqual(code, 1)
        self.assertEqual(
            (self.data_dir / "yields.json").read_text(), "{not json"
        )


class BuildSourcesTests(unittest.TestCase):
    def test_yields_use_treasury(self) -> None:
        self.assertEqual(
            [name for name, _ in markets.build_sources("yields", 1200)],
            ["treasury"],
        )

    def test_futures_prefer_sina_then_eastmoney(self) -> None:
        self.assertEqual(
            [name for name, _ in markets.build_sources("futures", 1200)],
            ["sina", "eastmoney"],
        )


if __name__ == "__main__":
    unittest.main()
