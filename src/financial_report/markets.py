"""Fetch and store Treasury yields and commodity futures."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import eastmoney, sina, store, timeseries, treasury

BOOTSTRAP_DAYS = 1200
INCREMENTAL_DAYS = 14

Source = tuple[str, Callable[[], list[timeseries.SeriesPoint]]]


@dataclass(frozen=True, slots=True)
class Group:
    name: str
    filename: str
    kind: str
    series: tuple[str, ...]


GROUPS = {
    "yields": Group(
        name="yields",
        filename="yields.json",
        kind="yields",
        series=("us5y", "us10y", "us30y"),
    ),
    "futures": Group(
        name="futures",
        filename="futures.json",
        kind="futures",
        series=("gold", "wti", "brent"),
    ),
}


def build_sources(name: str, days: int) -> list[Source]:
    if name == "yields":
        return [("treasury", lambda: treasury.fetch_points(days=days))]
    if name == "futures":
        return [
            ("sina", lambda: sina.fetch_points(days=days)),
            ("eastmoney", lambda: eastmoney.fetch_points(days=days)),
        ]
    raise KeyError(name)


def run_fetch_markets(
    data_dir: str | Path,
    groups: Sequence[str] = ("yields", "futures"),
    *,
    days: int | None = None,
    skip_if_fresh: int = 0,
    force: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
    sources_by_group: Mapping[str, Sequence[Source]] | None = None,
) -> int:
    """Update each requested group independently.

    A failed group keeps its previous file, so one broken source cannot
    erase history for the others.
    """

    directory = Path(data_dir)
    failures: list[str] = []

    for name in groups:
        group = GROUPS[name]
        path = directory / group.filename

        try:
            existing = timeseries.load(path)
        except store.StoreError as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures.append(f"{name}: {exc}")
            continue

        has_history = bool(existing and existing.get("points"))
        window = days or (INCREMENTAL_DAYS if has_history else BOOTSTRAP_DAYS)

        if existing and skip_if_fresh > 0 and not force:
            age = store.age_minutes(existing, now)
            if age is not None and age < skip_if_fresh:
                print(
                    f"{name}: data is {age:.0f} min old; "
                    "skipping fetch (use --force to override)"
                )
                continue

        if sources_by_group is None:
            candidates = build_sources(name, window)
        else:
            candidates = list(sources_by_group.get(name, ()))

        for source_name, fetch in candidates:
            try:
                points = fetch()
            except Exception as exc:  # noqa: BLE001 - source failures are expected
                print(
                    f"warning: {name} source {source_name} failed: {exc}",
                    file=sys.stderr,
                )
                continue

            if not points:
                print(
                    f"warning: {name} source {source_name} returned no points",
                    file=sys.stderr,
                )
                continue

            try:
                payload = timeseries.merge(
                    existing,
                    points,
                    source_name,
                    group.series,
                    kind=group.kind,
                    updated_at=now,
                )
            except store.StoreError as exc:
                print(
                    f"warning: {name} source {source_name} produced "
                    f"invalid data: {exc}",
                    file=sys.stderr,
                )
                continue

            if dry_run:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                break

            try:
                timeseries.save(path, payload)
            except OSError as exc:
                failures.append(f"{name}: could not save {path}: {exc}")
                print(f"error: could not save {path}: {exc}", file=sys.stderr)
                break

            print(timeseries.summary(payload))
            print(f"saved {path}")
            break
        else:
            failures.append(f"{name}: all sources failed")
            print(f"error: all {name} sources failed", file=sys.stderr)

    if not failures:
        return 0

    print("error: some market series could not be updated", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    return 1


__all__ = [
    "BOOTSTRAP_DAYS",
    "GROUPS",
    "INCREMENTAL_DAYS",
    "Group",
    "Source",
    "build_sources",
    "run_fetch_markets",
]
