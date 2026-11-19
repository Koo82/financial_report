from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from financial_report import cli, pce, store, timeseries
from financial_report.net import FetchError

TODAY = date(2026, 11, 19)
START = date(2025, 1, 1)

OBSERVATIONS = [
    ("2025-01-01", "100.0"),
    ("2025-02-01", "100.5"),
    ("2025-03-01", "100.8"),
    ("2025-04-01", "101.0"),
    ("2025-05-01", "101.1"),
    ("2025-06-01", "101.3"),
    ("2025-07-01", "101.4"),
    ("2025-08-01", "101.6"),
    ("2025-09-01", "101.8"),
    ("2025-10-01", "102.0"),
    ("2025-11-01", "102.2"),
    ("2025-12-01", "102.5"),
    ("2026-01-01", "103.0"),
    ("2026-02-01", "103.5"),
]


def payload() -> dict:
    return {
        "observations": [
            {"date": day, "value": value} for day, value in OBSERVATIONS
        ]
    }


def pce_points() -> list[timeseries.SeriesPoint]:
    return [
        timeseries.SeriesPoint(
            "2026-09-01",
            {
                "core_pce_index": 130.902,
                "core_pce_mom": 0.32,
                "core_pce_yoy": 2.8,
            },
        )
    ]


class ParseObservationsTests(unittest.TestCase):
    def test_parses_monthly_index_and_skips_missing_values(self) -> None:
        values = pce.parse_observations(
            {
                "observations": [
                    {"date": "2026-08-01", "value": "130.489"},
                    {"date": "2026-09-01", "value": "130.902"},
                    {"date": "2026-10-01", "value": "."},
                    {"date": "not-a-date", "value": "131.0"},
                ]
            }
        )

        self.assertEqual(
            values,
            {
                date(2026, 8, 1): 130.489,
                date(2026, 9, 1): 130.902,
            },
        )

    def test_error_payload_is_reported(self) -> None:
        with self.assertRaises(pce.PceError):
            pce.parse_observations({"error_message": "bad series"})

    def test_invalid_payload_is_rejected(self) -> None:
        with self.assertRaises(pce.PceError):
            pce.parse_observations([])


class InflationTests(unittest.TestCase):
    def test_calculates_mom_and_yoy(self) -> None:
        points = pce.inflation_points(pce.parse_observations(payload()))

        self.assertEqual(
            [point.date for point in points],
            ["2026-01-01", "2026-02-01"],
        )
        self.assertAlmostEqual(points[0].values["core_pce_mom"], 0.4878, places=4)
        self.assertAlmostEqual(points[0].values["core_pce_yoy"], 3.0, places=4)
        self.assertAlmostEqual(points[1].values["core_pce_mom"], 0.4854, places=4)
        self.assertAlmostEqual(points[1].values["core_pce_yoy"], 2.9851, places=4)

    def test_keeps_negative_inflation(self) -> None:
        values = {
            date(2025, 1, 1): 100.0,
            date(2025, 2, 1): 99.0,
            date(2026, 1, 1): 98.0,
            date(2026, 2, 1): 97.5,
        }

        points = pce.inflation_points(values)

        self.assertEqual(len(points), 1)
        self.assertLess(points[0].values["core_pce_mom"], 0)
        self.assertLess(points[0].values["core_pce_yoy"], 0)

    def test_start_filters_after_lookback_is_used(self) -> None:
        points = pce.inflation_points(
            pce.parse_observations(payload()),
            start=date(2026, 2, 1),
        )

        self.assertEqual([point.date for point in points], ["2026-02-01"])


class FetchTests(unittest.TestCase):
    def test_fetches_pcepilfe_with_the_api_key(self) -> None:
        with patch.object(pce, "get_json", return_value=payload()) as fake:
            points = pce.fetch_points(
                days=3650,
                today=TODAY,
                api_key="secret",
                sleep=lambda _: None,
            )

        url = fake.call_args.args[0]
        expected_start = TODAY - timedelta(
            days=3650 + pce.LOOKBACK_DAYS
        )
        self.assertIn("series_id=PCEPILFE", url)
        self.assertIn("api_key=secret", url)
        self.assertIn("frequency=m", url)
        self.assertIn(
            f"observation_start={expected_start.isoformat()}", url
        )
        self.assertIn("observation_end=2026-11-19", url)
        self.assertEqual(len(points), 2)
        self.assertEqual(points[-1].date, "2026-02-01")

    def test_missing_key_is_rejected(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            self.assertRaises(pce.PceError),
        ):
            pce.fetch_observations(START, TODAY)

    def test_error_message_redacts_api_key(self) -> None:
        def broken(url: str, **_: object) -> dict:
            raise FetchError(f"could not fetch {url}: boom")

        with (
            patch.object(pce, "get_json", side_effect=broken),
            self.assertRaises(pce.PceError) as caught,
        ):
            pce.fetch_observations(
                START,
                TODAY,
                api_key="very-secret-key",
                sleep=lambda _: None,
            )

        self.assertNotIn("very-secret-key", str(caught.exception))
        self.assertIn("***", str(caught.exception))

    def test_empty_window_is_reported(self) -> None:
        with (
            patch.object(
                pce,
                "get_json",
                return_value={"observations": []},
            ),
            self.assertRaises(pce.PceError),
        ):
            pce.fetch_points(
                days=3650,
                today=TODAY,
                api_key="secret",
                sleep=lambda _: None,
            )


class RunFetchPceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "pce.json"
        self.now = datetime(2026, 11, 19, 11, 30, tzinfo=store.KST)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_writes_monthly_history(self) -> None:
        code = pce.run_fetch_pce(
            self.path,
            now=self.now,
            fetcher=pce_points,
        )

        self.assertEqual(code, 0)
        payload = timeseries.load(self.path)
        assert payload
        self.assertEqual(payload["kind"], "pce")
        self.assertEqual(payload["source"], "fred")
        self.assertEqual(payload["series"], list(pce.SERIES))
        self.assertEqual(payload["points"][0]["core_pce_yoy"], 2.8)

    def test_failure_keeps_existing_file(self) -> None:
        original = timeseries.merge(
            None,
            pce_points(),
            "original",
            pce.SERIES,
            kind="pce",
            updated_at=self.now,
            allow_nonpositive=True,
        )
        timeseries.save(self.path, original)
        before = self.path.read_bytes()

        def broken() -> list[timeseries.SeriesPoint]:
            raise RuntimeError("down")

        code = pce.run_fetch_pce(self.path, now=self.now, fetcher=broken)

        self.assertEqual(code, 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_dry_run_does_not_write(self) -> None:
        code = pce.run_fetch_pce(
            self.path,
            dry_run=True,
            now=self.now,
            fetcher=pce_points,
        )

        self.assertEqual(code, 0)
        self.assertFalse(self.path.exists())

    def test_fresh_file_is_skipped(self) -> None:
        original = timeseries.merge(
            None,
            pce_points(),
            "original",
            pce.SERIES,
            kind="pce",
            updated_at=self.now,
            allow_nonpositive=True,
        )
        timeseries.save(self.path, original)
        fetch = Mock()

        code = pce.run_fetch_pce(
            self.path,
            skip_if_fresh=180,
            now=self.now,
            fetcher=fetch,
        )

        self.assertEqual(code, 0)
        fetch.assert_not_called()

    def test_force_overrides_freshness(self) -> None:
        original = timeseries.merge(
            None,
            pce_points(),
            "original",
            pce.SERIES,
            kind="pce",
            updated_at=self.now,
            allow_nonpositive=True,
        )
        timeseries.save(self.path, original)

        code = pce.run_fetch_pce(
            self.path,
            skip_if_fresh=180,
            force=True,
            now=self.now,
            fetcher=pce_points,
        )

        self.assertEqual(code, 0)
        payload = timeseries.load(self.path)
        assert payload
        self.assertEqual(payload["source"], "fred")

    def test_negative_values_are_saved(self) -> None:
        def negative() -> list[timeseries.SeriesPoint]:
            return [
                timeseries.SeriesPoint(
                    "2026-09-01",
                    {
                        "core_pce_index": 129.0,
                        "core_pce_mom": -0.2,
                        "core_pce_yoy": -0.5,
                    },
                )
            ]

        code = pce.run_fetch_pce(self.path, now=self.now, fetcher=negative)

        self.assertEqual(code, 0)
        payload = timeseries.load(self.path)
        assert payload
        self.assertEqual(payload["points"][0]["core_pce_yoy"], -0.5)

    def test_empty_source_is_reported(self) -> None:
        code = pce.run_fetch_pce(
            self.path,
            now=self.now,
            fetcher=list,
        )

        self.assertEqual(code, 1)
        self.assertFalse(self.path.exists())

    def test_corrupt_file_is_reported_without_crashing(self) -> None:
        self.path.write_text("{not json")

        code = pce.run_fetch_pce(
            self.path,
            now=self.now,
            fetcher=pce_points,
        )

        self.assertEqual(code, 1)
        self.assertEqual(self.path.read_text(), "{not json")


class CliTests(unittest.TestCase):
    def test_fetch_pce_options(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "fetch-pce",
                "--data",
                "x.json",
                "--days",
                "30",
                "--skip-if-fresh",
                "60",
                "--force",
                "--dry-run",
            ]
        )
        self.assertEqual(args.command, "fetch-pce")
        self.assertEqual(args.data, "x.json")
        self.assertEqual(args.days, 30)
        self.assertEqual(args.skip_if_fresh, 60)
        self.assertTrue(args.force)
        self.assertTrue(args.dry_run)


if __name__ == "__main__":
    unittest.main()
