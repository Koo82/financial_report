from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from financial_report import cli, policy, store, timeseries
from financial_report.net import FetchError

START = date(2024, 1, 1)
CURRENT = date(2026, 11, 16)


def point(day: str, **values: float) -> timeseries.SeriesPoint:
    return timeseries.SeriesPoint(day, dict(values))


class EcosTests(unittest.TestCase):
    def test_collapses_repeated_days_and_keeps_negative_rates(self) -> None:
        rows = [
            {"TIME": "20260101", "DATA_VALUE": "3"},
            {"TIME": "20260102", "DATA_VALUE": "3"},
            {"TIME": "20260103", "DATA_VALUE": ""},
            {"TIME": "20260104", "DATA_VALUE": "-0.1"},
        ]
        events = policy.parse_ecos_rows(rows)
        self.assertEqual(
            [event.as_dict() for event in events],
            [
                {"date": "2026-01-01", "kr": 3.0},
                {"date": "2026-01-04", "kr": -0.1},
            ],
        )

    def test_paginates_until_total(self) -> None:
        days = [date(2016, 1, 1) + timedelta(days=index) for index in range(1500)]
        calls: list[str] = []

        def fake(url: str, **_: object) -> dict:
            calls.append(url)
            if "/1/1000/" in url:
                rows = [
                    {
                        "TIME": day.strftime("%Y%m%d"),
                        "DATA_VALUE": "3.5",
                    }
                    for day in days[:1000]
                ]
            else:
                rows = [
                    {
                        "TIME": day.strftime("%Y%m%d"),
                        "DATA_VALUE": "3.5",
                    }
                    for day in days[1000:]
                ]
            return {
                "StatisticSearch": {
                    "list_total_count": 1500,
                    "row": rows,
                }
            }

        with patch.object(policy, "get_json", side_effect=fake):
            events = policy.fetch_korea(
                date(2016, 1, 1),
                date(2026, 11, 16),
                api_key="secret",
                sleep=lambda _: None,
            )

        self.assertEqual(len(calls), 2)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].date, "2016-01-01")

    def test_error_message_redacts_api_key(self) -> None:
        def broken(url: str, **_: object) -> dict:
            raise FetchError(f"could not fetch {url}: boom")

        with (
            patch.object(policy, "get_json", side_effect=broken),
            self.assertRaises(policy.PolicyError) as caught,
        ):
            policy.fetch_korea(
                START,
                CURRENT,
                api_key="very-secret-key",
                sleep=lambda _: None,
            )

        self.assertNotIn("very-secret-key", str(caught.exception))
        self.assertIn("***", str(caught.exception))

    def test_missing_key_is_rejected(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            self.assertRaises(policy.PolicyError),
        ):
            policy.fetch_korea(START, CURRENT)

    def test_ecos_error_payload_is_reported(self) -> None:
        with self.assertRaises(policy.PolicyError):
            policy._ecos_payload(
                {"RESULT": {"CODE": "ERROR-301", "MESSAGE": "bad request"}}
            )


class FredTests(unittest.TestCase):
    def test_parses_observations_and_skips_missing_values(self) -> None:
        values = policy.parse_fred_observations(
            {
                "observations": [
                    {"date": "2026-09-16", "value": "4.25"},
                    {"date": "2026-09-17", "value": "4.00"},
                    {"date": "2026-09-18", "value": "."},
                ]
            }
        )
        self.assertEqual(
            values,
            {"2026-09-16": 4.25, "2026-09-17": 4.0},
        )

    def test_builds_target_range_events(self) -> None:
        upper = {
            "2026-09-16": 4.25,
            "2026-09-17": 4.0,
            "2026-09-18": 4.0,
        }
        lower = {
            "2026-09-16": 4.0,
            "2026-09-17": 3.75,
            "2026-09-18": 3.75,
        }
        events = policy._collapse(
            {
                day: {"us_low": lower[day], "us_high": upper[day]}
                for day in upper
            },
            ("us_low", "us_high"),
        )
        self.assertEqual(
            [event.as_dict() for event in events],
            [
                {"date": "2026-09-16", "us_low": 4.0, "us_high": 4.25},
                {"date": "2026-09-17", "us_low": 3.75, "us_high": 4.0},
            ],
        )

    def test_error_message_redacts_api_key(self) -> None:
        def broken(url: str, **_: object) -> dict:
            raise FetchError(f"could not fetch {url}: boom")

        with (
            patch.object(policy, "get_json", side_effect=broken),
            self.assertRaises(policy.PolicyError) as caught,
        ):
            policy.fetch_us(
                START,
                CURRENT,
                api_key="very-secret-key",
                sleep=lambda _: None,
            )

        self.assertNotIn("very-secret-key", str(caught.exception))


