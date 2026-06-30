from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


REPORT_COLUMNS = (
    "category",
    "ticker",
    "outcome",
    "snapshots",
    "spread_snapshots",
    "min_spread",
    "avg_spread",
    "max_spread",
    "avg_best_bid",
    "avg_best_ask",
    "avg_top_bid_size",
    "avg_top_ask_size",
    "avg_total_bid_size",
    "avg_total_ask_size",
)


@dataclass
class SnapshotBook:
    category: str
    ticker: str
    outcome: str
    snapshot_id: str
    best_bid: int | None = None
    best_ask: int | None = None
    top_bid_size: int = 0
    top_ask_size: int = 0
    total_bid_size: int = 0
    total_ask_size: int = 0


@dataclass
class ReportRow:
    category: str
    ticker: str
    outcome: str
    snapshots: int
    spread_snapshots: int
    min_spread: int | None
    avg_spread: str
    max_spread: int | None
    avg_best_bid: str
    avg_best_ask: str
    avg_top_bid_size: str
    avg_top_ask_size: str
    avg_total_bid_size: str
    avg_total_ask_size: str


def build_report(
    output_dir: Path,
    tickers: tuple[str, ...] = (),
    categories: tuple[str, ...] = (),
    outcomes: tuple[str, ...] = (),
) -> tuple[ReportRow, ...]:
    ticker_filter = set(tickers)
    category_filter = set(categories)
    outcome_filter = set(outcomes)
    books: dict[tuple[str, str, str, str], SnapshotBook] = {}
    ticker_categories = _load_ticker_categories(output_dir)

    for path in sorted((output_dir / "orderbooks").glob("*.csv")):
        with path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                ticker = row.get("ticker", "")
                outcome = row.get("outcome", "")
                category = ticker_categories.get(ticker, "Unknown")
                if category_filter and category not in category_filter:
                    continue
                if ticker_filter and ticker not in ticker_filter:
                    continue
                if outcome_filter and outcome not in outcome_filter:
                    continue
                _add_row(books, category, row)

    return tuple(_summarize_books(books))


def write_report(rows: tuple[ReportRow, ...], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def _add_row(books: dict[tuple[str, str, str, str], SnapshotBook], category: str, row: dict[str, str]) -> None:
    try:
        level = int(row.get("level", ""))
        price = int(row.get("price", ""))
        size = int(row.get("size", ""))
    except ValueError:
        return

    ticker = row.get("ticker", "")
    outcome = row.get("outcome", "")
    book_side = row.get("book_side", "")
    snapshot_id = row.get("snapshot_id") or f"{row.get('capture_ts_ms', '')}:{ticker}"
    if not ticker or outcome not in {"yes", "no"} or book_side not in {"bid", "ask"}:
        return

    key = (category, ticker, outcome, snapshot_id)
    book = books.setdefault(key, SnapshotBook(category, ticker, outcome, snapshot_id))
    if book_side == "bid":
        book.total_bid_size += size
        if book.best_bid is None or price > book.best_bid:
            book.best_bid = price
        if level == 0:
            book.top_bid_size += size
    else:
        book.total_ask_size += size
        if book.best_ask is None or price < book.best_ask:
            book.best_ask = price
        if level == 0:
            book.top_ask_size += size


def _summarize_books(books: dict[tuple[str, str, str, str], SnapshotBook]) -> list[ReportRow]:
    grouped: dict[tuple[str, str, str], list[SnapshotBook]] = {}
    for book in books.values():
        grouped.setdefault((book.category, book.ticker, book.outcome), []).append(book)

    rows: list[ReportRow] = []
    for (category, ticker, outcome), items in grouped.items():
        spread_books = [book for book in items if book.best_bid is not None and book.best_ask is not None]
        spreads = [book.best_ask - book.best_bid for book in spread_books if book.best_ask is not None and book.best_bid is not None]
        rows.append(
            ReportRow(
                category=category,
                ticker=ticker,
                outcome=outcome,
                snapshots=len(items),
                spread_snapshots=len(spreads),
                min_spread=min(spreads) if spreads else None,
                avg_spread=_avg(spreads),
                max_spread=max(spreads) if spreads else None,
                avg_best_bid=_avg([book.best_bid for book in spread_books if book.best_bid is not None]),
                avg_best_ask=_avg([book.best_ask for book in spread_books if book.best_ask is not None]),
                avg_top_bid_size=_avg([book.top_bid_size for book in items]),
                avg_top_ask_size=_avg([book.top_ask_size for book in items]),
                avg_total_bid_size=_avg([book.total_bid_size for book in items]),
                avg_total_ask_size=_avg([book.total_ask_size for book in items]),
            )
        )

    return sorted(rows, key=_report_sort_key)


def _report_sort_key(row: ReportRow) -> tuple[int, Decimal, str, str]:
    spread_rank = 1 if row.spread_snapshots == 0 else 0
    avg_spread = Decimal(row.avg_spread) if row.avg_spread != "" else Decimal("999999999")
    return (spread_rank, avg_spread, row.category, row.ticker)


def _avg(values: list[int]) -> str:
    if not values:
        return ""
    value = Decimal(sum(values)) / Decimal(len(values))
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _load_ticker_categories(output_dir: Path) -> dict[str, str]:
    metadata_dir = output_dir / "metadata"
    category_by_series: dict[str, str] = {}
    series_path = metadata_dir / "series.csv"
    if series_path.exists():
        with series_path.open(newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                series_ticker = row.get("series_ticker", "")
                category = row.get("sanitized_category") or row.get("category") or "Unknown"
                if series_ticker:
                    category_by_series[series_ticker] = category

    categories: dict[str, str] = {}
    markets_path = metadata_dir / "markets.csv"
    if markets_path.exists():
        with markets_path.open(newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                ticker = row.get("ticker", "")
                series_ticker = row.get("series_ticker", "")
                if ticker:
                    categories[ticker] = category_by_series.get(series_ticker, "Unknown")
    return categories
