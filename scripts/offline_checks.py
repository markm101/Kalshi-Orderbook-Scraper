from __future__ import annotations

import csv
from dataclasses import replace
import tempfile
import sys
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kalshi_capture.capture import run_capture
from kalshi_capture.config import Config, read_env_file
from kalshi_capture.discovery import DiscoveryResult, MarketMetadata, SeriesMetadata
from kalshi_capture.gaps import GapLogger
from kalshi_capture.orderbook import extract_orderbook_tickers, flatten_orderbook_payload
from kalshi_capture.selector import market_passes_filters, score_orderbook_payload, select_liquid_tickers
from kalshi_capture.spread_depth import (
    LatestSnapshots,
    build_latest_report,
    build_report,
    write_latest_report,
    write_report,
)
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
    check_liquid_selector_scoring()
    check_liquid_selector_filters()
    check_liquid_selector_category_seed()
    check_liquid_selector_ranks_beyond_first_match()
    check_liquid_selector_diversifies_events()
    check_liquid_selector_uses_fp_fields_and_skips_one_sided()
    check_liquid_selector_keeps_existing_picks()
    check_spread_depth_report()
    check_latest_spread_report()
    check_latest_snapshots_keep_newest_book()
    check_capture_keeps_latest_spread_in_memory()
    check_capture_stops_polling_closed_markets()
    check_capture_keeps_picks_until_they_close()
    check_capture_stops_when_all_markets_close()
    print("offline checks passed")


def check_orderbook_flattening() -> None:
    payload = {
        "orderbooks": [
            {
                "ticker": "T1",
                "orderbook_fp": {
                    "yes_dollars": [["0.1300", "5.00"], ["0.1400", "25.00"], ["0.1500", "100.00"]],
                    "no_dollars": [["0.8400", "7.00"], ["0.8500", "50.00"]],
                },
            }
        ]
    }
    # Kalshi returns bid levels ascending by price, so the best bid is the last entry.
    rows = flatten_orderbook_payload(payload, 1782432000000)
    assert [(row.side, row.level, row.price, row.size) for row in rows] == [
        ("yes", 0, 1500, 10000),
        ("yes", 1, 1400, 2500),
        ("yes", 2, 1300, 500),
        ("no", 0, 8500, 5000),
        ("no", 1, 8400, 700),
    ]
    rows = flatten_orderbook_payload(payload, 1782432000000, max_levels=1)
    assert [(row.side, row.level, row.price, row.size) for row in rows] == [
        ("yes", 0, 1500, 10000),
        ("no", 0, 8500, 5000),
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
    orderbook_path = output_dir / "orderbooks" / "T1.csv"
    assert orderbook_path.exists()
    text = orderbook_path.read_text()
    assert "capture_ts_ms,ticker,side,level,price,size,snapshot_id" in text
    assert "1782432000000,T1,yes,0,1500,10000,1782432000000:T1" in text


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
    assert summary.total_size == 10000
    assert summary.total_top_level_size == 10000
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
    write_metadata(output_dir, discovery)
    payload = {
        "orderbooks": [
            {
                "ticker": "T1",
                "orderbook_fp": {"yes_dollars": [], "no_dollars": [["0.8500", "50.00"]]},
            }
        ]
    }
    raw_path = output_dir / "orderbooks" / "T1.csv"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        "capture_ts_ms,ticker,side,level,price,size,snapshot_id\n"
        "1782432000000,T1,no,0,8500,5000,1782432000000:T1\n"
    )
    assert derive_capture(output_dir, derived_dir) == 2
    derived_path = derived_dir / "orderbooks" / "T1.csv"
    text = derived_path.read_text()
    assert "yes,ask,0,1500,5000" in text
    assert (derived_dir / "metadata" / "markets.csv").exists()


def check_liquid_selector_scoring() -> None:
    payload = {
        "orderbooks": [
            {
                "ticker": "T1",
                "orderbook_fp": {
                    "yes_dollars": [["0.1400", "25.00"], ["0.1500", "100.00"]],
                    "no_dollars": [["0.8300", "50.00"]],
                },
            },
            {
                "ticker": "T2",
                "orderbook_fp": {
                    "yes_dollars": [["0.4500", "10.00"]],
                    "no_dollars": [],
                },
            },
        ]
    }
    scores = {candidate.ticker: candidate for candidate in score_orderbook_payload(payload)}
    assert scores["T1"].rows == 3
    assert scores["T1"].top_level_size == 15000
    assert scores["T1"].spread == 200
    assert scores["T2"].rows == 1
    assert scores["T2"].top_level_size == 1000
    assert scores["T2"].spread is None


