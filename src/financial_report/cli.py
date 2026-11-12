"""Command line entry point for fetching and storing market data."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from . import frankfurter, markets, store, yahoo

Source = tuple[str, Callable[[], list[store.Point]]]

BOOTSTRAP_DAYS = 1200
INCREMENTAL_DAYS = 14


def build_sources(existing: dict | None, days: int | None = None) -> list[Source]:
    has_history = bool(existing and existing.get("points"))
    window = days or (INCREMENTAL_DAYS if has_history else BOOTSTRAP_DAYS)

    return [
        ("yahoo", lambda: yahoo.fetch_points(days=window)),
        (
            "frankfurter",
            lambda: frankfurter.fetch_points(
                start=frankfurter.default_start(window)
            ),
        ),
    ]


def run_fetch(
    data_path: str | Path,
    sources: Sequence[Source] | None = None,
    *,
    skip_if_fresh: int = 0,
    force: bool = False,
    dry_run: bool = False,
    days: int | None = None,
    now: datetime | None = None,
) -> int:
    """Fetch from the first working source, merge, and save.

    Returns a process exit code. A failure never overwrites existing history.
    """

    try:
        existing = store.load(data_path)
    except store.StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if existing and skip_if_fresh > 0 and not force:
        age = store.age_minutes(existing, now)
        if age is not None and age < skip_if_fresh:
            print(
                f"data is {age:.0f} min old; skipping fetch (use --force to override)"
            )
            return 0

    candidates = (
        list(sources) if sources is not None else build_sources(existing, days)
    )
    failures: list[str] = []

    for name, fetch in candidates:
        try:
            points = fetch()
        except Exception as exc:  # noqa: BLE001 - source failures are expected
            failures.append(f"{name}: {exc}")
            print(f"warning: {name} failed: {exc}", file=sys.stderr)
            continue

        if not points:
            failures.append(f"{name}: no points")
            print(f"warning: {name} returned no points", file=sys.stderr)
            continue

        try:
            payload = store.merge(existing, points, name, updated_at=now)
        except store.StoreError as exc:
            failures.append(f"{name}: {exc}")
            print(f"warning: {name} produced invalid data: {exc}", file=sys.stderr)
            continue

        if dry_run:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        try:
            store.save(data_path, payload)
        except OSError as exc:
            print(f"error: could not save {data_path}: {exc}", file=sys.stderr)
            return 1

        print(store.format_summary(payload))
        print(f"saved {data_path}")
        return 0

    print("error: all rate sources failed", file=sys.stderr)
    for failure in failures:
        print(f"  - {failure}", file=sys.stderr)
    return 1


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a whole number") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="financial-report",
        description=(
            "Fetch daily exchange rates, US Treasury yields, and "
            "commodity futures."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="fetch rates and update history")
    fetch.add_argument(
        "--data",
        default="data/rates.json",
        help="history file to update (default: data/rates.json)",
    )
    fetch.add_argument(
        "--days",
        type=_positive_int,
        default=None,
        metavar="N",
        help=(
            "backfill window in days (default: 14 with existing history, "
            "1200 on the first run)"
        ),
    )
    fetch.add_argument(
        "--skip-if-fresh",
        type=int,
        default=0,
        metavar="MINUTES",
        help="skip when the file was updated less than MINUTES ago",
    )
    fetch.add_argument(
        "--force",
        action="store_true",
        help="ignore --skip-if-fresh",
    )
    fetch.add_argument(
        "--dry-run",
        action="store_true",
        help="print the merged JSON without writing the file",
    )
    fetch.add_argument(
        "--source",
        choices=("auto", "yahoo", "frankfurter"),
        default="auto",
        help="restrict the data source (default: auto with fallback)",
    )

    market = subparsers.add_parser(
        "fetch-markets",
        help="fetch Treasury yields and commodity futures",
    )
    market.add_argument(
        "--data-dir",
        default="data",
        help="directory holding yields.json and futures.json (default: data)",
    )
    market.add_argument(
        "--group",
        choices=("all", "yields", "futures"),
        default="all",
        help="series group to update (default: all)",
    )
    market.add_argument(
        "--days",
        type=_positive_int,
        default=None,
        metavar="N",
        help=(
            "backfill window in days (default: 14 with existing history, "
            "1200 on the first run)"
        ),
    )
    market.add_argument(
        "--skip-if-fresh",
        type=int,
        default=0,
        metavar="MINUTES",
        help="skip a group when its file was updated less than MINUTES ago",
    )
    market.add_argument(
        "--force",
        action="store_true",
        help="ignore --skip-if-fresh",
    )
    market.add_argument(
        "--dry-run",
        action="store_true",
        help="print the merged JSON without writing files",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "fetch-markets":
        groups = (
            ("yields", "futures") if args.group == "all" else (args.group,)
        )
        return markets.run_fetch_markets(
            args.data_dir,
            groups,
            days=args.days,
            skip_if_fresh=args.skip_if_fresh,
            force=args.force,
            dry_run=args.dry_run,
        )

    sources: Sequence[Source] | None = None
    if args.source != "auto":
        try:
            existing = store.load(args.data)
        except store.StoreError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        sources = [
            source
            for source in build_sources(existing, args.days)
            if source[0] == args.source
        ]

    return run_fetch(
        args.data,
        sources,
        skip_if_fresh=args.skip_if_fresh,
        force=args.force,
        dry_run=args.dry_run,
        days=args.days,
    )
