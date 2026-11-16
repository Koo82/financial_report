"""Collect central-bank policy rates from ECOS, BIS, and FRED."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from . import timeseries
from .net import FetchError, get_json, get_text
from .store import StoreError, now_kst
from .timeseries import SeriesPoint

ECOS_STAT = "722Y001"
ECOS_ITEM = "0101000"
ECOS_PAGE = 1000
BIS_URL = "https://stats.bis.org/api/v1/data/WS_CBPOL/D.{country}"
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
SERIES = ("kr", "jp", "us_low", "us_high")
SOURCE = "ecos+fred+bis"
DEFAULT_DAYS = 3650
RETAIN_DAYS = 3650
LOOKBACK_DAYS = 45
COUNTRY_KEYS = {
    "kr": ("kr",),
    "jp": ("jp",),
    "us": ("us_low", "us_high"),
}

Fetcher = Callable[[], list[SeriesPoint]]


class PolicyError(RuntimeError):
    """Raised when a policy-rate feed cannot be read or parsed."""


def _number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {".", "-"}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return round(number, 4)


def _redact(text: str, secret: str) -> str:
    """Keep API keys out of error messages that may contain request URLs."""

    if not secret:
        return text
    return text.replace(secret, "***").replace(
        quote(secret, safe=""), "***"
    )


def _day(value: object) -> str | None:
    text = str(value or "").strip()
    if len(text) >= 8 and text[:8].isdigit():
        try:
            return datetime.strptime(text[:8], "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def _collapse(
    rows: Mapping[str, Mapping[str, float]],
    series: Sequence[str],
) -> list[SeriesPoint]:
    """Keep only dates where at least one requested value changed."""

    events: list[SeriesPoint] = []
    previous: Mapping[str, float] | None = None

    for day in sorted(rows):
        values = {
            key: rows[day][key] for key in series if key in rows[day]
        }
        if len(values) != len(series):
            continue
        if previous is None or any(
            values[key] != previous[key] for key in series
        ):
            events.append(SeriesPoint(day, values))
            previous = values

    return events


def parse_ecos_rows(rows: Sequence[Mapping[str, object]]) -> list[SeriesPoint]:
    """Parse ECOS base-rate rows into effective-date change events."""

    values: dict[str, dict[str, float]] = {}
    for raw in rows:
        day = _day(raw.get("TIME"))
        rate = _number(raw.get("DATA_VALUE"))
        if day is None or rate is None:
            continue
        values[day] = {"kr": rate}
    return _collapse(values, ("kr",))


def _ecos_payload(
    payload: object,
) -> tuple[list[Mapping[str, object]], int]:
    if not isinstance(payload, Mapping):
        raise PolicyError("ECOS returned an invalid response")

    result = payload.get("StatisticSearch")
    if not isinstance(result, Mapping):
        detail = payload.get("RESULT")
        if isinstance(detail, Mapping):
            message = detail.get("MESSAGE") or detail.get("CODE") or "unknown error"
            raise PolicyError(f"ECOS error: {message}")
        raise PolicyError("ECOS returned no StatisticSearch data")

    rows = result.get("row")
    if not isinstance(rows, list):
        raise PolicyError("ECOS response had no rows")

    try:
        total = int(result.get("list_total_count") or 0)
    except (TypeError, ValueError) as exc:
        raise PolicyError("ECOS response had an invalid row count") from exc

    return [row for row in rows if isinstance(row, Mapping)], total


def _ecos_url(
    key: str,
    start: date,
    current: date,
    start_no: int,
    end_no: int,
) -> str:
    return (
        "https://ecos.bok.or.kr/api/StatisticSearch/"
        f"{quote(key, safe='')}/json/kr/{start_no}/{end_no}/"
        f"{ECOS_STAT}/D/{start:%Y%m%d}/{current:%Y%m%d}/{ECOS_ITEM}"
    )


def fetch_korea(
    start: date,
    current: date,
    *,
    api_key: str | None = None,
    timeout: float = 25.0,
    attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
) -> list[SeriesPoint]:
    """Fetch the Bank of Korea base rate from ECOS."""

    key = (api_key if api_key is not None else os.environ.get("ECOS_API_KEY", "")).strip()
    if not key:
        raise PolicyError("ECOS_API_KEY is not set")

    rows: list[Mapping[str, object]] = []
    total = 0
    start_no = 1

    while start_no <= max(total, 1):
        end_no = start_no + ECOS_PAGE - 1
        url = _ecos_url(key, start, current, start_no, end_no)
        try:
            payload = get_json(
                url,
                timeout=timeout,
                attempts=attempts,
                sleep=sleep,
            )
        except FetchError as exc:
            raise PolicyError(_redact(str(exc), key)) from None

        page_rows, total = _ecos_payload(payload)
        rows.extend(page_rows)
        if not page_rows:
            break
        start_no += ECOS_PAGE

    points = parse_ecos_rows(rows)
    points = [
        point
        for point in points
        if start.isoformat() <= point.date <= current.isoformat()
    ]
    if not points:
        raise PolicyError("ECOS returned no base-rate changes")
    return points


def parse_fred_observations(payload: object) -> dict[str, float]:
    """Parse one FRED observations response into ``{iso-date: value}``."""

    if not isinstance(payload, Mapping):
        raise PolicyError("FRED returned an invalid response")

    observations = payload.get("observations")
    if not isinstance(observations, list):
        message = payload.get("error_message") or "no observations"
        raise PolicyError(f"FRED error: {message}")

    values: dict[str, float] = {}
    for raw in observations:
        if not isinstance(raw, Mapping):
            continue
        day = _day(raw.get("date"))
        rate = _number(raw.get("value"))
        if day is not None and rate is not None:
            values[day] = rate
    return values


def _fred_observations(
    series_id: str,
    key: str,
    start: date,
    current: date,
    *,
    timeout: float,
    attempts: int,
    sleep: Callable[[float], None] | None,
) -> dict[str, float]:
    query = urlencode(
        {
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "frequency": "d",
            "observation_start": start.isoformat(),
            "observation_end": current.isoformat(),
            "sort_order": "asc",
        }
    )
    url = f"{FRED_URL}?{query}"
    try:
        payload = get_json(
            url,
            timeout=timeout,
            attempts=attempts,
            sleep=sleep,
        )
    except FetchError as exc:
        raise PolicyError(_redact(str(exc), key)) from None
    return parse_fred_observations(payload)


def fetch_us(
    start: date,
    current: date,
    *,
    api_key: str | None = None,
    timeout: float = 25.0,
    attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
) -> list[SeriesPoint]:
    """Fetch the Federal Reserve target range from FRED."""

    key = (api_key if api_key is not None else os.environ.get("FRED_API_KEY", "")).strip()
    if not key:
        raise PolicyError("FRED_API_KEY is not set")

    upper = _fred_observations(
        "DFEDTARU",
        key,
        start,
        current,
        timeout=timeout,
        attempts=attempts,
        sleep=sleep,
    )
    lower = _fred_observations(
        "DFEDTARL",
        key,
        start,
        current,
        timeout=timeout,
        attempts=attempts,
        sleep=sleep,
    )

    rows = {
        day: {"us_low": lower[day], "us_high": upper[day]}
        for day in sorted(set(upper) & set(lower))
    }
    points = _collapse(rows, ("us_low", "us_high"))
    if not points:
        raise PolicyError("FRED returned no federal-funds target changes")
    return points


def parse_bis_csv(text: str) -> list[SeriesPoint]:
    """Parse a BIS central-bank policy-rate CSV into change events."""

    reader = csv.DictReader(io.StringIO(text))
    fields = set(reader.fieldnames or [])
    if not {"TIME_PERIOD", "OBS_VALUE"}.issubset(fields):
        raise PolicyError(f"unexpected BIS columns: {sorted(fields)}")

    values: dict[str, dict[str, float]] = {}
    for raw in reader:
        day = _day(raw.get("TIME_PERIOD"))
        rate = _number(raw.get("OBS_VALUE"))
        if day is not None and rate is not None:
            values[day] = {"jp": rate}

    points = _collapse(values, ("jp",))
    if not points:
        raise PolicyError("BIS returned no Japan policy-rate changes")
    return points


def fetch_japan(
    start: date,
    current: date,
    *,
    timeout: float = 60.0,
    attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
) -> list[SeriesPoint]:
    """Fetch the BOJ policy target from the BIS policy-rate dataset.

    The BOJ's own API is keyless but only publishes the traded overnight
    call rate; BIS publishes the policy target with effective dates.
    """

    query = urlencode(
        {
            "startPeriod": start.isoformat(),
            "endPeriod": current.isoformat(),
            "format": "csv",
        }
    )
    url = f"{BIS_URL.format(country='JP')}?{query}"
    try:
        text = get_text(
            url,
            timeout=timeout,
            attempts=attempts,
            sleep=sleep,
        )
    except FetchError as exc:
        raise PolicyError(str(exc)) from exc

    points = parse_bis_csv(text)
    points = [
        point
        for point in points
        if start.isoformat() <= point.date <= current.isoformat()
    ]
    if not points:
        raise PolicyError("BIS returned no Japan policy-rate changes")
    return points


def _start_date(
    last: str | None,
    current: date,
    window_days: int = DEFAULT_DAYS,
) -> date:
    """Pick a fetch start that still covers a baseline before ``last``."""

    if last is None:
        return current - timedelta(days=window_days)
    try:
        parsed = date.fromisoformat(last)
    except ValueError:
        return current - timedelta(days=window_days)
    floor = current - timedelta(days=DEFAULT_DAYS)
    return max(parsed - timedelta(days=LOOKBACK_DAYS), floor)


def default_fetchers(
    current: date,
    last_dates: Mapping[str, str] | None = None,
    *,
    window_days: int = DEFAULT_DAYS,
) -> dict[str, Fetcher]:
    """Build the live fetchers, scoped to each country's stored history.

    Existing countries download only a short overlap before their last
    stored event, enough to establish a baseline. New countries use the full
    bootstrap window. This keeps BIS/FRED/ECOS responses small.
    """

    last_dates = last_dates or {}
    return {
        "kr": lambda: fetch_korea(
            _start_date(last_dates.get("kr"), current, window_days),
            current,
        ),
        "jp": lambda: fetch_japan(
            _start_date(last_dates.get("jp"), current, window_days),
            current,
        ),
        "us": lambda: fetch_us(
            _start_date(last_dates.get("us"), current, window_days),
            current,
        ),
    }


def _last_dates(existing: Mapping[str, object] | None) -> dict[str, str]:
    """Find the latest stored event date for each country."""

    latest: dict[str, str] = {}
    if not isinstance(existing, Mapping):
        return latest

    rows = existing.get("points")
    if not isinstance(rows, list):
        return latest

    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        day = _day(raw.get("date"))
        if day is None:
            continue
        for name, keys in COUNTRY_KEYS.items():
            if all(key in raw for key in keys):
                latest[name] = max(latest.get(name, ""), day)
    return latest


def _only_new(
    points: Sequence[SeriesPoint],
    last: str | None,
) -> list[SeriesPoint]:
    """Drop the rolling baseline that is already stored.

    Each fetch returns the full window, so the first row is a synthetic
    baseline rather than a real change. Keeping only dates after the last
    stored event avoids duplicate rows and daily file growth.
    """

    if last is None:
        return list(points)
    return [point for point in points if point.date > last]


def run_fetch_policy(
    data_path: str | Path,
    *,
    days: int | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
    fetchers: Mapping[str, Fetcher] | None = None,
) -> int:
    """Fetch policy rates, merge them into history, and save.

    Countries update independently: a failed source keeps its previous
    events while the other countries are still written.
    """

    path = Path(data_path)
    try:
        existing = timeseries.load(path)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    current = (now or now_kst()).date()
    last_dates = _last_dates(existing)
    candidates = (
        fetchers
        if fetchers is not None
        else default_fetchers(
            current,
            last_dates,
            window_days=days or DEFAULT_DAYS,
        )
    )

    points: list[SeriesPoint] = []
    failures: list[str] = []
    counts: dict[str, int] = {}
    succeeded = 0

    for name, fetch in candidates.items():
        try:
            country_points = fetch()
        except Exception as exc:  # noqa: BLE001 - source failures are expected
            print(f"warning: {name} policy source failed: {exc}", file=sys.stderr)
            failures.append(f"{name}: {exc}")
            continue

        if not country_points:
            print(
                f"warning: {name} policy source returned no points",
                file=sys.stderr,
            )
            failures.append(f"{name}: no points")
            continue

        succeeded += 1
        new_points = _only_new(country_points, last_dates.get(name))
        points.extend(new_points)
        counts[name] = len(new_points)

    if succeeded == 0:
        print("error: all policy-rate sources failed", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    try:
        payload = timeseries.merge(
            existing,
            points,
            SOURCE,
            SERIES,
            kind="policy",
            updated_at=now,
            retain_days=RETAIN_DAYS,
            allow_nonpositive=True,
        )
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not failures else 1

    try:
        timeseries.save(path, payload)
    except OSError as exc:
        print(f"error: could not save {path}: {exc}", file=sys.stderr)
        return 1

    print(timeseries.summary(payload))
    if points:
        print(
            "new policy events: "
            + ", ".join(f"{name} {count}" for name, count in counts.items())
        )
    else:
        print("no new policy-rate changes")
    print(f"saved {path}")

    if failures:
        print("error: some policy series could not be updated", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


__all__ = [
    "DEFAULT_DAYS",
    "RETAIN_DAYS",
    "SERIES",
    "SOURCE",
    "PolicyError",
    "default_fetchers",
    "fetch_japan",
    "fetch_korea",
    "fetch_us",
    "parse_bis_csv",
    "parse_ecos_rows",
    "parse_fred_observations",
    "run_fetch_policy",
]