def check_liquid_selector_filters() -> None:
    class FakeClient:
        def get(self, path: str, params=None):
            assert path == "/series/SERIES"
            return {"series": {"category": "Sports"}}

    market = {
        "ticker": "T1",
        "event_ticker": "SERIES-TEST",
        "close_time": "2999-01-01T00:00:00Z",
        "volume_fp": "125.00",
        "open_interest_fp": "250.00",
    }
    cache: dict[str, str] = {}
    assert market_passes_filters(
        FakeClient(),
        market,
        cache,
        include_categories=("Sports",),
        min_close_hours=1,
        min_volume=100,
        min_open_interest=200,
    )
    assert cache == {"SERIES": "Sports"}
    assert not market_passes_filters(FakeClient(), market, cache, include_categories=("Financials",))
    assert not market_passes_filters(FakeClient(), market, cache, exclude_categories=("Sports",))
    assert not market_passes_filters(FakeClient(), {**market, "close_time": "2000-01-01T00:00:00Z"}, cache, min_close_hours=1)
    assert not market_passes_filters(FakeClient(), market, cache, min_volume=500)
    assert not market_passes_filters(FakeClient(), market, cache, min_open_interest=500)


def check_liquid_selector_category_seed() -> None:
    class FakeClient:
        def get(self, path: str, params=None):
            if path == "/series":
                assert params["category"] == "Sports"
                return {"series": [{"ticker": "SERIES"}]}
            if path == "/markets":
                assert params["series_ticker"] == "SERIES"
                return {
                    "markets": [
                        {
                            "ticker": "T1",
                            "event_ticker": "SERIES-TEST",
                            "close_time": "2999-01-01T00:00:00Z",
                        }
                    ]
                }
            if path.startswith("/series/"):
                raise AssertionError(f"unexpected series lookup: {path}")
            if path == "/markets/orderbooks":
                return {
                    "orderbooks": [
                        {
                            "ticker": "T1",
                            "orderbook_fp": {"yes_dollars": [["0.4500", "10.00"]], "no_dollars": [["0.5000", "10.00"]]},
                        }
                    ]
                }
            raise AssertionError(path)

    assert select_liquid_tickers(FakeClient(), 1, include_categories=("Sports",)) == ("T1",)


def check_liquid_selector_ranks_beyond_first_match() -> None:
    class FakeClient:
        def get(self, path: str, params=None):
            if path == "/series":
                return {"series": [{"ticker": "SERIES1"}, {"ticker": "SERIES2"}]}
            if path == "/markets" and params["series_ticker"] == "SERIES1":
                return {
                    "markets": [
                        {
                            "ticker": "WEAK",
                            "series_ticker": "SERIES1",
                            "close_time": "2999-01-01T00:00:00Z",
                            "volume": "10",
                            "open_interest": "10",
                        }
                    ]
                }
            if path == "/markets" and params["series_ticker"] == "SERIES2":
                return {
                    "markets": [
                        {
                            "ticker": "STRONG",
                            "series_ticker": "SERIES2",
                            "close_time": "2999-01-02T00:00:00Z",
                            "volume": "1000",
                            "open_interest": "1000",
                        }
                    ]
                }
            if path == "/markets/orderbooks":
                tickers = tuple(value for key, value in params if key == "tickers")
                return {
                    "orderbooks": [
                        {
                            "ticker": ticker,
                            "orderbook_fp": {
                                "yes_dollars": [["0.4500", "10.00" if ticker == "WEAK" else "100.00"]],
                                "no_dollars": [["0.5000", "10.00"]],
                            },
                        }
                        for ticker in tickers
                    ]
                }
            raise AssertionError(path)

    assert select_liquid_tickers(FakeClient(), 1, scan_pages=1, include_categories=("Sports",)) == ("STRONG",)


