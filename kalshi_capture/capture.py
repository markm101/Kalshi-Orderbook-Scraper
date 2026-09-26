from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
import json

import httpx

from kalshi_capture.client import KalshiClient
from kalshi_capture.config import Config
from kalshi_capture.discovery import (
    CLOSED_MARKET_STATUSES,
    DiscoveryResult,
    MarketMetadata,
    SeriesMetadata,
    discover_markets,
    fetch_markets_by_ticker,
    market_result,
)
from kalshi_capture.gaps import GapLogger
from kalshi_capture.orderbook import OrderBookRow, fetch_orderbook_batch
from kalshi_capture.selector import select_liquid_tickers
from kalshi_capture.spread_depth import (
    LatestSnapshots,
    build_latest_report,
    build_report,
    write_latest_report,
    write_report,
)
from kalshi_capture.storage import append_market_result, write_metadata, write_orderbook_rows


@dataclass
class CaptureStats:
    started_ts_ms: int = 0
    ended_ts_ms: int = 0
    tracked_tickers: int = 0
    tracked_categories: int = 0
    cycles: int = 0
    batches: int = 0
    rows: int = 0
    errors: int = 0
    missing_tickers: int = 0
    zero_row_batches: int = 0


@dataclass
class TrackedMarkets:
    picked: tuple[str, ...] = ()
    closed: set[str] = field(default_factory=set)
    awaiting_result: set[str] = field(default_factory=set)
    markets: dict[str, MarketMetadata] = field(default_factory=dict)
    series: dict[str, SeriesMetadata] = field(default_factory=dict)


def run_capture(
    config: Config,
    client: KalshiClient,
    stop_requested: Callable[[], bool] | None = None,
) -> None:
    should_stop = stop_requested or (lambda: False)
    gap_logger = GapLogger(config.output_dir)
    stats = CaptureStats(started_ts_ms=int(time.time() * 1000))
    latest_snapshots = LatestSnapshots()
    tracked = TrackedMarkets()
    gap_logger.log("startup", "capture started")

    try:
        discovery = _discover(config, client, gap_logger, tracked)
        if not discovery.markets:
            gap_logger.log("empty_ticker_set", "no markets matched discovery filters")
            logging.warning("no markets matched discovery filters")
            return

        _update_tracked_counts(discovery, stats)
        _write_metadata(config, discovery, tracked)

        if config.once:
            discovery = _check_market_status(config, client, discovery, tracked, gap_logger)
            if _stop_when_all_closed(config, discovery, gap_logger):
                return
            _capture_cycle(config, client, discovery, gap_logger, stats, latest_snapshots)
            _write_latest_spread_report(config, gap_logger, latest_snapshots)
            return

        next_discovery_refresh = time.monotonic() + config.discovery_refresh_seconds
        next_status_check = time.monotonic()
        next_heartbeat = time.monotonic() + config.heartbeat_seconds
        stop_at = time.monotonic() + config.duration_seconds if config.duration_seconds > 0 else None
        while not should_stop() and not _duration_elapsed(stop_at):
            cycle_start = time.monotonic()
            if time.monotonic() >= next_discovery_refresh:
                discovery = _discover(config, client, gap_logger, tracked)
                _update_tracked_counts(discovery, stats)
                _write_metadata(config, discovery, tracked)
                next_discovery_refresh = time.monotonic() + config.discovery_refresh_seconds
            if time.monotonic() >= next_status_check:
                discovery = _check_market_status(config, client, discovery, tracked, gap_logger)
                _update_tracked_counts(discovery, stats)
                next_status_check = time.monotonic() + config.status_check_seconds
                if _stop_when_all_closed(config, discovery, gap_logger):
                    break

            _capture_cycle(config, client, discovery, gap_logger, stats, latest_snapshots)
            _write_latest_spread_report(config, gap_logger, latest_snapshots)

            if time.monotonic() >= next_heartbeat:
                _log_heartbeat(discovery, stats)
                next_heartbeat = time.monotonic() + config.heartbeat_seconds

            elapsed = time.monotonic() - cycle_start
            _sleep_interruptibly(max(0.0, config.interval - elapsed), should_stop, stop_at)
    finally:
        stats.ended_ts_ms = int(time.time() * 1000)
        _write_run_summary(config, stats)
        _write_spread_depth_report(config, gap_logger)
        _write_latest_spread_report(config, gap_logger, latest_snapshots)
        gap_logger.log("shutdown", "capture stopped")


def _discover(config: Config, client: KalshiClient, gap_logger: GapLogger, tracked: TrackedMarkets) -> DiscoveryResult:
    try:
        tickers = config.tickers
        if config.select_liquid:
            # Picks stay until they close; the selector only fills free slots.
            keep = tuple(ticker for ticker in tracked.picked if ticker not in tracked.closed)
            selected = select_liquid_tickers(
                client,
                limit=config.select_liquid,
                scan_pages=config.liquid_scan_pages,
                min_rows=config.min_orderbook_rows,
                min_top_level_size=config.min_top_level_size,
                include_categories=config.selector_categories,
                exclude_categories=config.selector_exclude_categories,
                min_close_hours=config.min_close_hours,
                min_volume=config.min_volume,
                min_open_interest=config.min_open_interest,
                keep=keep,
            )
            logging.info("selected liquid tickers=%s", selected)
            tracked.picked = selected
            tickers = tuple(dict.fromkeys((*tickers, *selected)))

        discovery = discover_markets(
            client,
            tickers=tuple(ticker for ticker in tickers if ticker not in tracked.closed),
            series=config.series,
            categories=config.categories,
            exclude_categories=config.exclude_categories,
        )
        return _without_closed(discovery, tracked.closed)
    except Exception as exc:
        gap_logger.log("discovery_error", str(exc))
        raise


