from __future__ import annotations

import tempfile
import sys
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kalshi_capture.config import read_env_file
from kalshi_capture.discovery import DiscoveryResult, MarketMetadata, SeriesMetadata
from kalshi_capture.gaps import GapLogger
from kalshi_capture.orderbook import extract_orderbook_tickers, flatten_orderbook_payload
from kalshi_capture.storage import write_metadata, write_orderbook_rows
from scripts.derive_bid_ask import derive_capture, derive_rows
from scripts.inspect_capture import inspect_capture


def main() -> None:
    check_orderbook_flattening()
    check_storage_writes()
    check_gap_logger()
    check_env_file_parser()
    check_capture_inspector()
    check_derived_bid_ask()
    print("offline checks passed")


def check_orderbook_flattening() -> None:
    payload = {
        "orderbooks": [
            {
                "ticker": "T1",
                "orderbook_fp": {
                    "yes_dollars": [["0.1500", "100.00"], ["0.1400", "25.00"]],
                    "no_dollars": [["0.8500", "50.00"]],
                },
            }
        ]
    }
    rows = flatten_orderbook_payload(payload, 1782432000000, max_levels=1)
    assert [(row.side, row.level, row.price, row.size) for row in rows] == [
        ("yes", 0, 1500, 100),
        ("no", 0, 8500, 50),
    ]
    assert rows[0].snapshot_id == "1782432000000:T1"
    assert extract_orderbook_tickers(payload) == ("T1",)


def check_storage_writes() -> None:
    output_dir = Path(tempfile.mkdtemp())
    market = MarketMetadata(
        ticker="T1",
        event_ticker="SERIES-TEST",
        series_ticker="SERIES",
        market_type="binary",
        status="active",
        title="",
        yes_sub_title="Yes",
        no_sub_title="No",
        open_time="",
        close_time="",
        updated_time="",
    )
    series = SeriesMetadata(
        series_ticker="SERIES",
        category="Sports",
        sanitized_category="Sports",
        tags="",
        title="Series",
        frequency="daily",
        updated_at="",
    )
    discovery = DiscoveryResult(markets=(market,), series=(series,))
    write_metadata(output_dir, discovery)

    payload = {
        "orderbooks": [
            {
                "ticker": "T1",
                "orderbook_fp": {"yes_dollars": [["0.1500", "100.00"]], "no_dollars": []},
            }
        ]
    }
    rows = flatten_orderbook_payload(payload, 1782432000000)
    write_orderbook_rows(output_dir, rows, discovery.ticker_categories)

    assert (output_dir / "metadata" / "markets.csv").exists()
    assert (output_dir / "metadata" / "series.csv").exists()
    orderbook_path = output_dir / "orderbooks" / "category=Sports" / "date=2026-06-26" / "orderbook.csv"
    assert orderbook_path.exists()
    assert "T1,yes,0,1500,100,1782432000000:T1" in orderbook_path.read_text()


def check_gap_logger() -> None:
    output_dir = Path(tempfile.mkdtemp())
    gap_logger = GapLogger(output_dir)
    gap_logger.log("startup", "test")
    gap_logger.log("missing_orderbook", "test", ticker="T1")
    text = (output_dir / "gaps.csv").read_text()
    assert "ts_ms,ticker,event_type,detail" in text
    assert "missing_orderbook" in text


def check_env_file_parser() -> None:
    temp_dir = Path(tempfile.mkdtemp())
    env_path = temp_dir / ".env"
    env_path.write_text(
        "# comment\n"
        "KALSHI_KEY_ID='example-key-id'\n"
        'KALSHI_PRIVATE_KEY_PATH="/tmp/key.txt"\n'
    )
    values = read_env_file(env_path)
    assert values["KALSHI_KEY_ID"] == "example-key-id"
    assert values["KALSHI_PRIVATE_KEY_PATH"] == "/tmp/key.txt"


def check_capture_inspector() -> None:
    output_dir = Path(tempfile.mkdtemp())
    market = MarketMetadata(
        ticker="T1",
        event_ticker="SERIES-TEST",
        series_ticker="SERIES",
        market_type="binary",
        status="active",
        title="",
        yes_sub_title="Yes",
        no_sub_title="No",
        open_time="",
        close_time="",
        updated_time="",
    )
    series = SeriesMetadata(
        series_ticker="SERIES",
        category="Sports",
        sanitized_category="Sports",
        tags="",
        title="Series",
        frequency="daily",
        updated_at="",
    )
    discovery = DiscoveryResult(markets=(market,), series=(series,))
    payload = {
        "orderbooks": [
            {
                "ticker": "T1",
                "orderbook_fp": {"yes_dollars": [["0.1500", "100.00"]], "no_dollars": []},
            }
        ]
    }
    rows = flatten_orderbook_payload(payload, 1782432000000)
    write_orderbook_rows(output_dir, rows, discovery.ticker_categories)
    gap_logger = GapLogger(output_dir)
    gap_logger.log("startup", "test")
    (output_dir / "run_summary.json").write_text(json.dumps({"rows": 1, "zero_row_batches": 0}) + "\n")

    summary = inspect_capture(output_dir)
    assert summary.orderbook_files == 1
    assert summary.orderbook_rows == 1
    assert summary.tickers == {"T1"}
    assert summary.categories == {"Sports"}
    assert summary.dates == {"2026-06-26"}
    assert len(summary.snapshots) == 1
    assert summary.total_size == 100
    assert summary.total_top_level_size == 100
    assert summary.run_summary["rows"] == 1
    assert summary.run_summary["zero_row_batches"] == 0
    assert summary.gap_events["startup"] == 1


def check_derived_bid_ask() -> None:
    raw_row = {
        "capture_ts_ms": "1782432000000",
        "ticker": "T1",
        "side": "no",
        "level": "0",
        "price": "8500",
        "size": "50",
        "snapshot_id": "1782432000000:T1",
    }
    derived = derive_rows(raw_row)
    assert [(row.outcome, row.book_side, row.level, row.price, row.size) for row in derived] == [
        ("no", "bid", 0, 8500, 50),
        ("yes", "ask", 0, 1500, 50),
    ]

    output_dir = Path(tempfile.mkdtemp())
    derived_dir = Path(tempfile.mkdtemp())
    market = MarketMetadata(
        ticker="T1",
        event_ticker="SERIES-TEST",
        series_ticker="SERIES",
        market_type="binary",
        status="active",
        title="",
        yes_sub_title="Yes",
        no_sub_title="No",
        open_time="",
        close_time="",
        updated_time="",
    )
    series = SeriesMetadata(
        series_ticker="SERIES",
        category="Sports",
        sanitized_category="Sports",
        tags="",
        title="Series",
        frequency="daily",
        updated_at="",
    )
    discovery = DiscoveryResult(markets=(market,), series=(series,))
    payload = {
        "orderbooks": [
            {
                "ticker": "T1",
                "orderbook_fp": {"yes_dollars": [], "no_dollars": [["0.8500", "50.00"]]},
            }
        ]
    }
    write_orderbook_rows(output_dir, flatten_orderbook_payload(payload, 1782432000000), discovery.ticker_categories)
    assert derive_capture(output_dir, derived_dir) == 2
    derived_path = derived_dir / "orderbooks" / "category=Sports" / "date=2026-06-26" / "orderbook.csv"
    text = derived_path.read_text()
    assert "yes,ask,0,1500,50" in text


if __name__ == "__main__":
    main()
