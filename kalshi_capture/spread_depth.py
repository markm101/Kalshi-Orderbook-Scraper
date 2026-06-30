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

LATEST_REPORT_COLUMNS = (
    "category",
    "ticker",
    "capture_ts_ms",
    "snapshot_id",
    "book_state",
    "yes_best_bid",
    "yes_best_ask",
    "yes_spread",
    "yes_top_bid_size",
    "yes_top_ask_size",
    "no_best_bid",
    "no_best_ask",
    "no_spread",
    "no_top_bid_size",
    "no_top_ask_size",
)


@dataclass
class SnapshotBook:
    category: str
    ticker: str
    outcome: str
    snapshot_id: str
    capture_ts_ms: int = 0
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


@dataclass
class LatestSpreadRow:
    category: str
    ticker: str
    capture_ts_ms: int
    snapshot_id: str
    book_state: str
    yes_best_bid: int | None
    yes_best_ask: int | None
    yes_spread: int | None
    yes_top_bid_size: int
    yes_top_ask_size: int
    no_best_bid: int | None
    no_best_ask: int | None
    no_spread: int | None
    no_top_bid_size: int
    no_top_ask_size: int


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
                for report_row in _report_input_rows(row):
                    ticker = report_row.get("ticker", "")
                    outcome = report_row.get("outcome", "")
                    category = ticker_categories.get(ticker, "Unknown")
                    if category_filter and category not in category_filter:
                        continue
                    if ticker_filter and ticker not in ticker_filter:
                        continue
                    if outcome_filter and outcome not in outcome_filter:
                        continue
                    _add_row(books, category, report_row)

    return tuple(_summarize_books(books))


def build_latest_report(
    output_dir: Path,
    tickers: tuple[str, ...] = (),
    categories: tuple[str, ...] = (),
) -> tuple[LatestSpreadRow, ...]:
    ticker_filter = set(tickers)
    category_filter = set(categories)
    books: dict[tuple[str, str, str, str], SnapshotBook] = {}
    ticker_categories = _load_ticker_categories(output_dir)

    for path in sorted((output_dir / "orderbooks").glob("*.csv")):
        with path.open(newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                for report_row in _report_input_rows(row):
                    ticker = report_row.get("ticker", "")
                    category = ticker_categories.get(ticker, "Unknown")
                    if category_filter and category not in category_filter:
                        continue
                    if ticker_filter and ticker not in ticker_filter:
                        continue
                    _add_row(books, category, report_row)

    return tuple(_summarize_latest_books(books))


def _report_input_rows(row: dict[str, str]) -> tuple[dict[str, str], ...]:
    if row.get("outcome") and row.get("book_side"):
        return (row,)
    if row.get("side") == "yes":
        ask_row = dict(row)
        ask_row["outcome"] = "no"
        ask_row["book_side"] = "ask"
        ask_row["price"] = _complement_price(row.get("price", ""))
        bid_row = dict(row)
        bid_row["outcome"] = "yes"
        bid_row["book_side"] = "bid"
        return (bid_row, ask_row)
    if row.get("side") == "no":
        bid_row = dict(row)
        bid_row["outcome"] = "no"
        bid_row["book_side"] = "bid"
        ask_row = dict(row)
        ask_row["outcome"] = "yes"
        ask_row["book_side"] = "ask"
        ask_row["price"] = _complement_price(row.get("price", ""))
        return (bid_row, ask_row)
    return ()


def _complement_price(value: str) -> str:
    try:
        return str(10000 - int(value))
    except ValueError:
        return ""


def write_report(rows: tuple[ReportRow, ...], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def write_latest_report(rows: tuple[LatestSpreadRow, ...], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=LATEST_REPORT_COLUMNS)
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
    capture_ts_ms = _parse_capture_ts_ms(row.get("capture_ts_ms", ""), snapshot_id)
    if not ticker or outcome not in {"yes", "no"} or book_side not in {"bid", "ask"}:
        return

    key = (category, ticker, outcome, snapshot_id)
    book = books.setdefault(key, SnapshotBook(category, ticker, outcome, snapshot_id))
    book.capture_ts_ms = max(book.capture_ts_ms, capture_ts_ms)
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


def _summarize_latest_books(books: dict[tuple[str, str, str, str], SnapshotBook]) -> list[LatestSpreadRow]:
    grouped: dict[tuple[str, str, str], dict[str, SnapshotBook]] = {}
    for book in books.values():
        grouped.setdefault((book.category, book.ticker, book.snapshot_id), {})[book.outcome] = book

    latest_by_ticker: dict[tuple[str, str], tuple[int, str, dict[str, SnapshotBook]]] = {}
    for (category, ticker, snapshot_id), outcome_books in grouped.items():
        capture_ts_ms = max((book.capture_ts_ms for book in outcome_books.values()), default=0)
        key = (category, ticker)
        current = latest_by_ticker.get(key)
        if current is None or (capture_ts_ms, snapshot_id) > (current[0], current[1]):
            latest_by_ticker[key] = (capture_ts_ms, snapshot_id, outcome_books)

    rows: list[LatestSpreadRow] = []
    for (category, ticker), (capture_ts_ms, snapshot_id, outcome_books) in latest_by_ticker.items():
        yes = outcome_books.get("yes")
        no = outcome_books.get("no")
        yes_bid = yes.best_bid if yes else None
        yes_ask = yes.best_ask if yes else None
        no_bid = no.best_bid if no else None
        no_ask = no.best_ask if no else None
        yes_spread = yes_ask - yes_bid if yes_bid is not None and yes_ask is not None else None
        no_spread = no_ask - no_bid if no_bid is not None and no_ask is not None else None
        rows.append(
            LatestSpreadRow(
                category=category,
                ticker=ticker,
                capture_ts_ms=capture_ts_ms,
                snapshot_id=snapshot_id,
                book_state=_book_state(yes_bid, yes_ask, no_bid, no_ask),
                yes_best_bid=yes_bid,
                yes_best_ask=yes_ask,
                yes_spread=yes_spread,
                yes_top_bid_size=yes.top_bid_size if yes else 0,
                yes_top_ask_size=yes.top_ask_size if yes else 0,
                no_best_bid=no_bid,
                no_best_ask=no_ask,
                no_spread=no_spread,
                no_top_bid_size=no.top_bid_size if no else 0,
                no_top_ask_size=no.top_ask_size if no else 0,
            )
        )

    return sorted(rows, key=lambda row: (row.category, row.ticker))


def _book_state(
    yes_bid: int | None,
    yes_ask: int | None,
    no_bid: int | None,
    no_ask: int | None,
) -> str:
    if yes_bid is not None and yes_ask is not None and no_bid is not None and no_ask is not None:
        return "spread_available"
    if yes_bid is not None or no_bid is not None:
        return "one_sided"
    return "empty"


def _parse_capture_ts_ms(value: str, snapshot_id: str) -> int:
    candidates = (value, snapshot_id.split(":", 1)[0])
    for candidate in candidates:
        try:
            return int(candidate)
        except ValueError:
            continue
    return 0


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
