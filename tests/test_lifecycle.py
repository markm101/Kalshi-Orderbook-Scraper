from tests.support import CaptureTestCase, Exchange, capture, gap_events, known_bug, market, read_csv, run_errors


def after_polls(ticker, count):
    return lambda exchange: exchange.polls[ticker] >= count


def after_seen(ticker, status):
    return lambda exchange: exchange.served[ticker, status] >= 1


def change(ticker, **fields):
    return lambda exchange: exchange.update(ticker, **fields)


class LifecycleTest(CaptureTestCase):
    def results(self):
        rows = read_csv(self.output_dir / "metadata" / "results.csv")
        return [(row["ticker"], row["status"], row["result"]) for row in rows]

    def test_unknown_ticker_does_not_prevent_auto_stop(self):
        steps = ((after_polls("A", 2), change("A", status="finalized", result="yes")),)
        capture(Exchange(market("A")), self.output_dir, steps=steps, tickers=("A", "TYPO"))
        self.assertIn("all_markets_closed", gap_events(self.output_dir))
        self.assertEqual(run_errors(self.output_dir), 0)

    def test_once_records_an_already_finalized_market_without_polling(self):
        exchange = Exchange(market("A", status="finalized", result="no"))
        capture(exchange, self.output_dir, tickers=("A",), once=True)
        self.assertEqual(self.results(), [("A", "finalized", "no")])
        self.assertEqual(exchange.polls["A"], 0)

    @known_bug("a --tickers run stops before the result exists")
    def test_result_is_recorded_after_close(self):
        steps = (
            (after_polls("A", 2), change("A", status="closed")),
            (after_seen("A", "closed"), change("A", status="finalized", result="yes")),
        )
        capture(Exchange(market("A")), self.output_dir, steps=steps, tickers=("A",))
        self.assertEqual(self.results(), [("A", "finalized", "yes")])

    @known_bug("the first result is stored as the final one")
    def test_only_the_final_result_is_recorded(self):
        steps = (
            (after_polls("B", 3), change("A", status="determined", result="yes")),
            (after_polls("B", 6), change("A", status="amended", result="no")),
            (after_polls("B", 9), change("A", status="finalized", result="no")),
        )
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 12), steps, tickers=("A", "B"))
        self.assertEqual(self.results(), [("A", "finalized", "no")])

    @known_bug("a disputed market is treated as open")
    def test_disputed_market_is_not_polled(self):
        exchange = Exchange(market("A", status="disputed", result="yes"), market("B"))
        capture(exchange, self.output_dir, after_polls("B", 4), tickers=("A", "B"))
        self.assertEqual(exchange.polls["A"], 0)

    @known_bug("an amended market is treated as open")
    def test_amended_market_is_not_polled(self):
        exchange = Exchange(market("A", status="amended", result="yes"), market("B"))
        capture(exchange, self.output_dir, after_polls("B", 4), tickers=("A", "B"))
        self.assertEqual(exchange.polls["A"], 0)

    @known_bug("a reopened market is never captured again")
    def test_reopened_market_is_captured(self):
        steps = (
            (after_polls("B", 3), change("A", status="closed")),
            (after_polls("B", 6), change("A", status="active")),
        )
        exchange = Exchange(market("A"), market("B"))
        capture(exchange, self.output_dir, after_polls("B", 12), steps, tickers=("A", "B"))
        self.assertGreaterEqual(exchange.polls["A"], 6)

    @known_bug("an omitted market is taken as closed")
    def test_omitted_market_does_not_end_the_run(self):
        steps = ((after_polls("A", 2), lambda exchange: exchange.markets.pop("A")),)
        capture(Exchange(market("A")), self.output_dir, after_polls("A", 8), steps,
                tickers=("A",), discovery_refresh_seconds=0)
        self.assertNotIn("all_markets_closed", gap_events(self.output_dir))

    @known_bug("a series market that closes before a refresh gets no result")
    def test_series_market_closed_before_refresh_gets_a_result(self):
        steps = ((after_polls("B", 3), change("A", status="finalized", result="yes")),)
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 7), steps,
                series=("S",), discovery_refresh_seconds=0)
        self.assertEqual(self.results(), [("A", "finalized", "yes")])

    @known_bug("markets.csv keeps a closed market as active")
    def test_metadata_follows_the_close(self):
        steps = ((after_polls("B", 3), change("A", status="finalized", result="yes")),)
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 7), steps,
                tickers=("A", "B"))
        status = {row["ticker"]: row["status"] for row in read_csv(self.output_dir / "metadata" / "markets.csv")}
        self.assertEqual(status["A"], "finalized")
