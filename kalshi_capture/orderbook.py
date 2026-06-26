from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from kalshi_capture.client import KalshiClient


@dataclass(frozen=True)
class OrderBookRow:
    capture_ts_ms: int
    ticker: str
    side: str
    level: int
    price: int
    size: int


@dataclass(frozen=True)
class OrderBookBatch:
    rows: tuple[OrderBookRow, ...]
    returned_tickers: tuple[str, ...]


def fetch_orderbooks(
    client: KalshiClient,
    tickers: tuple[str, ...],
    capture_ts_ms: int,
    max_levels: int = 0,
) -> tuple[OrderBookRow, ...]:
    return fetch_orderbook_batch(client, tickers, capture_ts_ms, max_levels=max_levels).rows


def fetch_orderbook_batch(
    client: KalshiClient,
    tickers: tuple[str, ...],
    capture_ts_ms: int,
    max_levels: int = 0,
) -> OrderBookBatch:
    rows: list[OrderBookRow] = []
    returned_tickers: list[str] = []
    for chunk in _chunks(tickers, 100):
        params = [("tickers", ticker) for ticker in chunk]
        payload = client.get("/markets/orderbooks", params=params)
        rows.extend(flatten_orderbook_payload(payload, capture_ts_ms, max_levels=max_levels))
        returned_tickers.extend(extract_orderbook_tickers(payload))
    return OrderBookBatch(rows=tuple(rows), returned_tickers=tuple(returned_tickers))


def flatten_orderbook_payload(
    payload: dict[str, Any],
    capture_ts_ms: int,
    max_levels: int = 0,
) -> tuple[OrderBookRow, ...]:
    orderbooks = payload.get("orderbooks")
    if not isinstance(orderbooks, list):
        raise ValueError("Expected orderbooks list in response")

    rows: list[OrderBookRow] = []
    for item in orderbooks:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "")
        if not ticker:
            continue
        book = item.get("orderbook_fp")
        if not isinstance(book, dict):
            continue
        rows.extend(_flatten_side(capture_ts_ms, ticker, "yes", book.get("yes_dollars"), max_levels))
        rows.extend(_flatten_side(capture_ts_ms, ticker, "no", book.get("no_dollars"), max_levels))
    return tuple(rows)


def extract_orderbook_tickers(payload: dict[str, Any]) -> tuple[str, ...]:
    orderbooks = payload.get("orderbooks")
    if not isinstance(orderbooks, list):
        raise ValueError("Expected orderbooks list in response")

    tickers: list[str] = []
    for item in orderbooks:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "")
        if ticker:
            tickers.append(ticker)
    return tuple(tickers)


def _flatten_side(
    capture_ts_ms: int,
    ticker: str,
    side: str,
    levels: Any,
    max_levels: int,
) -> tuple[OrderBookRow, ...]:
    if not isinstance(levels, list):
        return ()

    rows: list[OrderBookRow] = []
    selected_levels = levels[:max_levels] if max_levels > 0 else levels
    for level, price_size in enumerate(selected_levels):
        if not isinstance(price_size, list | tuple) or len(price_size) < 2:
            raise ValueError(f"Invalid price level for {ticker} {side}: {price_size!r}")
        rows.append(
            OrderBookRow(
                capture_ts_ms=capture_ts_ms,
                ticker=ticker,
                side=side,
                level=level,
                price=_dollars_to_cents(str(price_size[0])),
                size=_fixed_count_to_int(str(price_size[1])),
            )
        )
    return tuple(rows)


def _dollars_to_cents(value: str) -> int:
    try:
        cents = Decimal(value) * Decimal("100")
    except InvalidOperation as exc:
        raise ValueError(f"Invalid dollar price: {value!r}") from exc
    return _decimal_to_integral_int(cents, f"price {value!r}")


def _fixed_count_to_int(value: str) -> int:
    try:
        count = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid fixed count: {value!r}") from exc
    return _decimal_to_integral_int(count, f"size {value!r}")


def _decimal_to_integral_int(value: Decimal, label: str) -> int:
    integral = value.to_integral_value()
    if value != integral:
        raise ValueError(f"Expected integral {label}, got {value}")
    return int(integral)


def _chunks(items: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(items[i : i + size] for i in range(0, len(items), size))