def check_liquid_selector_diversifies_events() -> None:
    class FakeClient:
        def get(self, path: str, params=None):
            if path == "/markets":
                return {
                    "markets": [
                        {
                            "ticker": "LADDER-YES-1",
                            "event_ticker": "LADDER",
                            "close_time": "2999-01-01T00:00:00Z",
                            "volume": "1000",
                        },
                        {
                            "ticker": "LADDER-YES-2",
                            "event_ticker": "LADDER",
                            "close_time": "2999-01-01T00:00:00Z",
                            "volume": "900",
                        },
                        {
                            "ticker": "OTHER-YES",
                            "event_ticker": "OTHER",
                            "close_time": "2999-01-01T00:00:00Z",
                            "volume": "100",
                        },
                    ]
                }
            if path == "/markets/orderbooks":
                top_sizes = {"LADDER-YES-1": "100.00", "LADDER-YES-2": "90.00", "OTHER-YES": "10.00"}
                tickers = tuple(value for key, value in params if key == "tickers")
                return {
                    "orderbooks": [
                        {
                            "ticker": ticker,
                            "orderbook_fp": {
                                "yes_dollars": [["0.4500", top_sizes[ticker]]],
                                "no_dollars": [["0.5000", "10.00"]],
                            },
                        }
                        for ticker in tickers
                    ]
                }
            raise AssertionError(path)

    assert select_liquid_tickers(FakeClient(), 2, scan_pages=1) == ("LADDER-YES-1", "OTHER-YES")
    assert select_liquid_tickers(FakeClient(), 3, scan_pages=1) == ("LADDER-YES-1", "OTHER-YES")


def check_liquid_selector_uses_fp_fields_and_skips_one_sided() -> None:
    class FakeClient:
        def get(self, path: str, params=None):
            if path == "/markets":
                # Multivariate combo markets flood the open-market scan and are never two-sided.
                assert params["mve_filter"] == "exclude"
                return {
                    "markets": [
                        {"ticker": "DEAD", "event_ticker": "E1", "volume_fp": "900000.00", "volume_24h_fp": "900000.00"},
                        {"ticker": "QUIET", "event_ticker": "E2", "volume_fp": "5000.00", "volume_24h_fp": "10.00"},
                        {"ticker": "ACTIVE", "event_ticker": "E3", "volume_fp": "4000.00", "volume_24h_fp": "2500.00"},
                    ]
                }
            if path == "/markets/orderbooks":
                books = {
                    # No YES bids at all and a 99c NO bid: not a two-sided market.
                    "DEAD": {"yes_dollars": [], "no_dollars": [["0.0100", "46010.00"], ["0.9900", "414.06"]]},
                    "QUIET": {"yes_dollars": [["0.4000", "10.00"]], "no_dollars": [["0.5500", "10.00"]]},
                    "ACTIVE": {"yes_dollars": [["0.4000", "10.00"]], "no_dollars": [["0.5500", "10.00"]]},
                }
                tickers = tuple(value for key, value in params if key == "tickers")
                return {"orderbooks": [{"ticker": ticker, "orderbook_fp": books[ticker]} for ticker in tickers]}
            raise AssertionError(path)

    assert select_liquid_tickers(FakeClient(), 3, scan_pages=1) == ("ACTIVE", "QUIET")
    assert select_liquid_tickers(FakeClient(), 3, scan_pages=1, min_volume=4500) == ("QUIET",)


def check_liquid_selector_keeps_existing_picks() -> None:
    class FakeClient:
        def get(self, path: str, params=None):
            if path == "/markets":
                return {
                    "markets": [
                        {"ticker": "A", "event_ticker": "EA", "volume_24h_fp": "300.00"},
                        {"ticker": "A2", "event_ticker": "EA", "volume_24h_fp": "250.00"},
                        {"ticker": "B", "event_ticker": "EB", "volume_24h_fp": "200.00"},
                        {"ticker": "C", "event_ticker": "EC", "volume_24h_fp": "100.00"},
                    ]
                }
            if path == "/markets/orderbooks":
                tickers = tuple(value for key, value in params if key == "tickers")
                book = {"yes_dollars": [["0.4000", "10.00"]], "no_dollars": [["0.5500", "10.00"]]}
                return {"orderbooks": [{"ticker": ticker, "orderbook_fp": book} for ticker in tickers]}
            raise AssertionError(path)

    assert select_liquid_tickers(FakeClient(), 2, scan_pages=1) == ("A", "B")
    # Kept picks come first and only the free slots are filled.
    assert select_liquid_tickers(FakeClient(), 2, scan_pages=1, keep=("C",)) == ("C", "A")
    # A new pick never shares an event with a kept pick.
    assert select_liquid_tickers(FakeClient(), 2, scan_pages=1, keep=("A",)) == ("A", "B")


