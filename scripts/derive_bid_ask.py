from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from pathlib import Path
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kalshi_capture.orderbook import OrderBookRow, derive_bid_ask_rows


RAW_COLUMNS = ("capture_ts_ms", "ticker", "side", "level", "price", "size", "snapshot_id")
DERIVED_COLUMNS = ("capture_ts_ms", "snapshot_id", "ticker", "outcome", "book_side", "level", "price", "size")


def derive_rows(raw_row: dict[str, str]):
    capture_ts_ms = int(raw_row["capture_ts_ms"])
    ticker = raw_row["ticker"]
    row = OrderBookRow(
        capture_ts_ms=capture_ts_ms,
        ticker=ticker,
        side=raw_row["side"],
        level=int(raw_row["level"]),
        price=int(raw_row["price"]),
        size=int(raw_row["size"]),
        snapshot_id=raw_row.get("snapshot_id") or f"{capture_ts_ms}:{ticker}",
    )
    return derive_bid_ask_rows((row,))


def derive_capture(input_dir: Path, output_dir: Path) -> int:
    rows_written = 0
    _copy_metadata(input_dir, output_dir)
    for input_path in sorted((input_dir / "orderbooks").glob("*.csv")):
        output_path = output_dir / input_path.relative_to(input_dir)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with input_path.open(newline="") as input_file, output_path.open("w", newline="") as output_file:
            reader = csv.DictReader(input_file)
            writer = csv.DictWriter(output_file, fieldnames=DERIVED_COLUMNS)
            writer.writeheader()
            for raw_row in reader:
                for derived_row in derive_rows(raw_row):
                    writer.writerow(asdict(derived_row))
                    rows_written += 1
    return rows_written


def _copy_metadata(input_dir: Path, output_dir: Path) -> None:
    input_metadata = input_dir / "metadata"
    if input_metadata.exists():
        shutil.copytree(input_metadata, output_dir / "metadata", dirs_exist_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create bid/ask CSVs from older raw Kalshi orderbook captures.")
    parser.add_argument("input_dir", type=Path, help="Raw capture output directory")
    parser.add_argument("output_dir", type=Path, help="Derived output directory")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows_written = derive_capture(args.input_dir, args.output_dir)
    print(f"derived_rows_written: {rows_written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
