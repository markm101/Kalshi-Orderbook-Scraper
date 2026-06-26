from __future__ import annotations

import logging
import time

import httpx

from kalshi_capture.client import KalshiClient
from kalshi_capture.config import Config
from kalshi_capture.discovery import DiscoveryResult, discover_markets
from kalshi_capture.gaps import GapLogger
from kalshi_capture.orderbook import fetch_orderbooks
from kalshi_capture.storage import write_metadata, write_orderbook_rows


def run_capture(config: Config, client: KalshiClient) -> None:
    gap_logger = GapLogger(config.output_dir)
    gap_logger.log("startup", "capture started")

    try:
        discovery = _discover(config, client, gap_logger)
        if not discovery.markets:
            gap_logger.log("empty_ticker_set", "no markets matched discovery filters")
            logging.warning("no markets matched discovery filters")
            return

        write_metadata(config.output_dir, discovery)

        if config.once:
            _capture_cycle(config, client, discovery, gap_logger)
            return

        next_discovery_refresh = time.monotonic() + config.discovery_refresh_seconds
        while True:
            cycle_start = time.monotonic()
            if time.monotonic() >= next_discovery_refresh:
                discovery = _discover(config, client, gap_logger)
                write_metadata(config.output_dir, discovery)
                next_discovery_refresh = time.monotonic() + config.discovery_refresh_seconds
            _capture_cycle(config, client, discovery, gap_logger)
            elapsed = time.monotonic() - cycle_start
            time.sleep(max(0.0, config.interval - elapsed))
    finally:
        gap_logger.log("shutdown", "capture stopped")


def _discover(config: Config, client: KalshiClient, gap_logger: GapLogger) -> DiscoveryResult:
    try:
        return discover_markets(
            client,
            tickers=config.tickers,
            series=config.series,
            categories=config.categories,
            exclude_categories=config.exclude_categories,
        )
    except Exception as exc:
        gap_logger.log("discovery_error", str(exc))
        raise


def _capture_cycle(
    config: Config,
    client: KalshiClient,
    discovery: DiscoveryResult,
    gap_logger: GapLogger,
) -> None:
    tickers = tuple(market.ticker for market in discovery.markets if market.ticker)
    categories = discovery.ticker_categories
    capture_ts_ms = int(time.time() * 1000)

    if not tickers:
        gap_logger.log("empty_ticker_set", "no tickers available for capture")
        return

    for i in range(0, len(tickers), 100):
        chunk = tickers[i : i + 100]
        try:
            rows = fetch_orderbooks(client, chunk, capture_ts_ms, max_levels=config.max_levels)
            write_orderbook_rows(config.output_dir, rows, categories)
            logging.info("captured tickers=%s rows=%s", len(chunk), len(rows))
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            event_type = "rate_limited" if status_code == 429 else "http_error"
            gap_logger.log(event_type, f"status={status_code} tickers={','.join(chunk)}")
            logging.warning("orderbook fetch failed status=%s tickers=%s", status_code, chunk)
        except ValueError as exc:
            gap_logger.log("parse_error", f"tickers={','.join(chunk)} error={exc}")
            logging.exception("orderbook parse failed tickers=%s", chunk)
        except Exception as exc:
            gap_logger.log("exception", f"tickers={','.join(chunk)} error={exc}")
            logging.exception("orderbook capture failed tickers=%s", chunk)