def check_spread_depth_report() -> None:
    output_dir = Path(tempfile.mkdtemp())
    metadata_dir = output_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "markets.csv").write_text(
        "ticker,event_ticker,series_ticker,market_type,status,title,yes_sub_title,no_sub_title,open_time,close_time,updated_time\n"
        "T1,SERIES-TEST,SERIES,binary,active,,,,'','',''\n"
    )
    (metadata_dir / "series.csv").write_text(
        "series_ticker,category,sanitized_category,tags,title,frequency,updated_at\n"
        "SERIES,Sports,Sports,,Series,daily,\n"
    )
    output_path = output_dir / "orderbooks" / "T1.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "capture_ts_ms,snapshot_id,ticker,outcome,book_side,level,price,size\n"
        "1782432000000,1782432000000:T1,T1,yes,bid,0,4000,100\n"
        "1782432000000,1782432000000:T1,T1,yes,bid,1,3900,50\n"
        "1782432000000,1782432000000:T1,T1,yes,ask,0,4500,25\n"
        "1782432000000,1782432000000:T1,T1,yes,ask,1,4600,75\n"
        "1782432000000,1782432000000:T1,T1,no,bid,0,5500,25\n"
        "1782432000000,1782432000000:T1,T1,no,ask,0,6000,100\n"
    )

    rows = build_report(output_dir, outcomes=("yes",))
    assert len(rows) == 1
    row = rows[0]
    assert row.category == "Sports"
    assert row.ticker == "T1"
    assert row.outcome == "yes"
    assert row.snapshots == 1
    assert row.spread_snapshots == 1
    assert row.min_spread == 500
    assert row.avg_spread == "500.00"
    assert row.max_spread == 500
    assert row.avg_best_bid == "4000.00"
    assert row.avg_best_ask == "4500.00"
    assert row.avg_top_bid_size == "100.00"
    assert row.avg_top_ask_size == "25.00"
    assert row.avg_total_bid_size == "150.00"
    assert row.avg_total_ask_size == "100.00"

    raw_output_dir = Path(tempfile.mkdtemp())
    raw_metadata_dir = raw_output_dir / "metadata"
    raw_metadata_dir.mkdir(parents=True, exist_ok=True)
    (raw_metadata_dir / "markets.csv").write_text(
        "ticker,event_ticker,series_ticker,market_type,status,title,yes_sub_title,no_sub_title,open_time,close_time,updated_time\n"
        "T1,SERIES-TEST,SERIES,binary,active,,,,'','',''\n"
    )
    (raw_metadata_dir / "series.csv").write_text(
        "series_ticker,category,sanitized_category,tags,title,frequency,updated_at\n"
        "SERIES,Sports,Sports,,Series,daily,\n"
    )
    raw_path = raw_output_dir / "orderbooks" / "T1.csv"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(
        "capture_ts_ms,ticker,side,level,price,size,snapshot_id\n"
        "1782432000000,T1,yes,0,4000,100,1782432000000:T1\n"
        "1782432000000,T1,no,0,5500,25,1782432000000:T1\n"
    )
    raw_rows = build_report(raw_output_dir, outcomes=("yes",))
    assert len(raw_rows) == 1
    assert raw_rows[0].min_spread == 500
    assert raw_rows[0].avg_top_bid_size == "100.00"
    assert raw_rows[0].avg_top_ask_size == "25.00"

    report_path = output_dir / "spread_depth.csv"
    write_report(rows, report_path)
    assert "avg_spread" in report_path.read_text()


