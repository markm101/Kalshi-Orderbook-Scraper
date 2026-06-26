from __future__ import annotations

import csv
from dataclasses import asdict, fields
from pathlib import Path

from kalshi_capture.discovery import DiscoveryResult, MarketMetadata, SeriesMetadata


def write_metadata(output_dir: Path, discovery: DiscoveryResult) -> None:
    metadata_dir = output_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    _write_dataclass_csv(metadata_dir / "markets.csv", discovery.markets, MarketMetadata)
    _write_dataclass_csv(metadata_dir / "series.csv", discovery.series, SeriesMetadata)


def _write_dataclass_csv(path: Path, rows: tuple[object, ...], row_type: type[object]) -> None:
    fieldnames = [field.name for field in fields(row_type)]
    with path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))
