"""Fetch monthly Core PCE inflation from FRED."""

from __future__ import annotations

import json
import math
import os
import sys
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from . import timeseries
from .net import FetchError, get_json
from .store import StoreError, age_minutes, now_kst
from .timeseries import SeriesPoint

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
SERIES_ID = "PCEPILFE"
SERIES = ("core_pce_index", "core_pce_mom", "core_pce_yoy")
SOURCE = "fred"
DEFAULT_DAYS = 3650
RETAIN_DAYS = 3650
# A twelve-month year-over-year comparison needs at least 366 days of
# history. The extra margin also covers leap years and month-end dates.
LOOKBACK_DAYS = 400


class PceError(RuntimeError):
    """Raised when the FRED Core PCE feed cannot be read or parsed."""


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
    return number


def _redact(text: str, secret: str) -> str:
    """Keep API keys out of error messages that may contain request URLs."""

    if not secret:
        return text
    return text.replace(secret, "***").replace(quote(secret, safe=""), "***")


def _day(value: object) -> date | None:
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _shift_month(day: date, months: int) -> date:
    """Return the first day of the month shifted by ``months``."""

    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def parse_observations(payload: object) -> dict[date, float]:
    """Parse a FRED observations response into ``{month: index}``."""

    if not isinstance(payload, Mapping):
        raise PceError("FRED returned an invalid response")

    observations = payload.get("observations")
    if not isinstance(observations, list):
        message = payload.get("error_message") or "no observations"
        raise PceError(f"FRED error: {message}")

    values: dict[date, float] = {}
    for raw in observations:
        if not isinstance(raw, Mapping):
            continue
        day = _day(raw.get("date"))
        index = _number(raw.get("value"))
        if day is not None and index is not None and index > 0:
            values[day] = index
    return values


def inflation_points(
    values: Mapping[date, float],
    *,
    start: date | None = None,
) -> list[SeriesPoint]:
    """Calculate MoM and YoY inflation from monthly index levels."""

    points: list[SeriesPoint] = []
    for day in sorted(values):
        index = values[day]
        previous = values.get(_shift_month(day, -1))
        year_ago = values.get(_shift_month(day, -12))
        if previous is None or year_ago is None:
            continue
        if previous <= 0 or year_ago <= 0:
            continue
        if start is not None and day < start:
            continue

        points.append(
            SeriesPoint(
                day.isoformat(),
                {
                    "core_pce_index": index,
                    "core_pce_mom": (index / previous - 1) * 100,
                    "core_pce_yoy": (index / year_ago - 1) * 100,
                },
            )
        )
    return points


def fetch_observations(
    start: date,
    current: date,
    *,
    api_key: str | None = None,
    timeout: float = 25.0,
    attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
) -> dict[date, float]:
    """Fetch the Core PCE index observations between two dates."""

    key = (
        api_key if api_key is not None else os.environ.get("FRED_API_KEY", "")
    ).strip()
    if not key:
        raise PceError("FRED_API_KEY is not set")

    query = urlencode(
        {
            "series_id": SERIES_ID,
            "api_key": key,
            "file_type": "json",
            "frequency": "m",
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
        raise PceError(_redact(str(exc), key)) from None

    try:
        return parse_observations(payload)
    except PceError as exc:
        raise PceError(_redact(str(exc), key)) from None


def fetch_points(
    days: int = DEFAULT_DAYS,
    *,
    today: date | None = None,
    api_key: str | None = None,
    timeout: float = 25.0,
    attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
) -> list[SeriesPoint]:
    """Fetch the last ``days`` of Core PCE inflation."""

    current = today or now_kst().date()
    start = current - timedelta(days=days)
    lookback = start - timedelta(days=LOOKBACK_DAYS)

    values = fetch_observations(
        lookback,
        current,
        api_key=api_key,
        timeout=timeout,
        attempts=attempts,
        sleep=sleep,
    )
    points = inflation_points(values, start=start)
    if not points:
        raise PceError("FRED returned no Core PCE observations in the window")
    return points


def run_fetch_pce(
    data_path: str | Path,
    *,
    days: int | None = None,
    skip_if_fresh: int = 0,
    force: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
    fetcher: Callable[[], list[SeriesPoint]] | None = None,
) -> int:
    """Fetch Core PCE inflation, merge it into history, and save."""

    path = Path(data_path)
    try:
        existing = timeseries.load(path)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if existing and skip_if_fresh > 0 and not force:
        age = age_minutes(existing, now)
        if age is not None and age < skip_if_fresh:
            print(
                f"data is {age:.0f} min old; skipping fetch "
                "(use --force to override)"
            )
            return 0

    current = (now or now_kst()).date()
    fetch = fetcher or (
        lambda: fetch_points(days=days or DEFAULT_DAYS, today=current)
    )

    try:
        points = fetch()
    except Exception as exc:  # noqa: BLE001 - source failures are expected
        print(f"error: Core PCE source failed: {exc}", file=sys.stderr)
        return 1

    if not points:
        print("error: Core PCE source returned no points", file=sys.stderr)
        return 1

    try:
        payload = timeseries.merge(
            existing,
            points,
            SOURCE,
            SERIES,
            kind="pce",
            updated_at=now,
            retain_days=RETAIN_DAYS,
            allow_nonpositive=True,
        )
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    try:
        timeseries.save(path, payload)
    except OSError as exc:
        print(f"error: could not save {path}: {exc}", file=sys.stderr)
        return 1

    print(timeseries.summary(payload))
    print(f"saved {path}")
    return 0


__all__ = [
    "DEFAULT_DAYS",
    "RETAIN_DAYS",
    "SERIES",
    "SERIES_ID",
    "SOURCE",
    "PceError",
    "fetch_observations",
    "fetch_points",
    "inflation_points",
    "parse_observations",
    "run_fetch_pce",
]
