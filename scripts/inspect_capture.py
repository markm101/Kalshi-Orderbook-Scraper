from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
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


def inspect_capture(output_dir: Path) -> CaptureSummary:
    summary = CaptureSummary()
    for path in sorted((output_dir / "orderbooks").glob("category=*/date=*/orderbook.csv")):
        summary.orderbook_files += 1
        _add_partition_values(path, summary)
        with path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                summary.orderbook_rows += 1
                ticker = row.get("ticker", "")
                if ticker:
                    summary.tickers.add(ticker)
                _add_ts(summary, row.get("capture_ts_ms", ""))

    gap_path = output_dir / "gaps.csv"
    if gap_path.exists():
        with gap_path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                event_type = row.get("event_type", "") or "unknown"
                summary.gap_events[event_type] = summary.gap_events.get(event_type, 0) + 1

    return summary


def print_summary(summary: CaptureSummary) -> None:
    print(f"orderbook_files: {summary.orderbook_files}")
    print(f"orderbook_rows: {summary.orderbook_rows}")
    print(f"unique_tickers: {len(summary.tickers)}")
    print(f"categories: {', '.join(sorted(summary.categories)) or '(none)'}")
    print(f"dates: {', '.join(sorted(summary.dates)) or '(none)'}")
    print(f"first_capture_ts_ms: {summary.min_ts_ms or '(none)'}")
    print(f"last_capture_ts_ms: {summary.max_ts_ms or '(none)'}")
    if summary.gap_events:
        print("gap_events:")
        for event_type, count in sorted(summary.gap_events.items()):
            print(f"  {event_type}: {count}")
    else:
        print("gap_events: (none)")


def _add_partition_values(path: Path, summary: CaptureSummary) -> None:
    for part in path.parts:
        if part.startswith("category="):
            summary.categories.add(part.removeprefix("category="))
        elif part.startswith("date="):
            summary.dates.add(part.removeprefix("date="))


def _add_ts(summary: CaptureSummary, value: str) -> None:
    try:
        ts_ms = int(value)
    except ValueError:
        return

    if summary.min_ts_ms is None or ts_ms < summary.min_ts_ms:
        summary.min_ts_ms = ts_ms
    if summary.max_ts_ms is None or ts_ms > summary.max_ts_ms:
        summary.max_ts_ms = ts_ms


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
