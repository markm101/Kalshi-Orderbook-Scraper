from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kalshi_capture.spread_depth import LatestSpreadRow, build_latest_report, write_latest_report


def print_report(rows: tuple[LatestSpreadRow, ...], limit: int) -> None:
    selected = rows[:limit] if limit > 0 else rows
    print(f"latest_rows: {len(rows)}")
    for row in selected:
        print(
            " ".join(
                (
                    f"category={row.category}",
                    f"ticker={row.ticker}",
                    f"capture_ts_ms={row.capture_ts_ms}",
                    f"book_state={row.book_state}",
                    f"yes_bid={_format_optional(row.yes_best_bid)}",
                    f"yes_ask={_format_optional(row.yes_best_ask)}",
                    f"yes_spread={_format_optional(row.yes_spread)}",
                    f"no_bid={_format_optional(row.no_best_bid)}",
                    f"no_ask={_format_optional(row.no_best_ask)}",
                    f"no_spread={_format_optional(row.no_spread)}",
                )
            )
        )


def _format_optional(value: int | None) -> str:
    return str(value) if value is not None else "(none)"


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Report the latest derived spread for each captured ticker.")
    parser.add_argument("output_dir", type=Path, help="Capture output directory")
    parser.add_argument("--tickers", default="", help="Comma-separated tickers to include")
    parser.add_argument("--categories", default="", help="Comma-separated category partition names to include")
    parser.add_argument("--output-csv", type=Path, help="Optional CSV report path")
    parser.add_argument("--limit", type=int, default=20, help="Rows to print; 0 prints all")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows = build_latest_report(
        args.output_dir,
        tickers=_parse_csv(args.tickers),
        categories=_parse_csv(args.categories),
    )
    print_report(rows, args.limit)
    if args.output_csv:
        write_latest_report(rows, args.output_csv)
        print(f"csv_written: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