def _check_market_status(
    config: Config,
    client: KalshiClient,
    discovery: DiscoveryResult,
    tracked: TrackedMarkets,
    gap_logger: GapLogger,
) -> DiscoveryResult:
    tickers = tuple(dict.fromkeys((*(market.ticker for market in discovery.markets), *sorted(tracked.awaiting_result))))
    if not tickers:
        return discovery
    try:
        markets = fetch_markets_by_ticker(client, tickers)
    except Exception as exc:
        gap_logger.log("status_check_error", str(exc))
        logging.warning("market status check failed error=%s", exc)
        return discovery

    for ticker in tickers:
        market = markets.get(ticker)
        if market is None:
            continue
        status = str(market.get("status") or "")
        result = str(market.get("result") or "")
        if ticker not in tracked.closed and status in CLOSED_MARKET_STATUSES:
            tracked.closed.add(ticker)
            tracked.awaiting_result.add(ticker)
            detail = f"status={status} result={result or 'pending'} close_time={market.get('close_time') or ''}"
            gap_logger.log("market_closed", detail, ticker=ticker)
            logging.info("market closed ticker=%s %s", ticker, detail)
        if ticker in tracked.awaiting_result and result:
            append_market_result(config.output_dir, market_result(market))
            tracked.awaiting_result.discard(ticker)
    return _without_closed(discovery, tracked.closed)


def _stop_when_all_closed(config: Config, discovery: DiscoveryResult, gap_logger: GapLogger) -> bool:
    # Picks and series/category discovery can add markets later; a --tickers list cannot.
    if discovery.markets or config.select_liquid or config.series or config.categories:
        return False
    gap_logger.log("all_markets_closed", "every tracked market has closed; stopping")
    logging.info("every tracked market has closed; stopping")
    return True


def _without_closed(discovery: DiscoveryResult, closed: set[str]) -> DiscoveryResult:
    if not closed:
        return discovery
    return DiscoveryResult(
        markets=tuple(market for market in discovery.markets if market.ticker not in closed),
        series=discovery.series,
    )


def _write_metadata(config: Config, discovery: DiscoveryResult, tracked: TrackedMarkets) -> None:
    # Keep every market seen during the run, so closed markets keep their metadata.
    tracked.markets.update((market.ticker, market) for market in discovery.markets)
    tracked.series.update((item.series_ticker, item) for item in discovery.series)
    write_metadata(
        config.output_dir,
        DiscoveryResult(markets=tuple(tracked.markets.values()), series=tuple(tracked.series.values())),
    )


def _capture_cycle(
    config: Config,
    client: KalshiClient,
    discovery: DiscoveryResult,
    gap_logger: GapLogger,
    stats: CaptureStats,
    latest_snapshots: LatestSnapshots,
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
            if not batch.rows:
                gap_logger.log("zero_rows", f"no orderbook levels returned for tickers={','.join(chunk)}")
                stats.zero_row_batches += 1
                logging.warning("orderbook batch returned zero rows tickers=%s", chunk)
            write_orderbook_rows(config.output_dir, batch.rows, categories)
            latest_snapshots.update(_csv_row(row) for row in batch.rows)
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


def _csv_row(row: OrderBookRow) -> dict[str, str]:
    return {name: str(value) for name, value in asdict(row).items()}


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
        "heartbeat tracked_tickers=%s categories=%s cycles=%s batches=%s rows=%s errors=%s missing_tickers=%s zero_row_batches=%s",
        len(discovery.markets),
        len(categories),
        stats.cycles,
        stats.batches,
        stats.rows,
        stats.errors,
        stats.missing_tickers,
        stats.zero_row_batches,
    )


def _update_tracked_counts(discovery: DiscoveryResult, stats: CaptureStats) -> None:
    stats.tracked_tickers = len(discovery.markets)
    stats.tracked_categories = len({item.sanitized_category for item in discovery.series})


def _write_run_summary(config: Config, stats: CaptureStats) -> None:
    output_path = config.output_dir / "run_summary.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = asdict(stats)
    summary["duration_ms"] = max(0, stats.ended_ts_ms - stats.started_ts_ms)
    summary["env"] = config.env
    summary["interval"] = config.interval
    summary["max_levels"] = config.max_levels
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


def _write_spread_depth_report(config: Config, gap_logger: GapLogger) -> None:
    try:
        rows = build_report(config.output_dir)
        output_path = config.output_dir / "spread_depth.csv"
        write_report(rows, output_path)
        logging.info("wrote spread/depth report rows=%s path=%s", len(rows), output_path)
    except Exception as exc:
        gap_logger.log("spread_depth_error", str(exc))
        logging.exception("spread/depth report failed")


def _write_latest_spread_report(config: Config, gap_logger: GapLogger, latest_snapshots: LatestSnapshots) -> None:
    try:
        rows = build_latest_report(config.output_dir, snapshots=latest_snapshots)
        output_path = config.output_dir / "latest_spread.csv"
        write_latest_report(rows, output_path)
        logging.info("wrote latest spread report rows=%s path=%s", len(rows), output_path)
    except Exception as exc:
        gap_logger.log("latest_spread_error", str(exc))
        logging.exception("latest spread report failed")


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
