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
    DiscoveryResult,
    MarketMetadata,
    MarketPhase,
    SeriesMetadata,
    discover_markets,
    fetch_markets_by_ticker,
    market_phase,
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


# Kalshi can remove a provisional market for good, so absence cannot be waited out forever.
MAX_MISSED_STATUS_CHECKS = 15


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
class TrackedMarket:
    metadata: MarketMetadata
    # Only status checks set these. Discovery's copy of the status can be stale.
    status: str = ""
    result: str = ""
    missed_checks: int = 0

    @property
    def phase(self) -> MarketPhase:
        if self.missed_checks >= MAX_MISSED_STATUS_CHECKS:
            return MarketPhase.UNAVAILABLE
        return market_phase(self.status)


@dataclass
class TrackedMarkets:
    # Every pick of the run, so a reopened one takes up a slot again.
    picked: tuple[str, ...] = ()
    markets: dict[str, TrackedMarket] = field(default_factory=dict)
    series: dict[str, SeriesMetadata] = field(default_factory=dict)

    def add(self, discovery: DiscoveryResult) -> None:
        for metadata in discovery.markets:
            market = self.markets.setdefault(metadata.ticker, TrackedMarket(metadata))
            market.metadata = metadata
            if market.phase is MarketPhase.UNAVAILABLE:
                market.missed_checks = 0
        self.series.update((item.series_ticker, item) for item in discovery.series)

    def in_phase(self, *phases: MarketPhase) -> dict[str, TrackedMarket]:
        return {ticker: market for ticker, market in self.markets.items() if market.phase in phases}

    def polled(self) -> DiscoveryResult:
        markets = tuple(market.metadata for market in self.in_phase(MarketPhase.TRADING).values())
        series_tickers = {market.series_ticker for market in markets}
        return DiscoveryResult(
            markets=markets,
            series=tuple(item for item in self.series.values() if item.series_ticker in series_tickers),
        )


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
        _discover(config, client, gap_logger, tracked)
        if not tracked.markets:
            gap_logger.log("empty_ticker_set", "no markets matched discovery filters")
            logging.warning("no markets matched discovery filters")
            return

        _write_metadata(config, tracked)

        if config.once:
            _check_market_status(config, client, tracked, gap_logger)
            if _stop_when_all_finalized(config, tracked, gap_logger):
                return
            _capture_cycle(config, client, tracked, gap_logger, stats, latest_snapshots)
            _write_latest_spread_report(config, gap_logger, latest_snapshots)
            return

        next_discovery_refresh = time.monotonic() + config.discovery_refresh_seconds
        next_status_check = time.monotonic()
        next_heartbeat = time.monotonic() + config.heartbeat_seconds
        stop_at = time.monotonic() + config.duration_seconds if config.duration_seconds > 0 else None
        while not should_stop() and not _duration_elapsed(stop_at):
            cycle_start = time.monotonic()
            if time.monotonic() >= next_discovery_refresh:
                try:
                    _discover(config, client, gap_logger, tracked)
                except Exception:
                    stats.errors += 1
                    logging.exception("discovery refresh failed; keeping the current markets")
                else:
                    _write_metadata(config, tracked)
                next_discovery_refresh = time.monotonic() + config.discovery_refresh_seconds
            if time.monotonic() >= next_status_check:
                _check_market_status(config, client, tracked, gap_logger)
                next_status_check = time.monotonic() + config.status_check_seconds
                if _stop_when_all_finalized(config, tracked, gap_logger):
                    break

            _capture_cycle(config, client, tracked, gap_logger, stats, latest_snapshots)
            _write_latest_spread_report(config, gap_logger, latest_snapshots)

            if time.monotonic() >= next_heartbeat:
                _log_heartbeat(tracked.polled(), stats)
                next_heartbeat = time.monotonic() + config.heartbeat_seconds

            elapsed = time.monotonic() - cycle_start
            _sleep_interruptibly(max(0.0, config.interval - elapsed), should_stop, stop_at)
    finally:
        stats.ended_ts_ms = int(time.time() * 1000)
        stats.tracked_tickers = len(tracked.in_phase(MarketPhase.TRADING))
        stats.tracked_categories = len({item.sanitized_category for item in tracked.series.values()})
        _write_run_summary(config, stats)
        _log_pending_results(tracked, gap_logger)
        _write_spread_depth_report(config, gap_logger)
        _write_latest_spread_report(config, gap_logger, latest_snapshots)
        gap_logger.log("shutdown", "capture stopped")


