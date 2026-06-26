from __future__ import annotations

import csv
import time
from pathlib import Path


GAP_COLUMNS = ("ts_ms", "ticker", "event_type", "detail")


class GapLogger:
    def __init__(self, output_dir: Path) -> None:
        self.path = output_dir / "gaps.csv"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event_type: str, detail: str, ticker: str = "*") -> None:
        file_exists = self.path.exists()
        with self.path.open("a", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=GAP_COLUMNS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(
                {
                    "ts_ms": int(time.time() * 1000),
                    "ticker": ticker,
                    "event_type": event_type,
                    "detail": detail,
                }
            )