class BisTests(unittest.TestCase):
    def test_parses_quoted_notes_and_negative_rates(self) -> None:
        text = (
            "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE,SUPP_INFO_BREAKS\n"
            "D,JP,2024-03-19,-0.1,\"from 2016: minus 0.1 percent, with a note\"\n"
            "D,JP,2024-03-20,-0.1,\"same\"\n"
            "D,JP,2024-03-21,0,\"new\"\n"
        )
        events = policy.parse_bis_csv(text)
        self.assertEqual(
            [event.as_dict() for event in events],
            [
                {"date": "2024-03-19", "jp": -0.1},
                {"date": "2024-03-21", "jp": 0.0},
            ],
        )

    def test_unexpected_columns_raise(self) -> None:
        with self.assertRaises(policy.PolicyError):
            policy.parse_bis_csv("DATE,VALUE\n2026-01-01,1\n")


class DefaultFetcherTests(unittest.TestCase):
    def test_start_date_uses_a_short_overlap_before_the_last_event(self) -> None:
        current = date(2026, 11, 16)
        start = policy._start_date("2026-09-24", current)
        self.assertEqual(
            start,
            date(2026, 9, 24) - timedelta(days=policy.LOOKBACK_DAYS),
        )

    def test_start_date_falls_back_to_the_window_for_new_countries(self) -> None:
        current = date(2026, 11, 16)
        self.assertEqual(
            policy._start_date(None, current),
            current - timedelta(days=policy.DEFAULT_DAYS),
        )
        self.assertEqual(
            policy._start_date("not-a-date", current),
            current - timedelta(days=policy.DEFAULT_DAYS),
        )

    def test_start_date_never_goes_beyond_the_window(self) -> None:
        current = date(2026, 11, 16)
        self.assertEqual(
            policy._start_date("2010-01-01", current),
            current - timedelta(days=policy.DEFAULT_DAYS),
        )

    def test_window_days_only_applies_without_history(self) -> None:
        current = date(2026, 11, 16)
        self.assertEqual(
            policy._start_date(None, current, 30),
            current - timedelta(days=30),
        )
        self.assertEqual(
            policy._start_date("2026-09-24", current, 30),
            date(2026, 9, 24) - timedelta(days=policy.LOOKBACK_DAYS),
        )

    def test_default_fetchers_scope_each_country(self) -> None:
        current = date(2026, 11, 16)
        with patch.object(policy, "fetch_japan", return_value=[]) as japan:
            policy.default_fetchers(current, {"jp": "2026-09-24"})["jp"]()
        japan.assert_called_once_with(
            date(2026, 9, 24) - timedelta(days=policy.LOOKBACK_DAYS),
            current,
        )


class RunFetchPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "policy.json"
        self.now = datetime(2026, 11, 16, 9, 0, tzinfo=store.KST)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _seed(self) -> None:
        payload = timeseries.merge(
            None,
            [
                point("2026-01-01", kr=3.0, jp=0.5, us_low=4.0, us_high=4.25),
            ],
            policy.SOURCE,
            policy.SERIES,
            kind="policy",
            updated_at=self.now,
            allow_nonpositive=True,
        )
        timeseries.save(self.path, payload)

    def test_partial_failure_keeps_other_countries_and_saves_successes(self) -> None:
        self._seed()

        def broken() -> list[timeseries.SeriesPoint]:
            raise RuntimeError("BOJ unavailable")

        fetchers = {
            "kr": lambda: [point("2026-08-27", kr=3.0)],
            "jp": broken,
            "us": lambda: [
                point("2026-09-17", us_low=3.75, us_high=4.0)
            ],
        }
        code = policy.run_fetch_policy(
            self.path,
            now=self.now,
            fetchers=fetchers,
        )

        self.assertEqual(code, 1)
        payload = timeseries.load(self.path)
        assert payload is not None
        latest = payload["points"][-1]
        self.assertEqual(latest["us_low"], 3.75)
        self.assertIn(
            "2026-01-01",
            [row["date"] for row in payload["points"]],
        )
        self.assertEqual(
            payload["points"][0]["jp"],
            0.5,
        )

    def test_all_failures_do_not_touch_existing_file(self) -> None:
        self._seed()
        before = self.path.read_bytes()

        def broken() -> list[timeseries.SeriesPoint]:
            raise RuntimeError("down")

        code = policy.run_fetch_policy(
            self.path,
            now=self.now,
            fetchers={"kr": broken, "jp": broken, "us": broken},
        )

        self.assertEqual(code, 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_repeated_baseline_is_not_stored_again(self) -> None:
        self._seed()
        fetchers = {
            "kr": lambda: [
                point("2025-01-01", kr=3.5),
                point("2026-01-01", kr=3.0),
            ],
            "jp": lambda: [
                point("2025-01-01", jp=0.25),
                point("2026-01-01", jp=0.5),
            ],
            "us": lambda: [
                point("2025-01-01", us_low=4.25, us_high=4.5),
                point("2026-01-01", us_low=4.0, us_high=4.25),
            ],
        }
        code = policy.run_fetch_policy(
            self.path,
            now=self.now,
            fetchers=fetchers,
        )

        self.assertEqual(code, 0)
        payload = timeseries.load(self.path)
        assert payload is not None
        self.assertEqual(len(payload["points"]), 1)
        self.assertEqual(
            payload["updatedAt"],
            "2026-11-16T09:00:00+09:00",
        )

    def test_only_events_after_the_last_stored_date_are_added(self) -> None:
        self._seed()
        code = policy.run_fetch_policy(
            self.path,
            now=self.now,
            fetchers={
                "kr": lambda: [
                    point("2025-01-01", kr=3.5),
                    point("2026-08-27", kr=3.0),
                ]
            },
        )

        self.assertEqual(code, 0)
        payload = timeseries.load(self.path)
        assert payload is not None
        self.assertEqual(
            [row["date"] for row in payload["points"]],
            ["2026-01-01", "2026-08-27"],
        )
        self.assertEqual(payload["points"][-1]["kr"], 3.0)

    def test_dry_run_does_not_write(self) -> None:
        code = policy.run_fetch_policy(
            self.path,
            dry_run=True,
            now=self.now,
            fetchers={"kr": lambda: [point("2026-08-27", kr=3.0)]},
        )
        self.assertEqual(code, 0)
        self.assertFalse(self.path.exists())

    def test_nonpositive_values_are_kept(self) -> None:
        code = policy.run_fetch_policy(
            self.path,
            now=self.now,
            fetchers={
                "jp": lambda: [
                    point("2024-03-19", jp=-0.1),
                    point("2024-03-21", jp=0.0),
                ]
            },
        )
        self.assertEqual(code, 0)
        payload = timeseries.load(self.path)
        assert payload is not None
        self.assertEqual(payload["points"][0]["jp"], -0.1)
        self.assertEqual(payload["points"][1]["jp"], 0.0)


class CliTests(unittest.TestCase):
    def test_fetch_policy_options(self) -> None:
        args = cli.build_parser().parse_args(
            ["fetch-policy", "--data", "x.json", "--days", "30", "--dry-run"]
        )
        self.assertEqual(args.command, "fetch-policy")
        self.assertEqual(args.data, "x.json")
        self.assertEqual(args.days, 30)
        self.assertTrue(args.dry_run)


if __name__ == "__main__":
    unittest.main()
