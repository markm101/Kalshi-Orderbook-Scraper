from __future__ import annotations

import csv
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path

from kalshi_capture.discovery import DiscoveryResult, MarketMetadata, SeriesMetadata, UNKNOWN_CATEGORY
from kalshi_capture.orderbook import OrderBookRow


def write_metadata(output_dir: Path, discovery: DiscoveryResult) -> None:
    metadata_dir = output_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    _write_dataclass_csv(metadata_dir / "markets.csv", discovery.markets, MarketMetadata)
    _write_dataclass_csv(metadata_dir / "series.csv", discovery.series, SeriesMetadata)


def write_orderbook_rows(
    output_dir: Path,
    rows: tuple[OrderBookRow, ...],
    ticker_categories: dict[str, str],
) -> None:
    rows_by_path: dict[Path, list[OrderBookRow]] = {}
    for row in rows:
        category = ticker_categories.get(row.ticker, UNKNOWN_CATEGORY)
        date = datetime.fromtimestamp(row.capture_ts_ms / 1000, tz=UTC).date().isoformat()
        path = output_dir / "orderbooks" / f"category={category}" / f"date={date}" / "orderbook.csv"
        rows_by_path.setdefault(path, []).append(row)

    for path, path_rows in rows_by_path.items():
        _append_dataclass_csv(path, tuple(path_rows), OrderBookRow)


def _write_dataclass_csv(path: Path, rows: tuple[object, ...], row_type: type[object]) -> None:
    fieldnames = [field.name for field in fields(row_type)]
    with path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _append_dataclass_csv(path: Path, rows: tuple[object, ...], row_type: type[object]) -> None:
    if not rows:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists()
    fieldnames = [field.name for field in fields(row_type)]
    with path.open("a", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
