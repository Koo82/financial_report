"""Fetch daily USD/KRW and JPY/KRW quotes from Yahoo Finance.

Yahoo's chart endpoint is unofficial and aggressively rate limits shared IPs,
so every request tries both query hosts and retries with backoff. The caller
is expected to fall back to another source when this module raises.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .store import KST, Point

HOSTS = (
    "https://query1.finance.yahoo.com",
    "https://query2.finance.yahoo.com",
)
SYMBOLS = {
    "usd": "USDKRW=X",
    "jpy": "JPYKRW=X",
}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class YahooError(RuntimeError):
    """Raised when Yahoo cannot be reached or returns unusable data."""


def _get_json(
    path: str,
    params: Mapping[str, str],
    *,
    timeout: float = 15.0,
    attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    query = urlencode(params)
    url_path = f"{path}?{query}" if query else path
    wait = sleep or time.sleep
    last_error: Exception | None = None

    for attempt in range(attempts):
        for host in HOSTS:
            request = Request(
                f"{host}{url_path}",
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json,text/plain,*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    payload = json.load(response)
            except (OSError, ValueError) as exc:
                last_error = exc
                continue
            if isinstance(payload, dict):
                return payload
            last_error = YahooError("unexpected response shape")

        if attempt < attempts - 1:
            wait(min(20.0, 2.0 * (2**attempt)))

    raise YahooError(f"Yahoo Finance request failed: {last_error}")


def parse_chart_payload(payload: Mapping[str, Any]) -> dict[str, float]:
    """Extract ``{date: close}`` from a Yahoo chart response.

    Timestamps are converted to KST so a daily bar keeps the date Korean
    users expect, even though Yahoo reports FX time in London/GMT.
    """

    try:
        result = payload["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError) as exc:
        raise YahooError("unexpected Yahoo chart payload") from exc

    if not isinstance(timestamps, list) or not isinstance(closes, list):
        raise YahooError("unexpected Yahoo chart payload")

    series: dict[str, float] = {}
    for stamp, close in zip(timestamps, closes):
        if close is None or isinstance(close, bool):
            continue
        try:
            value = float(close)
            moment = datetime.fromtimestamp(float(stamp), KST)
        except TypeError, ValueError, OSError, OverflowError:
            continue
        if value <= 0:
            continue
        # A later bar for the same day wins (Yahoo sometimes repeats a day).
        series[moment.date().isoformat()] = value

    if not series:
        raise YahooError("Yahoo returned no usable closes")

    return series


def align_series(
    usd: Mapping[str, float],
    jpy: Mapping[str, float],
) -> list[Point]:
    """Join both series, forward-filling a side that has no quote that day."""

    points: list[Point] = []
    last_usd: float | None = None
    last_jpy: float | None = None

    for day in sorted(set(usd) | set(jpy)):
        if day in usd:
            last_usd = usd[day]
        if day in jpy:
            last_jpy = jpy[day]
        if last_usd is None or last_jpy is None:
            continue
        points.append(
            Point(
                date=day,
                usd_krw=round(last_usd, 4),
                jpy_krw_100=round(last_jpy * 100, 4),
            )
        )

    return points


def fetch_points(
    days: int = 180,
    interval: str = "1d",
    *,
    timeout: float = 15.0,
    attempts: int = 3,
    sleep: Callable[[float], None] | None = None,
) -> list[Point]:
    """Fetch both symbols for the last ``days`` and return aligned points."""

    end = int(time.time())
    start = end - days * 86_400

    series: dict[str, dict[str, float]] = {}
    for key, symbol in SYMBOLS.items():
        payload = _get_json(
            f"/v8/finance/chart/{symbol}",
            {
                "period1": str(start),
                "period2": str(end + 86_400),
                "interval": interval,
                "includePrePost": "false",
                "events": "div,split",
            },
            timeout=timeout,
            attempts=attempts,
            sleep=sleep,
        )
        series[key] = parse_chart_payload(payload)

    return align_series(series["usd"], series["jpy"])
