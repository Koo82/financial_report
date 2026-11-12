"""Persist and merge the daily exchange-rate history."""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 1
RETAIN_DAYS = 1200


class StoreError(RuntimeError):
    """Raised when the on-disk history cannot be read or written."""


@dataclass(frozen=True, slots=True)
class Point:
    """One day of rates. ``jpy_krw_100`` is the price of 100 Japanese yen."""

    date: str
    usd_krw: float
    jpy_krw_100: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "usdKrw": self.usd_krw,
            "jpyKrw100": self.jpy_krw_100,
        }


def now_kst() -> datetime:
    return datetime.now(KST)


def make_point(day: Any, usd_krw: Any, jpy_krw_100: Any) -> Point | None:
    """Validate and normalize one point, returning ``None`` for bad input."""

    try:
        parsed = date.fromisoformat(str(day)[:10])
    except TypeError, ValueError:
        return None

    values: list[float] = []
    for value in (usd_krw, jpy_krw_100):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            return None
        values.append(round(number, 4))

    return Point(parsed.isoformat(), values[0], values[1])


def load(path: str | Path) -> dict[str, Any] | None:
    """Read the history file. Returns ``None`` when it does not exist yet."""

    file = Path(path)
    if not file.exists():
        return None

    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"could not read {file}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
        raise StoreError(f"{file} is not a valid rates file")

    return payload


def merge(
    existing: Mapping[str, Any] | None,
    points: Iterable[Point],
    source: str,
    *,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    """Merge new points into history; a new value wins for the same date."""

    by_date: dict[str, Point] = {}

    if existing:
        for raw in existing.get("points", []):
            if not isinstance(raw, Mapping):
                continue
            point = make_point(raw.get("date"), raw.get("usdKrw"), raw.get("jpyKrw100"))
            if point is not None:
                by_date[point.date] = point

    for point in points:
        by_date[point.date] = point

    ordered = [by_date[key] for key in sorted(by_date)]
    if not ordered:
        raise StoreError("no valid rate points to save")

    cutoff = date.fromisoformat(ordered[-1].date) - timedelta(days=RETAIN_DAYS)
    ordered = [point for point in ordered if date.fromisoformat(point.date) >= cutoff]

    stamp = (updated_at or now_kst()).astimezone(KST)

    return {
        "version": SCHEMA_VERSION,
        "updatedAt": stamp.isoformat(timespec="seconds"),
        "source": source,
        "points": [point.as_dict() for point in ordered],
    }


def save(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write the history atomically so a failed run cannot corrupt it."""

    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    handle, temp_name = tempfile.mkstemp(
        prefix=f".{file.name}.", suffix=".tmp", dir=file.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, file)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def age_minutes(
    payload: Mapping[str, Any], now: datetime | None = None
) -> float | None:
    """Minutes since the payload was written, or ``None`` if unknown."""

    stamp = payload.get("updatedAt")
    if not isinstance(stamp, str):
        return None

    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)

    current = now or now_kst()
    return max(0.0, (current - parsed).total_seconds() / 60)


def format_summary(payload: Mapping[str, Any]) -> str:
    points = payload.get("points") or []
    if not points:
        return "no points"
    latest = points[-1]
    return (
        f"{payload.get('source', '?')}: {latest.get('date')} "
        f"USD/KRW {latest.get('usdKrw', 0):,.2f} · "
        f"100 JPY/KRW {latest.get('jpyKrw100', 0):,.2f} "
        f"({len(points)} points)"
    )
