from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from kalshi_capture.client import KalshiClient
from kalshi_capture.config import Config
from kalshi_capture.discovery import DiscoveryResult, discover_markets
from kalshi_capture.gaps import GapLogger
from kalshi_capture.orderbook import fetch_orderbook_batch
from kalshi_capture.storage import write_metadata, write_orderbook_rows


@dataclass
class CaptureStats:
    cycles: int = 0
    batches: int = 0
    rows: int = 0
    errors: int = 0
    missing_tickers: int = 0


def run_capture(
    config: Config,
    client: KalshiClient,
    stop_requested: Callable[[], bool] | None = None,
) -> None:
    should_stop = stop_requested or (lambda: False)
    gap_logger = GapLogger(config.output_dir)
    stats = CaptureStats()
    gap_logger.log("startup", "capture started")

    try:
        discovery = _discover(config, client, gap_logger)
        if not discovery.markets:
            gap_logger.log("empty_ticker_set", "no markets matched discovery filters")
            logging.warning("no markets matched discovery filters")
            return

        write_metadata(config.output_dir, discovery)

        if config.once:
            _capture_cycle(config, client, discovery, gap_logger, stats)
            return

        next_discovery_refresh = time.monotonic() + config.discovery_refresh_seconds
        next_heartbeat = time.monotonic() + config.heartbeat_seconds
        stop_at = time.monotonic() + config.duration_seconds if config.duration_seconds > 0 else None
        while not should_stop() and not _duration_elapsed(stop_at):
            cycle_start = time.monotonic()
            if time.monotonic() >= next_discovery_refresh:
                discovery = _discover(config, client, gap_logger)
                write_metadata(config.output_dir, discovery)
                next_discovery_refresh = time.monotonic() + config.discovery_refresh_seconds

            _capture_cycle(config, client, discovery, gap_logger, stats)

            if time.monotonic() >= next_heartbeat:
                _log_heartbeat(discovery, stats)
                next_heartbeat = time.monotonic() + config.heartbeat_seconds

            elapsed = time.monotonic() - cycle_start
            _sleep_interruptibly(max(0.0, config.interval - elapsed), should_stop, stop_at)
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
    stats: CaptureStats,
) -> None:
    tickers = tuple(market.ticker for market in discovery.markets if market.ticker)
    categories = discovery.ticker_categories
    capture_ts_ms = int(time.time() * 1000)

    if not tickers:
        gap_logger.log("empty_ticker_set", "no tickers available for capture")
        stats.errors += 1
        return

    stats.cycles += 1
    for i in range(0, len(tickers), 100):
        chunk = tickers[i : i + 100]
        try:
            batch = fetch_orderbook_batch(client, chunk, capture_ts_ms, max_levels=config.max_levels)
            _log_missing_tickers(chunk, batch.returned_tickers, gap_logger, stats)
            write_orderbook_rows(config.output_dir, batch.rows, categories)
            stats.batches += 1
            stats.rows += len(batch.rows)
            logging.info("captured tickers=%s rows=%s", len(chunk), len(batch.rows))
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            event_type = "rate_limited" if status_code == 429 else "http_error"
            gap_logger.log(event_type, f"status={status_code} tickers={','.join(chunk)}")
            stats.errors += 1
            logging.warning("orderbook fetch failed status=%s tickers=%s", status_code, chunk)
        except ValueError as exc:
            gap_logger.log("parse_error", f"tickers={','.join(chunk)} error={exc}")
            stats.errors += 1
            logging.exception("orderbook parse failed tickers=%s", chunk)
        except Exception as exc:
            gap_logger.log("exception", f"tickers={','.join(chunk)} error={exc}")
            stats.errors += 1
            logging.exception("orderbook capture failed tickers=%s", chunk)


def _log_missing_tickers(
    requested: tuple[str, ...],
    returned: tuple[str, ...],
    gap_logger: GapLogger,
    stats: CaptureStats,
) -> None:
    missing = sorted(set(requested) - set(returned))
    for ticker in missing:
        gap_logger.log("missing_orderbook", "ticker absent from successful batch response", ticker=ticker)
    stats.missing_tickers += len(missing)


def _log_heartbeat(discovery: DiscoveryResult, stats: CaptureStats) -> None:
    categories = {item.sanitized_category for item in discovery.series}
    logging.info(
        "heartbeat tracked_tickers=%s categories=%s cycles=%s batches=%s rows=%s errors=%s missing_tickers=%s",
        len(discovery.markets),
        len(categories),
        stats.cycles,
        stats.batches,
        stats.rows,
        stats.errors,
        stats.missing_tickers,
    )


def _duration_elapsed(stop_at: float | None) -> bool:
    return stop_at is not None and time.monotonic() >= stop_at


def _sleep_interruptibly(seconds: float, should_stop: Callable[[], bool], stop_at: float | None) -> None:
    deadline = time.monotonic() + seconds
    if stop_at is not None:
        deadline = min(deadline, stop_at)
    while not should_stop() and not _duration_elapsed(stop_at):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.5))