def check_latest_spread_report() -> None:
    output_dir = Path(tempfile.mkdtemp())
    metadata_dir = output_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "markets.csv").write_text(
        "ticker,event_ticker,series_ticker,market_type,status,title,yes_sub_title,no_sub_title,open_time,close_time,updated_time\n"
        "T1,SERIES-TEST,SERIES,binary,active,,,,'','',''\n"
        "T2,SERIES-TEST,SERIES,binary,active,,,,'','',''\n"
    )
    (metadata_dir / "series.csv").write_text(
        "series_ticker,category,sanitized_category,tags,title,frequency,updated_at\n"
        "SERIES,Sports,Sports,,Series,daily,\n"
    )
    orderbook_dir = output_dir / "orderbooks"
    orderbook_dir.mkdir(parents=True, exist_ok=True)
    (orderbook_dir / "T1.csv").write_text(
        "capture_ts_ms,ticker,side,level,price,size,snapshot_id\n"
        "1782432000000,T1,yes,0,4000,100,1782432000000:T1\n"
        "1782432000000,T1,no,0,5500,25,1782432000000:T1\n"
        "1782432001000,T1,yes,0,4100,200,1782432001000:T1\n"
        "1782432001000,T1,no,0,5600,75,1782432001000:T1\n"
    )
    (orderbook_dir / "T2.csv").write_text(
        "capture_ts_ms,ticker,side,level,price,size,snapshot_id\n"
        "1782432000000,T2,no,0,8000,100,1782432000000:T2\n"
    )

    rows = build_latest_report(output_dir)
    by_ticker = {row.ticker: row for row in rows}
    assert by_ticker["T1"].book_state == "spread_available"
    assert by_ticker["T1"].capture_ts_ms == 1782432001000
    assert by_ticker["T1"].yes_best_bid == 4100
    assert by_ticker["T1"].yes_best_ask == 4400
    assert by_ticker["T1"].yes_spread == 300
    assert by_ticker["T1"].no_best_bid == 5600
    assert by_ticker["T1"].no_best_ask == 5900
    assert by_ticker["T1"].no_spread == 300
    assert by_ticker["T2"].book_state == "one_sided"
    assert by_ticker["T2"].yes_spread is None

    report_path = output_dir / "latest_spread.csv"
    write_latest_report(rows, report_path)
    assert "book_state" in report_path.read_text()


def check_latest_snapshots_keep_newest_book() -> None:
    def raw_row(ticker: str, ts: int, side: str, price: int, size: int) -> dict[str, str]:
        return {
            "capture_ts_ms": str(ts),
            "ticker": ticker,
            "side": side,
            "level": "0",
            "price": str(price),
            "size": str(size),
            "snapshot_id": f"{ts}:{ticker}",
        }

    snapshots = LatestSnapshots()
    snapshots.update(
        [
            raw_row("T1", 1000, "yes", 4000, 1000),
            raw_row("T1", 1000, "no", 5500, 2000),
            raw_row("T2", 1000, "yes", 2000, 500),
        ]
    )
    # Newer T1 book with no NO bids: it replaces the old book rather than merging with it.
    snapshots.update([raw_row("T1", 2000, "yes", 4200, 3000)])
    # An older T1 book arriving late is ignored.
    snapshots.update([raw_row("T1", 1500, "no", 5000, 100)])

    report = {row.ticker: row for row in build_latest_report(Path(tempfile.mkdtemp()), snapshots=snapshots)}
    assert (report["T1"].capture_ts_ms, report["T1"].yes_best_bid, report["T1"].no_best_bid) == (2000, 4200, None)
    assert report["T1"].book_state == "one_sided"
    assert (report["T2"].capture_ts_ms, report["T2"].yes_best_bid) == (1000, 2000)


