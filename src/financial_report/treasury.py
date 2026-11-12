"""Fetch the official US Treasury par yield curve."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Callable
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from .net import FetchError, get_text
from .store import now_kst
from .timeseries import SeriesPoint

BASE = (
    "https://home.treasury.gov/resource-center/data-chart-center/"
    "interest-rates/daily-treasury-rates.csv/{year}/all"
)
COLUMNS = {"us5y": "5 Yr", "us10y": "10 Yr", "us30y": "30 Yr"}
SERIES = tuple(COLUMNS)


class TreasuryError(RuntimeError):
    """Raised when the Treasury feed cannot be parsed."""


def _url(year: int) -> str:
    query = urlencode(
        {
            "type": "daily_treasury_yield_curve",
            "field_tdr_date_value": str(year),
            "page": "",
            "_format": "csv",
        }
    )
    return f"{BASE.format(year=year)}?{query}"


def _number(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return round(number, 4)


def _day(value: object) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(str(value).strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_csv(text: str, *, series: tuple[str, ...] = SERIES) -> list[SeriesPoint]:
    """Parse one annual Treasury CSV, sorted oldest-first."""

    reader = csv.DictReader(io.StringIO(text))
    fields = {name.strip() for name in (reader.fieldnames or []) if name}
    required = {"Date", *(COLUMNS[key] for key in series)}
    if not required.issubset(fields):
        raise TreasuryError(f"unexpected Treasury columns: {sorted(fields)}")

    rows: dict[str, dict[str, float]] = {}
    for raw in reader:
        day = _day(raw.get("Date"))
        if day is None:
            continue

        values: dict[str, float] = {}
        for key in series:
            number = _number(raw.get(COLUMNS[key]))
            if number is not None:
                values[key] = number

        if len(values) == len(series):
            rows[day.isoformat()] = values

    if not rows:
        raise TreasuryError("Treasury CSV contained no usable yields")

    return [
        SeriesPoint(day, rows[day])
        for day in sorted(rows)
    ]


def fetch_points(
    days: int = 1200,
    *,
    today: date | None = None,
    timeout: float = 25.0,
    attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
) -> list[SeriesPoint]:
    """Fetch the last ``days`` of 5/10/30-year yields."""

    current = today or now_kst().date()
    start = current - timedelta(days=days)

    rows: dict[str, dict[str, float]] = {}
    for year in range(start.year, current.year + 1):
        try:
            text = get_text(
                _url(year),
                timeout=timeout,
                attempts=attempts,
                sleep=sleep,
            )
        except FetchError as exc:
            raise TreasuryError(str(exc)) from exc

        for point in parse_csv(text):
            day = date.fromisoformat(point.date)
            if start <= day <= current:
                rows[point.date] = point.values

    if not rows:
        raise TreasuryError("Treasury returned no yields in the requested window")

    return [
        SeriesPoint(day, rows[day])
        for day in sorted(rows)
    ]
