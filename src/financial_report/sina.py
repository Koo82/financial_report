"""Fetch continuous front-month futures from Sina Finance."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import date, timedelta
from urllib.parse import quote

from .net import FetchError, get_text
from .store import now_kst
from .timeseries import SeriesPoint

SYMBOLS = {"gold": "GC", "wti": "CL", "brent": "OIL"}
SERIES = tuple(SYMBOLS)
BASE = (
    "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
    "var%20_{symbol}=/GlobalFuturesService.getGlobalFuturesDailyKLine"
)


class SinaError(RuntimeError):
    """Raised when the Sina futures feed cannot be parsed."""


def _url(symbol: str) -> str:
    stamp = int(time.time())
    return f"{BASE.format(symbol=symbol)}?symbol={quote(symbol)}&_={stamp}"


def _number(value: object) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number <= 0 or not math.isfinite(number):
        return None
    return round(number, 4)


def parse_payload(text: str) -> dict[str, float]:
    """Parse the JSONP body into ``{iso-date: close}``."""

    start = text.find("=(")
    end = text.rfind(")")
    if start == -1 or end <= start:
        raise SinaError("unexpected Sina futures response")

    body = text[start + 2 : end]
    try:
        rows = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SinaError(f"invalid Sina futures JSON: {exc}") from exc

    if not isinstance(rows, list):
        raise SinaError("Sina futures response was not a list")

    closes: dict[str, float] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        close = _number(raw.get("close"))
        if close is None:
            continue
        try:
            day = date.fromisoformat(str(raw.get("date"))[:10])
        except ValueError:
            continue
        closes[day.isoformat()] = close

    if not closes:
        raise SinaError("Sina futures response contained no closes")

    return closes


def fetch_points(
    days: int = 1200,
    *,
    today: date | None = None,
    timeout: float = 30.0,
    attempts: int = 2,
    sleep: Callable[[float], None] | None = None,
) -> list[SeriesPoint]:
    """Fetch gold, WTI and Brent, keeping completed sessions only."""

    current = today or now_kst().date()
    start = current - timedelta(days=days)
    pause = sleep or time.sleep

    series: dict[str, dict[str, float]] = {}
    for key, symbol in SYMBOLS.items():
        try:
            text = get_text(
                _url(symbol),
                timeout=timeout,
                attempts=attempts,
                sleep=sleep,
                headers={"Referer": "https://finance.sina.com.cn/"},
            )
        except FetchError as exc:
            raise SinaError(str(exc)) from exc

        closes = parse_payload(text)
        series[key] = {
            day: close
            for day, close in closes.items()
            if start.isoformat() <= day < current.isoformat()
        }
        pause(0.2)

    shared = set.intersection(*(set(rows) for rows in series.values()))
    if not shared:
        raise SinaError("Sina returned no completed futures sessions")

    return [
        SeriesPoint(day, {key: series[key][day] for key in SERIES})
        for day in sorted(shared)
    ]