def check_capture_keeps_latest_spread_in_memory() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.polls = 0

        def get(self, path: str, params=None):
            if path == "/markets":
                return {"markets": [{"ticker": "T1", "event_ticker": "SERIES-TEST", "series_ticker": "SERIES"}]}
            if path == "/series/SERIES":
                return {"series": {"ticker": "SERIES", "category": "Sports"}}
            if path == "/markets/orderbooks":
                self.polls += 1
                yes_price = f"0.{40 + self.polls}00"
                return {
                    "orderbooks": [
                        {
                            "ticker": "T1",
                            "orderbook_fp": {"yes_dollars": [[yes_price, "10.00"]], "no_dollars": [["0.5000", "10.00"]]},
                        }
                    ]
                }
            raise AssertionError(path)

    output_dir = Path(tempfile.mkdtemp())
    # A market captured by an earlier run into the same directory. Each poll must not re-read old CSVs.
    (output_dir / "orderbooks").mkdir(parents=True)
    (output_dir / "orderbooks" / "OLD.csv").write_text(
        "capture_ts_ms,ticker,side,level,price,size,snapshot_id\n"
        "1782432000000,OLD,yes,0,3000,100,1782432000000:OLD\n"
    )
    client = FakeClient()
    run_capture(_capture_config(output_dir, tickers=("T1",)), client, stop_requested=lambda: client.polls >= 3)

    assert len((output_dir / "orderbooks" / "T1.csv").read_text().splitlines()) == 1 + 3 * 2
    with (output_dir / "latest_spread.csv").open(newline="") as csv_file:
        latest = [(row["ticker"], row["yes_best_bid"], row["yes_best_ask"]) for row in csv.DictReader(csv_file)]
    assert latest == [("T1", "4300", "5000")], latest


def check_capture_stops_polling_closed_markets() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.polls = 0

        def market(self, ticker: str) -> dict:
            market = {"ticker": ticker, "event_ticker": f"SERIES-{ticker}", "series_ticker": "SERIES", "status": "active", "result": ""}
            if ticker == "T2" and self.polls >= 2:
                market.update(
                    status="finalized",
                    result="yes",
                    close_time="2026-09-26T05:50:01Z",
                    settlement_ts="2026-09-26T05:54:06Z",
                    settlement_value_dollars="1.0000",
                )
            return market

        def get(self, path: str, params=None):
            if path == "/markets":
                return {"markets": [self.market(ticker) for ticker in params["tickers"].split(",")]}
            if path == "/series/SERIES":
                return {"series": {"ticker": "SERIES", "category": "Sports"}}
            if path == "/markets/orderbooks":
                self.polls += 1
                return _two_sided_books(tuple(value for key, value in params if key == "tickers"))
            raise AssertionError(path)

    output_dir = Path(tempfile.mkdtemp())
    client = FakeClient()
    config = _capture_config(output_dir, tickers=("T1", "T2"), discovery_refresh_seconds=0, status_check_seconds=0.0)
    run_capture(config, client, stop_requested=lambda: client.polls >= 4)

    # T2 settles after two polls: it is not polled again, even though --tickers still lists it.
    assert _snapshot_count(output_dir, "T1") == 4
    assert _snapshot_count(output_dir, "T2") == 2
    results = _read_csv(output_dir / "metadata" / "results.csv")
    assert [(row["ticker"], row["status"], row["result"], row["settlement_value"], row["close_time"]) for row in results] == [
        ("T2", "finalized", "yes", "10000", "2026-09-26T05:50:01Z")
    ]
    closed = [row for row in _read_csv(output_dir / "gaps.csv") if row["event_type"] == "market_closed"]
    assert [row["ticker"] for row in closed] == ["T2"]


def check_capture_keeps_picks_until_they_close() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.scans = 0
            self.orderbook_calls = 0

        def market(self, ticker: str) -> dict:
            market = {"ticker": ticker, "event_ticker": f"E{ticker}", "series_ticker": "SERIES", "status": "active", "result": ""}
            if ticker == "B" and self.orderbook_calls >= 3:
                market.update(status="finalized", result="no", settlement_value_dollars="0.0000")
            return market

        def get(self, path: str, params=None):
            if path == "/markets" and "tickers" in params:
                return {"markets": [self.market(ticker) for ticker in params["tickers"].split(",")]}
            if path == "/markets":
                self.scans += 1
                # After the first pick, C becomes the busiest market. It must not push out B while B is open.
                volumes = {"A": 300, "B": 200, "C": 100} if self.scans == 1 else {"A": 300, "B": 200, "C": 1000}
                markets = [dict(self.market(ticker), volume_24h_fp=f"{volume}.00") for ticker, volume in volumes.items()]
                return {"markets": [market for market in markets if market["status"] == "active"]}
            if path == "/series/SERIES":
                return {"series": {"ticker": "SERIES", "category": "Sports"}}
            if path == "/markets/orderbooks":
                self.orderbook_calls += 1
                return _two_sided_books(tuple(value for key, value in params if key == "tickers"))
            raise AssertionError(path)

    output_dir = Path(tempfile.mkdtemp())
    client = FakeClient()
    config = _capture_config(output_dir, tickers=(), select_liquid=2, discovery_refresh_seconds=0, status_check_seconds=0.0)
    run_capture(config, client, stop_requested=lambda: client.orderbook_calls >= 7)

    snapshots = {ticker: _snapshot_times(output_dir, ticker) for ticker in ("A", "B", "C")}
    all_polls = set().union(*snapshots.values())
    assert snapshots["A"] == all_polls
    assert snapshots["B"] and snapshots["C"]
    # C only fills B's slot after B closes.
    assert max(snapshots["B"]) < min(snapshots["C"])
    assert [row["ticker"] for row in _read_csv(output_dir / "metadata" / "results.csv")] == ["B"]
    # Metadata keeps every market captured in the run, including the closed one.
    assert sorted(row["ticker"] for row in _read_csv(output_dir / "metadata" / "markets.csv")) == ["A", "B", "C"]


