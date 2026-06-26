from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from kalshi_capture.client import KalshiClient


UNKNOWN_CATEGORY = "Unknown"


@dataclass(frozen=True)
class MarketMetadata:
    ticker: str
    event_ticker: str
    series_ticker: str
    market_type: str
    status: str
    title: str
    yes_sub_title: str
    no_sub_title: str
    open_time: str
    close_time: str
    updated_time: str


@dataclass(frozen=True)
class SeriesMetadata:
    series_ticker: str
    category: str
    sanitized_category: str
    tags: str
    title: str
    frequency: str
    updated_at: str


@dataclass(frozen=True)
class DiscoveryResult:
    markets: tuple[MarketMetadata, ...]
    series: tuple[SeriesMetadata, ...]

    @property
    def ticker_categories(self) -> dict[str, str]:
        categories_by_series = {item.series_ticker: item.sanitized_category for item in self.series}
        return {
            market.ticker: categories_by_series.get(market.series_ticker, UNKNOWN_CATEGORY)
            for market in self.markets
        }


def sanitize_category(category: str | None) -> str:
    value = (category or UNKNOWN_CATEGORY).strip() or UNKNOWN_CATEGORY
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return value or UNKNOWN_CATEGORY


def discover_markets(
    client: KalshiClient,
    tickers: tuple[str, ...] = (),
    series: tuple[str, ...] = (),
    categories: tuple[str, ...] = (),
    exclude_categories: tuple[str, ...] = (),
) -> DiscoveryResult:
    raw_markets: dict[str, dict[str, Any]] = {}

    if tickers:
        raw_markets.update(_fetch_markets_by_ticker(client, tickers))

    for series_ticker in series:
        for market in _fetch_open_markets(client, series_ticker=series_ticker):
            ticker = _as_str(market.get("ticker"))
            if ticker:
                raw_markets[ticker] = market

    category_series = _fetch_series_for_categories(client, categories)
    for series_ticker in category_series:
        for market in _fetch_open_markets(client, series_ticker=series_ticker):
            ticker = _as_str(market.get("ticker"))
            if ticker:
                raw_markets[ticker] = market

    market_items = tuple(_market_metadata(market) for market in raw_markets.values())
    series_tickers = tuple(sorted({market.series_ticker for market in market_items if market.series_ticker}))
    series_items = _fetch_series_metadata(client, series_tickers, category_series)

    if exclude_categories or categories:
        market_items = _filter_markets_by_category(
            market_items,
            series_items,
            include_categories=categories,
            exclude_categories=exclude_categories,
        )
        needed_series = {market.series_ticker for market in market_items}
        series_items = tuple(item for item in series_items if item.series_ticker in needed_series)

    return DiscoveryResult(markets=market_items, series=series_items)


def _fetch_markets_by_ticker(client: KalshiClient, tickers: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    markets: dict[str, dict[str, Any]] = {}
    for i in range(0, len(tickers), 100):
        chunk = tickers[i : i + 100]
        payload = client.get("/markets", params={"tickers": ",".join(chunk), "limit": 1000})
        for market in payload.get("markets", []):
            ticker = _as_str(market.get("ticker"))
            if ticker:
                markets[ticker] = market
    return markets


def _fetch_open_markets(client: KalshiClient, series_ticker: str | None = None) -> tuple[dict[str, Any], ...]:
    params: dict[str, Any] = {"status": "open", "limit": 1000}
    if series_ticker:
        params["series_ticker"] = series_ticker

    markets: list[dict[str, Any]] = []
    cursor = ""
    while True:
        if cursor:
            params["cursor"] = cursor
        else:
            params.pop("cursor", None)

        payload = client.get("/markets", params=params)
        markets.extend(item for item in payload.get("markets", []) if isinstance(item, dict))
        cursor = _as_str(payload.get("cursor"))
        if not cursor:
            break

    return tuple(markets)


def _fetch_series_for_categories(
    client: KalshiClient,
    categories: tuple[str, ...],
) -> dict[str, SeriesMetadata]:
    series_by_ticker: dict[str, SeriesMetadata] = {}
    for category in categories:
        payload = client.get("/series", params={"category": category, "include_product_metadata": "true"})
        for item in payload.get("series", []):
            if not isinstance(item, dict):
                continue
            metadata = _series_metadata(item)
            if metadata.series_ticker:
                series_by_ticker[metadata.series_ticker] = metadata
    return series_by_ticker


def _fetch_series_metadata(
    client: KalshiClient,
    series_tickers: tuple[str, ...],
    seed: dict[str, SeriesMetadata],
) -> tuple[SeriesMetadata, ...]:
    series_by_ticker = dict(seed)
    for series_ticker in series_tickers:
        if series_ticker in series_by_ticker:
            continue
        payload = client.get(f"/series/{series_ticker}")
        item = payload.get("series")
        if isinstance(item, dict):
            metadata = _series_metadata(item)
            if metadata.series_ticker:
                series_by_ticker[metadata.series_ticker] = metadata
    return tuple(series_by_ticker[ticker] for ticker in sorted(series_by_ticker))


def _filter_markets_by_category(
    markets: tuple[MarketMetadata, ...],
    series: tuple[SeriesMetadata, ...],
    include_categories: tuple[str, ...],
    exclude_categories: tuple[str, ...],
) -> tuple[MarketMetadata, ...]:
    category_by_series = {item.series_ticker: item.category.casefold() for item in series}
    include = {item.casefold() for item in include_categories}
    exclude = {item.casefold() for item in exclude_categories}

    filtered: list[MarketMetadata] = []
    for market in markets:
        category = category_by_series.get(market.series_ticker, UNKNOWN_CATEGORY.casefold())
        if include and category not in include:
            continue
        if exclude and category in exclude:
            continue
        filtered.append(market)
    return tuple(filtered)


def _market_metadata(item: dict[str, Any]) -> MarketMetadata:
    return MarketMetadata(
        ticker=_as_str(item.get("ticker")),
        event_ticker=_as_str(item.get("event_ticker")),
        series_ticker=_series_from_market(item),
        market_type=_as_str(item.get("market_type")),
        status=_as_str(item.get("status")),
        title=_as_str(item.get("title")),
        yes_sub_title=_as_str(item.get("yes_sub_title")),
        no_sub_title=_as_str(item.get("no_sub_title")),
        open_time=_as_str(item.get("open_time")),
        close_time=_as_str(item.get("close_time")),
        updated_time=_as_str(item.get("updated_time")),
    )


def _series_metadata(item: dict[str, Any]) -> SeriesMetadata:
    category = _as_str(item.get("category")) or UNKNOWN_CATEGORY
    tags = item.get("tags")
    return SeriesMetadata(
        series_ticker=_as_str(item.get("ticker")),
        category=category,
        sanitized_category=sanitize_category(category),
        tags="|".join(str(tag) for tag in tags) if isinstance(tags, list) else "",
        title=_as_str(item.get("title")),
        frequency=_as_str(item.get("frequency")),
        updated_at=_as_str(item.get("updated_time") or item.get("last_updated_ts")),
    )


def _series_from_market(item: dict[str, Any]) -> str:
    series_ticker = _as_str(item.get("series_ticker"))
    if series_ticker:
        return series_ticker

    event_ticker = _as_str(item.get("event_ticker"))
    if "-" in event_ticker:
        return event_ticker.split("-", 1)[0]
    return event_ticker


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)
