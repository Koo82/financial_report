"""Persist and merge generic daily market series.

The FX history keeps its own file and schema; this module handles the
multi-column Treasury and futures files.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .store import KST, RETAIN_DAYS, StoreError, age_minutes, now_kst

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    """One date with one or more named values."""

    date: str
    values: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {"date": self.date, **self.values}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    return round(number, 4)


def _day(value: Any) -> str | None:
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
    return parsed.isoformat()


def make_point(
    day: Any, raw: Mapping[str, Any], series: Sequence[str]
) -> SeriesPoint | None:
    """Validate one row, keeping only known positive numeric values."""

    parsed = _day(day)
    if parsed is None:
        return None

    values: dict[str, float] = {}
    for key in series:
        number = _number(raw.get(key))
        if number is not None:
            values[key] = number

    if not values:
        return None
    return SeriesPoint(parsed, values)


def load(path: str | Path) -> dict[str, Any] | None:
    """Read a series file. Returns ``None`` when it does not exist yet."""

    file = Path(path)
    if not file.exists():
        return None

    try:
        payload = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"could not read {file}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
        raise StoreError(f"{file} is not a valid series file")

    series = payload.get("series")
    if not isinstance(series, list) or not all(
        isinstance(key, str) for key in series
    ):
        raise StoreError(f"{file} is missing its series list")

    return payload


def merge(
    existing: Mapping[str, Any] | None,
    points: Iterable[SeriesPoint],
    source: str,
    series: Sequence[str],
    *,
    kind: str,
    updated_at: datetime | None = None,
    retain_days: int = RETAIN_DAYS,
) -> dict[str, Any]:
    """Merge new columns into history; new values win for the same date."""

    by_date: dict[str, dict[str, float]] = {}

    if existing:
        old_series = existing.get("series") or series
        old_series = [
            key for key in old_series if isinstance(key, str) and key in series
        ]
        for raw in existing.get("points", []):
            if not isinstance(raw, Mapping):
                continue
            point = make_point(raw.get("date"), raw, old_series)
            if point is not None:
                by_date.setdefault(point.date, {}).update(point.values)

    for point in points:
        clean = make_point(point.date, point.values, series)
        if clean is not None:
            by_date.setdefault(clean.date, {}).update(clean.values)

    ordered = [key for key in sorted(by_date) if by_date[key]]
    if not ordered:
        raise StoreError("no valid series points to save")

    cutoff = date.fromisoformat(ordered[-1]) - timedelta(days=retain_days)
    ordered = [key for key in ordered if date.fromisoformat(key) >= cutoff]

    stamp = (updated_at or now_kst()).astimezone(KST)

    return {
        "version": SCHEMA_VERSION,
        "kind": kind,
        "updatedAt": stamp.isoformat(timespec="seconds"),
        "source": source,
        "series": list(series),
        "points": [
            {"date": key, **by_date[key]}
            for key in ordered
        ],
    }


def save(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Write the series file atomically."""

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


def summary(payload: Mapping[str, Any]) -> str:
    """One-line description used by the CLI."""

    points = payload.get("points") or []
    if not points:
        return "no points"

    latest = points[-1]
    values = []
    for key in payload.get("series", []):
        if key in latest:
            values.append(f"{key} {latest[key]:,.4f}")

    return (
        f"{payload.get('source', '?')}: {latest.get('date')} "
        f"{' · '.join(values)} ({len(points)} points)"
    )


__all__ = [
    "SCHEMA_VERSION",
    "SeriesPoint",
    "age_minutes",
    "load",
    "make_point",
    "merge",
    "save",
    "summary",
]
