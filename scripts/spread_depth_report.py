from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kalshi_capture.spread_depth import ReportRow, build_report, write_report


def print_report(rows: tuple[ReportRow, ...], limit: int) -> None:
    selected = rows[:limit] if limit > 0 else rows
    print(f"report_rows: {len(rows)}")
    for row in selected:
        print(
            " ".join(
                (
                    f"category={row.category}",
                    f"ticker={row.ticker}",
                    f"outcome={row.outcome}",
                    f"snapshots={row.snapshots}",
                    f"spread_snapshots={row.spread_snapshots}",
                    f"avg_spread={row.avg_spread}",
                    f"min_spread={row.min_spread if row.min_spread is not None else '(none)'}",
                    f"max_spread={row.max_spread if row.max_spread is not None else '(none)'}",
                    f"avg_top_bid_size={row.avg_top_bid_size}",
                    f"avg_top_ask_size={row.avg_top_ask_size}",
                    f"avg_total_bid_size={row.avg_total_bid_size}",
                    f"avg_total_ask_size={row.avg_total_ask_size}",
                )
            )
        )


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report spread and depth metrics from bid/ask capture CSVs.")
    parser.add_argument("output_dir", type=Path, help="Capture output directory")
    parser.add_argument("--tickers", default="", help="Comma-separated tickers to include")
    parser.add_argument("--categories", default="", help="Comma-separated category partition names to include")
    parser.add_argument("--outcomes", default="", help="Comma-separated outcomes to include: yes,no")
    parser.add_argument("--output-csv", type=Path, help="Optional CSV report path")
    parser.add_argument("--limit", type=int, default=20, help="Rows to print; 0 prints all")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = build_report(
        args.output_dir,
        tickers=_parse_csv(args.tickers),
        categories=_parse_csv(args.categories),
        outcomes=_parse_csv(args.outcomes),
    )
    print_report(rows, args.limit)
    if args.output_csv:
        write_report(rows, args.output_csv)
        print(f"csv_written: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
