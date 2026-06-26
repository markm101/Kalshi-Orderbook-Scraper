from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kalshi_capture.client import KalshiClient
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
) -> tuple[str, ...]:
    if limit <= 0:
        return ()

    candidates: dict[str, LiquidMarketCandidate] = {}
    cursor = ""
    for _ in range(scan_pages):
        params: dict[str, Any] = {"status": "open", "limit": 100}
        if cursor:
            params["cursor"] = cursor

        market_payload = client.get("/markets", params=params)
        tickers = tuple(
            str(market.get("ticker"))
            for market in market_payload.get("markets", [])
            if isinstance(market, dict) and market.get("ticker")
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


def _rank_candidates(candidates: tuple[LiquidMarketCandidate, ...], limit: int) -> tuple[str, ...]:
    ranked = sorted(candidates, key=lambda item: (item.top_level_size, item.rows, item.ticker), reverse=True)
    return tuple(candidate.ticker for candidate in ranked[:limit])


def _chunks(items: tuple[str, ...], size: int) -> tuple[tuple[str, ...], ...]:
    return tuple(items[i : i + size] for i in range(0, len(items), size))
