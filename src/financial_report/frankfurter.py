"""Fallback source: European Central Bank reference rates via Frankfurter."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .store import Point

BASE_URL = "https://api.frankfurter.dev/v1"
USER_AGENT = "financial-report/0.1 (+https://github.com/)"


class FrankfurterError(RuntimeError):
    """Raised when Frankfurter cannot be reached or returns unusable data."""


def _get_json(
    path: str,
    params: Mapping[str, str],
    *,
    timeout: float = 20.0,
    attempts: int = 2,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    query = urlencode(params)
    url = f"{BASE_URL}{path}?{query}" if query else f"{BASE_URL}{path}"
    wait = sleep or time.sleep
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            request = Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            if isinstance(payload, dict):
                return payload
            last_error = FrankfurterError("unexpected response shape")
        except (OSError, ValueError) as exc:
            last_error = exc

        if attempt < attempts - 1:
            wait(2.0)

    raise FrankfurterError(f"Frankfurter request failed: {last_error}")


def _cross_rates(row: Mapping[str, Any]) -> tuple[float, float] | None:
    """Turn ``KRW -> USD/JPY`` rates into ``USD/KRW`` and ``100 JPY/KRW``."""

    try:
        usd_per_krw = float(row["USD"])
        jpy_per_krw = float(row["JPY"])
    except KeyError, TypeError, ValueError:
        return None

    if not all(
        math.isfinite(value) and value > 0 for value in (usd_per_krw, jpy_per_krw)
    ):
        return None

    return round(1 / usd_per_krw, 4), round(100 / jpy_per_krw, 4)


def parse_payload(payload: Mapping[str, Any]) -> list[Point]:
    """Handle both the ``/latest`` and date-range response shapes."""

    rates = payload.get("rates")
    if not isinstance(rates, Mapping):
        raise FrankfurterError("Frankfurter payload has no rates")

    rows: list[tuple[str, Mapping[str, Any]]] = []
    if "date" in payload and isinstance(rates.get("USD"), (int, float)):
        rows.append((str(payload["date"]), rates))
    else:
        for day, row in rates.items():
            if isinstance(row, Mapping):
                rows.append((str(day), row))

    points: list[Point] = []
    for day, row in rows:
        try:
            date.fromisoformat(day)
        except ValueError:
            continue
        converted = _cross_rates(row)
        if converted is None:
            continue
        points.append(Point(day, converted[0], converted[1]))

    if not points:
        raise FrankfurterError("Frankfurter returned no usable rates")

    return sorted(points, key=lambda point: point.date)


def fetch_points(
    start: str | None = None,
    end: str | None = None,
    *,
    timeout: float = 20.0,
    attempts: int = 2,
    sleep: Callable[[float], None] | None = None,
) -> list[Point]:
    if start is None:
        payload = _get_json(
            "/latest",
            {"base": "KRW", "symbols": "USD,JPY"},
            timeout=timeout,
            attempts=attempts,
            sleep=sleep,
        )
    else:
        last_day = end or date.today().isoformat()
        payload = _get_json(
            f"/{start}..{last_day}",
            {"base": "KRW", "symbols": "USD,JPY"},
            timeout=timeout,
            attempts=attempts,
            sleep=sleep,
        )

    return parse_payload(payload)


def default_start(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()
