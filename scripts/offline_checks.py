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
from kalshi_capture.selector import market_passes_filters, score_orderbook_payload, select_liquid_tickers
from kalshi_capture.spread_depth import build_report, write_report
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
    check_spread_depth_report()
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
                    "yes_dollars": [["0.1500", "100.00"], ["0.1400", "25.00"]],
                    "no_dollars": [["0.8500", "50.00"]],
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
    assert scores["T2"].rows == 1
    assert scores["T2"].top_level_size == 1000


def check_liquid_selector_filters() -> None:
    class FakeClient:
        def get(self, path: str, params=None):
            assert path == "/series/SERIES"
            return {"series": {"category": "Sports"}}

    market = {
        "ticker": "T1",
        "event_ticker": "SERIES-TEST",
        "close_time": "2999-01-01T00:00:00Z",
        "volume": "125",
        "open_interest": "250",
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
                            "orderbook_fp": {"yes_dollars": [["0.4500", "10.00"]], "no_dollars": []},
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
                                "no_dollars": [],
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
                            "orderbook_fp": {"yes_dollars": [["0.4500", top_sizes[ticker]]], "no_dollars": []},
                        }
                        for ticker in tickers
                    ]
                }
            raise AssertionError(path)

    assert select_liquid_tickers(FakeClient(), 2, scan_pages=1) == ("LADDER-YES-1", "OTHER-YES")
    assert select_liquid_tickers(FakeClient(), 3, scan_pages=1) == ("LADDER-YES-1", "OTHER-YES")


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


if __name__ == "__main__":
    main()
