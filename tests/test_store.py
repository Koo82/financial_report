from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from financial_report import store


class MakePointTests(unittest.TestCase):
    def test_valid_point_is_rounded(self) -> None:
        point = store.make_point("2026-11-10", 1339.123456, 846.987654)
        assert point is not None
        self.assertEqual(point.date, "2026-11-10")
        self.assertEqual(point.usd_krw, 1339.1235)
        self.assertEqual(point.jpy_krw_100, 846.9877)

    def test_bad_values_are_rejected(self) -> None:
        cases = [
            ("not-a-date", 1300.0, 800.0),
            ("2026-11-10", None, 800.0),
            ("2026-11-10", 0, 800.0),
            ("2026-11-10", -1.0, 800.0),
            ("2026-11-10", float("nan"), 800.0),
            ("2026-11-10", True, 800.0),
        ]
        for day, usd, jpy in cases:
            with self.subTest(day=day, usd=usd, jpy=jpy):
                self.assertIsNone(store.make_point(day, usd, jpy))


class MergeTests(unittest.TestCase):
    def test_new_value_wins_and_dates_are_sorted(self) -> None:
        existing = {
            "points": [
                {"date": "2026-11-09", "usdKrw": 1300.0, "jpyKrw100": 800.0},
                {"date": "2026-11-10", "usdKrw": 1310.0, "jpyKrw100": 810.0},
            ]
        }
        merged = store.merge(
            existing,
            [store.Point("2026-11-10", 1320.0, 815.0)],
            "yahoo",
            updated_at=datetime(2026, 11, 11, 11, 30, tzinfo=store.KST),
        )
        self.assertEqual(merged["source"], "yahoo")
        self.assertEqual(merged["updatedAt"], "2026-11-11T11:30:00+09:00")
        self.assertEqual(
            [p["date"] for p in merged["points"]], ["2026-11-09", "2026-11-10"]
        )
        self.assertEqual(merged["points"][-1]["usdKrw"], 1320.0)

    def test_old_points_beyond_retention_are_removed(self) -> None:
        old = (datetime(2024, 1, 1).date()).isoformat()
        new = (datetime(2026, 11, 10).date()).isoformat()
        payload = store.merge(
            None,
            [store.Point(old, 1300.0, 800.0), store.Point(new, 1310.0, 810.0)],
            "test",
        )
        self.assertEqual([p["date"] for p in payload["points"]], [new])

    def test_invalid_existing_entries_are_skipped(self) -> None:
        existing = {
            "points": [
                {"date": "bad", "usdKrw": "x"},
                {"date": "2026-11-10", "usdKrw": 1310.0, "jpyKrw100": 810.0},
            ]
        }
        merged = store.merge(existing, [], "test")
        self.assertEqual(len(merged["points"]), 1)

    def test_empty_input_raises(self) -> None:
        with self.assertRaises(store.StoreError):
            store.merge(None, [], "test")


class FileTests(unittest.TestCase):
    def test_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "rates.json"
            payload = store.merge(
                None,
                [store.Point("2026-11-10", 1310.0, 810.0)],
                "test",
                updated_at=datetime(2026, 11, 11, 11, 30, tzinfo=store.KST),
            )
            store.save(path, payload)

            loaded = store.load(path)
            assert loaded is not None
            self.assertEqual(loaded, json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual(loaded["points"][0]["usdKrw"], 1310.0)

    def test_load_missing_file_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(store.load(Path(temp) / "missing.json"))

    def test_load_invalid_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rates.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(store.StoreError):
                store.load(path)

    def test_age_minutes(self) -> None:
        now = datetime(2026, 11, 11, 12, 0, tzinfo=store.KST)
        payload = {"updatedAt": "2026-11-11T11:30:00+09:00"}
        self.assertAlmostEqual(store.age_minutes(payload, now), 30.0)
        self.assertIsNone(store.age_minutes({"updatedAt": "nope"}, now))
        self.assertIsNone(store.age_minutes({}, now))


if __name__ == "__main__":
    unittest.main()
