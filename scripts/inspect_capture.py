from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass
class CaptureSummary:
    orderbook_files: int = 0
    orderbook_rows: int = 0
    tickers: set[str] = field(default_factory=set)
    categories: set[str] = field(default_factory=set)
    dates: set[str] = field(default_factory=set)
    min_ts_ms: int | None = None
    max_ts_ms: int | None = None
    gap_events: dict[str, int] = field(default_factory=dict)
    snapshots: set[str] = field(default_factory=set)
    top_level_rows: int = 0
    total_top_level_size: int = 0
    total_size: int = 0
    spread_count: int = 0
    min_yes_spread: int | None = None
    max_yes_spread: int | None = None
    run_summary: dict[str, object] = field(default_factory=dict)


def inspect_capture(output_dir: Path) -> CaptureSummary:
    summary = CaptureSummary()
    categories = _load_ticker_categories(output_dir)
    for path in _orderbook_paths(output_dir):
        summary.orderbook_files += 1
        with path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                summary.orderbook_rows += 1
                ticker = row.get("ticker", "")
                if ticker:
                    summary.tickers.add(ticker)
                    summary.categories.add(categories.get(ticker, "Unknown"))
                _add_ts(summary, row.get("capture_ts_ms", ""))
                _add_date(summary, row.get("capture_ts_ms", ""))
                _add_orderbook_metrics(summary, row)

    gap_path = output_dir / "gaps.csv"
    if gap_path.exists():
        with gap_path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                event_type = row.get("event_type", "") or "unknown"
                summary.gap_events[event_type] = summary.gap_events.get(event_type, 0) + 1

    run_summary_path = output_dir / "run_summary.json"
    if run_summary_path.exists():
        summary.run_summary = json.loads(run_summary_path.read_text())

    _add_spread_metrics(output_dir, summary)
    return summary


def print_summary(summary: CaptureSummary) -> None:
    print(f"orderbook_files: {summary.orderbook_files}")
    print(f"orderbook_rows: {summary.orderbook_rows}")
    print(f"unique_tickers: {len(summary.tickers)}")
    print(f"categories: {', '.join(sorted(summary.categories)) or '(none)'}")
    print(f"dates: {', '.join(sorted(summary.dates)) or '(none)'}")
    print(f"first_capture_ts_ms: {summary.min_ts_ms or '(none)'}")
    print(f"last_capture_ts_ms: {summary.max_ts_ms or '(none)'}")
    print(f"snapshots: {len(summary.snapshots)}")
    print(f"total_size: {summary.total_size}")
    print(f"top_level_rows: {summary.top_level_rows}")
    print(f"total_top_level_size: {summary.total_top_level_size}")
    print(f"yes_spread_count: {summary.spread_count}")
    print(f"min_yes_spread: {summary.min_yes_spread if summary.min_yes_spread is not None else '(none)'}")
    print(f"max_yes_spread: {summary.max_yes_spread if summary.max_yes_spread is not None else '(none)'}")
    if summary.run_summary:
        print("run_summary:")
        for key, value in sorted(summary.run_summary.items()):
            print(f"  {key}: {value}")
    if summary.gap_events:
        print("gap_events:")
        for event_type, count in sorted(summary.gap_events.items()):
            print(f"  {event_type}: {count}")
    else:
        print("gap_events: (none)")


def _add_ts(summary: CaptureSummary, value: str) -> None:
    try:
        ts_ms = int(value)
    except ValueError:
        return

    if summary.min_ts_ms is None or ts_ms < summary.min_ts_ms:
        summary.min_ts_ms = ts_ms
    if summary.max_ts_ms is None or ts_ms > summary.max_ts_ms:
        summary.max_ts_ms = ts_ms


def _add_date(summary: CaptureSummary, value: str) -> None:
    try:
        ts_ms = int(value)
    except ValueError:
        return
    summary.dates.add(datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date().isoformat())


def _add_orderbook_metrics(summary: CaptureSummary, row: dict[str, str]) -> None:
    snapshot_id = row.get("snapshot_id") or f"{row.get('capture_ts_ms', '')}:{row.get('ticker', '')}"
    if snapshot_id != ":":
        summary.snapshots.add(snapshot_id)

    try:
        size = int(row.get("size", "0"))
        level = int(row.get("level", "-1"))
    except ValueError:
        return

    summary.total_size += size
    if level == 0:
        summary.top_level_rows += 1
        summary.total_top_level_size += size


def _add_spread_metrics(output_dir: Path, summary: CaptureSummary) -> None:
    best_by_snapshot: dict[tuple[str, str], dict[str, int]] = {}
    for path in _orderbook_paths(output_dir):
        with path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                if row.get("level") != "0":
                    continue
                snapshot_id = row.get("snapshot_id") or f"{row.get('capture_ts_ms', '')}:{row.get('ticker', '')}"
                side = row.get("side", "")
                try:
                    price = int(row.get("price", ""))
                except ValueError:
                    continue
                best_by_snapshot.setdefault((snapshot_id, row.get("ticker", "")), {})[side] = price

    for sides in best_by_snapshot.values():
        if "yes" not in sides or "no" not in sides:
            continue
        yes_bid = sides["yes"]
        yes_ask = 10000 - sides["no"]
        spread = yes_ask - yes_bid
        summary.spread_count += 1
        if summary.min_yes_spread is None or spread < summary.min_yes_spread:
            summary.min_yes_spread = spread
        if summary.max_yes_spread is None or spread > summary.max_yes_spread:
            summary.max_yes_spread = spread


def _orderbook_paths(output_dir: Path) -> tuple[Path, ...]:
    return tuple(sorted((output_dir / "orderbooks").glob("*.csv")))


def _load_ticker_categories(output_dir: Path) -> dict[str, str]:
    metadata_dir = output_dir / "metadata"
    category_by_series: dict[str, str] = {}
    series_path = metadata_dir / "series.csv"
    if series_path.exists():
        with series_path.open(newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                series_ticker = row.get("series_ticker", "")
                category = row.get("sanitized_category") or row.get("category") or "Unknown"
                if series_ticker:
                    category_by_series[series_ticker] = category

    categories: dict[str, str] = {}
    markets_path = metadata_dir / "markets.csv"
    if markets_path.exists():
        with markets_path.open(newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                ticker = row.get("ticker", "")
                series_ticker = row.get("series_ticker", "")
                if ticker:
                    categories[ticker] = category_by_series.get(series_ticker, "Unknown")
    return categories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect captured Kalshi orderbook CSV output.")
    parser.add_argument("output_dir", type=Path, help="Capture output directory")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print_summary(inspect_capture(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