def _discover(config: Config, client: KalshiClient, gap_logger: GapLogger, tracked: TrackedMarkets) -> None:
    try:
        not_trading = tracked.in_phase(MarketPhase.SETTLING, MarketPhase.FINALIZED)
        unavailable = tracked.in_phase(MarketPhase.UNAVAILABLE)
        tickers = config.tickers
        if config.select_liquid:
            # Picks stay until they close; the selector only fills free slots.
            keep = tuple(ticker for ticker in tracked.picked if ticker not in not_trading and ticker not in unavailable)
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
            tickers = tuple(dict.fromkeys((*tickers, *selected)))

        discovery = discover_markets(
            client,
            tickers=tuple(ticker for ticker in tickers if ticker not in not_trading),
            series=config.series,
            categories=config.categories,
            exclude_categories=config.exclude_categories,
        )
        if config.select_liquid:
            tracked.picked = tuple(dict.fromkeys((*tracked.picked, *selected)))
        tracked.add(discovery)
    except Exception as exc:
        gap_logger.log("discovery_error", str(exc))
        raise


def _check_market_status(
    config: Config,
    client: KalshiClient,
    tracked: TrackedMarkets,
    gap_logger: GapLogger,
) -> None:
    watched = tracked.in_phase(MarketPhase.TRADING, MarketPhase.SETTLING)
    if not watched:
        return
    try:
        latest = fetch_markets_by_ticker(client, tuple(watched))
    except Exception as exc:
        gap_logger.log("status_check_error", str(exc))
        logging.warning("market status check failed error=%s", exc)
        return

    for ticker, market in watched.items():
        item = latest.get(ticker)
        if item is None:
            market.missed_checks += 1
            if market.missed_checks == 1:
                gap_logger.log("market_missing", "ticker absent from successful status response", ticker=ticker)
                logging.warning("market missing from status check ticker=%s", ticker)
            if market.phase is MarketPhase.UNAVAILABLE:
                detail = f"status={market.status} result={market.result or 'pending'} missed_checks={market.missed_checks}"
                gap_logger.log("market_unavailable", detail, ticker=ticker)
                logging.warning("stopped watching unavailable market ticker=%s", ticker)
            continue
        market.missed_checks = 0
        previous = market.phase
        market.status = str(item.get("status") or "")
        market.result = str(item.get("result") or "")
        if market.phase is previous:
            continue

        detail = f"status={market.status} result={market.result or 'pending'} close_time={item.get('close_time') or ''}"
        if previous is MarketPhase.TRADING:
            gap_logger.log("market_closed", detail, ticker=ticker)
            logging.info("market closed ticker=%s %s", ticker, detail)
        elif market.phase is MarketPhase.TRADING:
            gap_logger.log("market_reopened", detail, ticker=ticker)
            logging.info("market reopened ticker=%s %s", ticker, detail)
        if market.phase is MarketPhase.FINALIZED:
            append_market_result(config.output_dir, market_result(item))


def _stop_when_all_finalized(config: Config, tracked: TrackedMarkets, gap_logger: GapLogger) -> bool:
    # Picks and series/category discovery can add markets later; a --tickers list cannot.
    if config.select_liquid or config.series or config.categories:
        return False
    if tracked.in_phase(MarketPhase.TRADING, MarketPhase.SETTLING):
        return False
    if tracked.in_phase(MarketPhase.UNAVAILABLE):
        event, detail = "markets_unavailable", "every tracked market is finalized or unavailable; stopping"
    else:
        event, detail = "all_markets_closed", "every tracked market is finalized; stopping"
    gap_logger.log(event, detail)
    logging.info(detail)
    return True


def _log_pending_results(tracked: TrackedMarkets, gap_logger: GapLogger) -> None:
    for ticker, market in tracked.markets.items():
        if market_phase(market.status) is not MarketPhase.SETTLING:
            continue
        gap_logger.log("result_pending", f"status={market.status} result={market.result or 'pending'}", ticker=ticker)


def _write_metadata(config: Config, tracked: TrackedMarkets) -> None:
    # Keep every market seen during the run, so closed markets keep their metadata.
    write_metadata(
        config.output_dir,
        DiscoveryResult(
            markets=tuple(market.metadata for market in tracked.markets.values()),
            series=tuple(tracked.series.values()),
        ),
    )


def _capture_cycle(
    config: Config,
    client: KalshiClient,
    tracked: TrackedMarkets,
    gap_logger: GapLogger,
    stats: CaptureStats,
    latest_snapshots: LatestSnapshots,
) -> None:
    polled = tracked.polled()
    tickers = tuple(market.ticker for market in polled.markets)
    categories = polled.ticker_categories
    capture_ts_ms = int(time.time() * 1000)

    if not tickers:
        if tracked.in_phase(MarketPhase.SETTLING):
            return
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
