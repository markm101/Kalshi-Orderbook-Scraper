import time

from kalshi_capture.discovery import market_result
from tests.support import (
    BOOK,
    EMPTY_BOOK,
    CaptureTestCase,
    Exchange,
    capture,
    gap_events,
    http_error,
    known_bug,
    market,
    read_csv,
    run_errors,
)


class CaptureTest(CaptureTestCase):
    def test_batches_cover_every_ticker_within_the_api_limit(self):
        for count in (1, 99, 100, 101, 200, 250):
            tickers = tuple(f"T{i}" for i in range(count))
            exchange = Exchange(*map(market, tickers))
            output_dir = self.output_dir / str(count)
            capture(exchange, output_dir, tickers=tickers, once=True)
            self.assertLessEqual(max(exchange.batch_sizes), 100)
            self.assertEqual(dict(exchange.polls), dict.fromkeys(tickers, 1))
            self.assertEqual(len(list((output_dir / "orderbooks").iterdir())), count)

    def test_series_discovery_reads_every_page(self):
        tickers = [f"T{i}" for i in range(2001)]
        exchange = Exchange(*map(market, tickers))
        capture(exchange, self.output_dir, series=("S",), once=True)
        self.assertEqual(set(exchange.polls), set(tickers))

    def test_failed_batch_does_not_lose_the_others(self):
        def fail(exchange, path):
            if path == "/markets/orderbooks" and not failed:
                failed.append(path)
                raise http_error(429)

        failed = []
        tickers = tuple(f"T{i}" for i in range(150))
        capture(Exchange(*map(market, tickers), fail=fail), self.output_dir, tickers=tickers, once=True)
        self.assertIn("rate_limited", gap_events(self.output_dir))
        self.assertEqual(len(list((self.output_dir / "orderbooks").iterdir())), 50)

    def test_failed_status_check_does_not_stop_capture(self):
        def fail(exchange, path):
            if path == "/markets" and exchange.polls["A"] == 2 and not failed:
                failed.append(path)
                raise http_error(503)

        failed = []
        capture(Exchange(market("A"), fail=fail), self.output_dir, lambda ex: ex.polls["A"] >= 5, tickers=("A",))
        self.assertIn("status_check_error", gap_events(self.output_dir))

    def test_book_absent_from_response_is_logged(self):
        class NoBooks(Exchange):
            def get(self, path, params=None):
                return {"orderbooks": []} if path == "/markets/orderbooks" else super().get(path, params)

        capture(NoBooks(market("A")), self.output_dir, tickers=("A",), once=True)
        self.assertIn("missing_orderbook", gap_events(self.output_dir))

    def test_metadata_round_trips_unicode_quotes_and_newlines(self):
        title = 'a,"b"\nc é'
        capture(Exchange(market("A", title=title)), self.output_dir, tickers=("A",), once=True)
        self.assertEqual(read_csv(self.output_dir / "metadata" / "markets.csv")[0]["title"], title)

    def test_settlement_value_uses_price_units(self):
        for text, units in (("1.0000", 10000), ("0.0000", 0), ("0.3350", 3350), (None, None), ("", None)):
            self.assertEqual(market_result({"settlement_value_dollars": text}).settlement_value, units)

    @known_bug("a failed discovery refresh ends the run", type(http_error(503)))
    def test_failed_discovery_refresh_does_not_stop_capture(self):
        def fail(exchange, path):
            if path.startswith("/series/") and exchange.polls["A"] >= 2:
                raise http_error(503)

        exchange = Exchange(market("A"), fail=fail)
        capture(exchange, self.output_dir, lambda ex: ex.polls["A"] >= 6, tickers=("A",), discovery_refresh_seconds=0)
        self.assertGreaterEqual(exchange.polls["A"], 6)

    @known_bug("a mistyped ticker is dropped without a gap")
    def test_unknown_ticker_is_reported(self):
        capture(Exchange(market("A")), self.output_dir, tickers=("A", "TYPO"), once=True)
        self.assertIn("TYPO", (self.output_dir / "gaps.csv").read_text())

    @known_bug("an emptied book still shows its last quote")
    def test_emptied_book_is_not_shown_as_tradable(self):
        exchange = Exchange(market("A"), market("B"), book=lambda t, poll: BOOK if t == "B" or poll < 2 else EMPTY_BOOK)
        capture(exchange, self.output_dir, lambda ex: ex.polls["A"] >= 4, tickers=("A", "B"))
        states = {row["ticker"]: row["book_state"] for row in read_csv(self.output_dir / "latest_spread.csv")}
        self.assertNotEqual(states.get("A"), "spread_available")

    @known_bug("an empty snapshot leaves no record")
    def test_empty_snapshot_is_recorded(self):
        capture(Exchange(market("A"), market("B"), book=lambda t, _: BOOK if t == "B" else EMPTY_BOOK),
                self.output_dir, tickers=("A", "B"), once=True)
        reports = {"latest_spread.csv", "spread_depth.csv", "markets.csv"}
        records = [row for path in self.output_dir.rglob("*.csv") if path.name not in reports for row in read_csv(path)]
        self.assertIn("A", {row.get("ticker") for row in records})

    @known_bug("a timestamp predates the response it describes")
    def test_timestamp_is_not_before_the_response(self):
        received = []

        def book(ticker, poll):
            if ticker == "T100":
                time.sleep(0.05)
                received.append(int(time.time() * 1000))
            return BOOK

        tickers = tuple(f"T{i}" for i in range(101))
        capture(Exchange(*map(market, tickers), book=book), self.output_dir, tickers=tickers, once=True)
        row = read_csv(self.output_dir / "orderbooks" / "T100.csv")[0]
        self.assertGreaterEqual(int(row["capture_ts_ms"]), received[0])

    @known_bug("one bad level discards the whole batch")
    def test_bad_level_does_not_discard_other_books(self):
        bad = {"yes_dollars": [["0.50005", "1.00"]]}
        exchange = Exchange(market("A"), market("B"), book=lambda t, _: BOOK if t == "A" else bad)
        capture(exchange, self.output_dir, tickers=("A", "B"), once=True)
        self.assertTrue((self.output_dir / "orderbooks" / "A.csv").exists())

    @known_bug("an empty pick set counts an error on every cycle")
    def test_waiting_for_a_new_pick_is_not_an_error(self):
        steps = ((lambda ex: ex.polls["A"] >= 3, lambda ex: ex.update("A", status="finalized", result="yes")),)
        capture(Exchange(market("A")), self.output_dir, steps=steps, select_liquid=1, duration_seconds=0.3)
        self.assertLessEqual(run_errors(self.output_dir), 1)
