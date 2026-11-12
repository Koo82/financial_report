"""Fallback futures collector using Eastmoney's continuous contracts."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import date, timedelta
from urllib.parse import urlencode

from .net import FetchError, get_text
from .store import now_kst
from .timeseries import SeriesPoint

SECIDS = {"gold": "101.GC00Y", "wti": "102.CL00Y", "brent": "112.B00Y"}
SERIES = tuple(SECIDS)
HOSTS = (
    "https://push2his.eastmoney.com",
    "https://push2delay.eastmoney.com",
    "https://push2.eastmoney.com",
)
PATH = "/api/qt/stock/kline/get"


class EastmoneyError(RuntimeError):
    """Raised when the Eastmoney futures feed cannot be parsed."""


def _url(host: str, secid: str, start: date, end: date) -> str:
    query = urlencode(
        {
            "secid": secid,
            "klt": "101",
            "fqt": "0",
            "beg": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "fields1": "f1,f2,f3,f4,f5",
            "fields2": "f51,f52,f53",
        }
    )
    return f"{host}{PATH}?{query}"


def _number(value: object) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number <= 0 or not math.isfinite(number):
        return None
    return round(number, 4)


def parse_payload(
    text: str, *, today: date | None = None
) -> dict[str, float]:
    """Parse one Eastmoney kline response into ``{iso-date: close}``."""

    current = today or now_kst().date()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EastmoneyError(f"invalid Eastmoney JSON: {exc}") from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise EastmoneyError("Eastmoney returned no data")

    rows = data.get("klines")
    if not isinstance(rows, list):
        raise EastmoneyError("Eastmoney response had no klines")

    closes: dict[str, float] = {}
    for raw in rows:
        if not isinstance(raw, str):
            continue
        parts = raw.split(",")
        if len(parts) < 3:
            continue

        close = _number(parts[2])
        if close is None:
            continue
        try:
            day = date.fromisoformat(parts[0][:10])
        except ValueError:
            continue
        if day >= current:
            continue

        closes[day.isoformat()] = close

    if not closes:
        raise EastmoneyError("Eastmoney response contained no closes")

    return closes


def _fetch_one(
    secid: str,
    start: date,
    current: date,
    *,
    timeout: float,
    sleep: Callable[[float], None] | None,
) -> dict[str, float]:
    pause = sleep or time.sleep
    errors: list[str] = []

    for host in HOSTS:
        try:
            text = get_text(
                _url(host, secid, start, current),
                timeout=timeout,
                attempts=1,
                sleep=sleep,
                headers={"Referer": "https://quote.eastmoney.com/"},
            )
            return parse_payload(text, today=current)
        except (FetchError, EastmoneyError) as exc:
            errors.append(f"{host}: {exc}")
            pause(0.3)

    raise EastmoneyError("; ".join(errors))


def fetch_points(
    days: int = 1200,
    *,
    today: date | None = None,
    timeout: float = 20.0,
    sleep: Callable[[float], None] | None = None,
) -> list[SeriesPoint]:
    """Fetch gold, WTI and Brent, keeping completed sessions only."""

    current = today or now_kst().date()
    start = current - timedelta(days=days)
    pause = sleep or time.sleep

    series: dict[str, dict[str, float]] = {}
    for key, secid in SECIDS.items():
        closes = _fetch_one(
            secid,
            start,
            current,
            timeout=timeout,
            sleep=sleep,
        )
        series[key] = {
            day: close
            for day, close in closes.items()
            if day >= start.isoformat()
        }
        pause(0.4)

    shared = set.intersection(*(set(rows) for rows in series.values()))
    if not shared:
        raise EastmoneyError("Eastmoney returned no completed futures sessions")

    return [
        SeriesPoint(day, {key: series[key][day] for key in SERIES})
        for day in sorted(shared)
    ]
