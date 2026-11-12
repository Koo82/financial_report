from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from financial_report import store, timeseries


def point(day: str, **values: float) -> timeseries.SeriesPoint:
    return timeseries.SeriesPoint(day, dict(values))


class MergeTests(unittest.TestCase):
    def test_new_values_win_and_old_columns_survive(self) -> None:
        existing = {
            "series": ["a", "b"],
            "points": [{"date": "2026-11-10", "a": 1.0, "b": 2.0}],
        }
        merged = timeseries.merge(
            existing,
            [point("2026-11-10", a=3.0)],
            "test",
            ("a", "b"),
            kind="test",
        )
        self.assertEqual(
            merged["points"],
            [{"date": "2026-11-10", "a": 3.0, "b": 2.0}],
        )

    def test_invalid_rows_are_skipped(self) -> None:
        merged = timeseries.merge(
            None,
            [
                point("bad", a=1.0),
                point("2026-11-09", a=-1.0),
                point("2026-11-10", a=1.0),
            ],
            "test",
            ("a",),
            kind="test",
        )
        self.assertEqual([row["date"] for row in merged["points"]], ["2026-11-10"])

    def test_empty_input_raises(self) -> None:
        with self.assertRaises(store.StoreError):
            timeseries.merge(None, [], "test", ("a",), kind="test")

    def test_three_year_old_point_is_retained(self) -> None:
        new = datetime(2026, 11, 10)
        old = (new - timedelta(days=1095)).date().isoformat()
        merged = timeseries.merge(
            None,
            [point(old, a=1.0), point(new.date().isoformat(), a=2.0)],
            "test",
            ("a",),
            kind="test",
        )
        self.assertEqual(len(merged["points"]), 2)

    def test_points_beyond_retention_are_removed(self) -> None:
        new = datetime(2026, 11, 10)
        old = (new - timedelta(days=1300)).date().isoformat()
        merged = timeseries.merge(
            None,
            [point(old, a=1.0), point(new.date().isoformat(), a=2.0)],
            "test",
            ("a",),
            kind="test",
        )
        self.assertEqual([row["date"] for row in merged["points"]], [
            new.date().isoformat()
        ])

    def test_payload_shape(self) -> None:
        merged = timeseries.merge(
            None,
            [point("2026-11-10", us5y=4.81, us10y=4.98)],
            "treasury",
            ("us5y", "us10y"),
            kind="yields",
            updated_at=datetime(2026, 11, 12, 11, 30, tzinfo=store.KST),
        )
        self.assertEqual(merged["version"], timeseries.SCHEMA_VERSION)
        self.assertEqual(merged["kind"], "yields")
        self.assertEqual(merged["source"], "treasury")
        self.assertEqual(merged["series"], ["us5y", "us10y"])
        self.assertEqual(
            merged["updatedAt"], "2026-11-12T11:30:00+09:00"
        )


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "series.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_round_trip(self) -> None:
        payload = timeseries.merge(
            None,
            [point("2026-11-10", a=1.5)],
            "test",
            ("a",),
            kind="test",
        )
        timeseries.save(self.path, payload)
        loaded = timeseries.load(self.path)
        self.assertEqual(loaded, json.loads(self.path.read_text()))

    def test_missing_file_is_none(self) -> None:
        self.assertIsNone(timeseries.load(self.path))

    def test_file_without_series_is_rejected(self) -> None:
        self.path.write_text('{"points": []}')
        with self.assertRaises(store.StoreError):
            timeseries.load(self.path)

        self.path.write_text('{"series": ["a"], "points": []}')
        self.assertIsNotNone(timeseries.load(self.path))


if __name__ == "__main__":
    unittest.main()
