from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from kalshi_capture.client import KalshiClient
from kalshi_capture.discovery import UNKNOWN_CATEGORY
from kalshi_capture.orderbook import flatten_orderbook_payload


@dataclass(frozen=True)
class LiquidMarketCandidate:
    ticker: str
    rows: int
    top_level_size: int


def select_liquid_tickers(
    client: KalshiClient,
    limit: int,
    scan_pages: int = 5,
    min_rows: int = 1,
    min_top_level_size: int = 0,
    include_categories: tuple[str, ...] = (),
    exclude_categories: tuple[str, ...] = (),
    min_close_hours: float = 0.0,
    min_volume: int = 0,
    min_open_interest: int = 0,
) -> tuple[str, ...]:
    if limit <= 0:
        return ()

    candidates: dict[str, LiquidMarketCandidate] = {}
    series_categories: dict[str, str] = {}
    cursor = ""
    for _ in range(scan_pages):
        params: dict[str, Any] = {"status": "open", "limit": 100}
        if cursor:
            params["cursor"] = cursor

        market_payload = client.get("/markets", params=params)
        markets = tuple(item for item in market_payload.get("markets", []) if isinstance(item, dict))
        tickers = tuple(
            str(market.get("ticker"))
            for market in markets
            if market_passes_filters(
                client,
                market,
                series_categories,
                include_categories=include_categories,
                exclude_categories=exclude_categories,
                min_close_hours=min_close_hours,
                min_volume=min_volume,
                min_open_interest=min_open_interest,
            )
            and market.get("ticker")
        )
        for chunk in _chunks(tickers, 100):
            orderbook_payload = client.get("/markets/orderbooks", params=[("tickers", ticker) for ticker in chunk])
            for candidate in score_orderbook_payload(orderbook_payload):
                if candidate.rows < min_rows or candidate.top_level_size < min_top_level_size:
                    continue
                candidates[candidate.ticker] = candidate
                if len(candidates) >= limit:
                    return _rank_candidates(tuple(candidates.values()), limit)

        cursor = str(market_payload.get("cursor") or "")
        if not cursor:
            break

    return _rank_candidates(tuple(candidates.values()), limit)


def score_orderbook_payload(payload: dict[str, Any]) -> tuple[LiquidMarketCandidate, ...]:
    rows = flatten_orderbook_payload(payload, capture_ts_ms=0)
    scores: dict[str, dict[str, int]] = {}
    for row in rows:
        score = scores.setdefault(row.ticker, {"rows": 0, "top_level_size": 0})
        score["rows"] += 1
        if row.level == 0:
            score["top_level_size"] += row.size

    return tuple(
        LiquidMarketCandidate(
            ticker=ticker,
            rows=score["rows"],
            top_level_size=score["top_level_size"],
        )
        for ticker, score in scores.items()
    )


def market_passes_filters(
    client: KalshiClient,
    market: dict[str, Any],
    series_categories: dict[str, str],
    include_categories: tuple[str, ...] = (),
    exclude_categories: tuple[str, ...] = (),
    min_close_hours: float = 0.0,
    min_volume: int = 0,
    min_open_interest: int = 0,
) -> bool:
    if include_categories or exclude_categories:
        category = _market_category(client, market, series_categories).casefold()
        include = {item.casefold() for item in include_categories}
        exclude = {item.casefold() for item in exclude_categories}
        if include and category not in include:
            return False
        if exclude and category in exclude:
            return False

    if min_close_hours > 0 and not _has_min_close_hours(market, min_close_hours):
        return False
    if min_volume > 0 and _market_number(market, ("volume", "volume_24h", "previous_24_hour_volume")) < min_volume:
        return False
    if min_open_interest > 0 and _market_number(market, ("open_interest",)) < min_open_interest:
        return False
    return True


def _rank_candidates(candidates: tuple[LiquidMarketCandidate, ...], limit: int) -> tuple[str, ...]:
    ranked = sorted(candidates, key=lambda item: (item.top_level_size, item.rows, item.ticker), reverse=True)
    return tuple(candidate.ticker for candidate in ranked[:limit])


def _chunks(items: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(items[i : i + size] for i in range(0, len(items), size))


def _market_category(client: KalshiClient, market: dict[str, Any], series_categories: dict[str, str]) -> str:
    series_ticker = _series_from_market(market)
    if not series_ticker:
        return UNKNOWN_CATEGORY
    if series_ticker not in series_categories:
        payload = client.get(f"/series/{series_ticker}")
        series = payload.get("series")
        category = series.get("category") if isinstance(series, dict) else ""
        series_categories[series_ticker] = str(category or UNKNOWN_CATEGORY)
    return series_categories[series_ticker]


def _series_from_market(market: dict[str, Any]) -> str:
    series_ticker = str(market.get("series_ticker") or "")
    if series_ticker:
        return series_ticker

    event_ticker = str(market.get("event_ticker") or "")
    if "-" in event_ticker:
        return event_ticker.split("-", 1)[0]
    return event_ticker


def _has_min_close_hours(market: dict[str, Any], min_close_hours: float) -> bool:
    close_time = str(market.get("close_time") or "")
    if not close_time:
        return False
    try:
        close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
    except ValueError:
        return False
    if close_dt.tzinfo is None:
        close_dt = close_dt.replace(tzinfo=UTC)
    return close_dt >= datetime.now(UTC) + timedelta(hours=min_close_hours)


def _market_number(market: dict[str, Any], fields: tuple[str, ...]) -> int:
    for field in fields:
        value = market.get(field)
        if value in (None, ""):
            continue
        try:
            return int(Decimal(str(value)))
        except (InvalidOperation, ValueError):
            continue
    return 0