def check_capture_stops_when_all_markets_close() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.polls = 0

        def get(self, path: str, params=None):
            if path == "/markets":
                closed = self.polls >= 2
                return {
                    "markets": [
                        {
                            "ticker": ticker,
                            "event_ticker": f"SERIES-{ticker}",
                            "series_ticker": "SERIES",
                            "status": "finalized" if closed else "active",
                            "result": "no" if closed else "",
                        }
                        for ticker in params["tickers"].split(",")
                    ]
                }
            if path == "/series/SERIES":
                return {"series": {"ticker": "SERIES", "category": "Sports"}}
            if path == "/markets/orderbooks":
                self.polls += 1
                return _two_sided_books(tuple(value for key, value in params if key == "tickers"))
            raise AssertionError(path)

    output_dir = Path(tempfile.mkdtemp())
    client = FakeClient()
    # With only --tickers, nothing can replace settled markets, so the run should end on its own.
    # duration_seconds is only a safety net in case it doesn't.
    config = _capture_config(output_dir, tickers=("T1", "T2"), status_check_seconds=0.0, duration_seconds=2.0)
    run_capture(config, client)

    events = [row["event_type"] for row in _read_csv(output_dir / "gaps.csv")]
    assert events.count("all_markets_closed") == 1, events
    assert "empty_ticker_set" not in events
    assert json.loads((output_dir / "run_summary.json").read_text())["errors"] == 0
    assert client.polls == 2
    assert sorted(row["ticker"] for row in _read_csv(output_dir / "metadata" / "results.csv")) == ["T1", "T2"]


def _capture_config(output_dir: Path, **changes) -> Config:
    config = Config(
        env="demo",
        base_url="",
        key_id="",
        private_key_path=Path("unused.key"),
        tickers=(),
        select_liquid=0,
        liquid_scan_pages=1,
        min_orderbook_rows=1,
        min_top_level_size=0,
        selector_categories=(),
        selector_exclude_categories=(),
        min_close_hours=0.0,
        min_volume=0,
        min_open_interest=0,
        series=(),
        categories=(),
        exclude_categories=(),
        interval=0.01,
        output_dir=output_dir,
        max_levels=0,
        dry_run=False,
        discover_only=False,
        once=False,
        duration_seconds=0.0,
        heartbeat_seconds=300,
        discovery_refresh_seconds=900,
        log_level="WARNING",
    )
    return replace(config, **changes)


def _two_sided_books(tickers: tuple[str, ...]) -> dict:
    book = {"yes_dollars": [["0.4000", "10.00"]], "no_dollars": [["0.5500", "10.00"]]}
    return {"orderbooks": [{"ticker": ticker, "orderbook_fp": book} for ticker in tickers]}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _snapshot_times(output_dir: Path, ticker: str) -> set[int]:
    return {int(row["capture_ts_ms"]) for row in _read_csv(output_dir / "orderbooks" / f"{ticker}.csv")}


def _snapshot_count(output_dir: Path, ticker: str) -> int:
    return len(_snapshot_times(output_dir, ticker))


if __name__ == "__main__":
    main()
