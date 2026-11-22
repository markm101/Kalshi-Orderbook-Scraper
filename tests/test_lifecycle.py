import json

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

    def test_result_is_recorded_after_close(self):
        steps = (
            (after_polls("A", 2), change("A", status="closed")),
            (after_seen("A", "closed"), change("A", status="finalized", result="yes")),
        )
        capture(Exchange(market("A")), self.output_dir, steps=steps, tickers=("A",))
        self.assertEqual(self.results(), [("A", "finalized", "yes")])

    def test_only_the_final_result_is_recorded(self):
        steps = (
            (after_polls("B", 3), change("A", status="determined", result="yes")),
            (after_polls("B", 6), change("A", status="amended", result="no")),
            (after_polls("B", 9), change("A", status="finalized", result="no")),
        )
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 12), steps, tickers=("A", "B"))
        self.assertEqual(self.results(), [("A", "finalized", "no")])

    def test_disputed_market_is_not_polled(self):
        exchange = Exchange(market("A", status="disputed", result="yes"), market("B"))
        capture(exchange, self.output_dir, after_polls("B", 4), tickers=("A", "B"))
        self.assertEqual(exchange.polls["A"], 0)

    def test_amended_market_is_not_polled(self):
        exchange = Exchange(market("A", status="amended", result="yes"), market("B"))
        capture(exchange, self.output_dir, after_polls("B", 4), tickers=("A", "B"))
        self.assertEqual(exchange.polls["A"], 0)

    def test_reopened_market_is_captured(self):
        steps = (
            (after_polls("B", 3), change("A", status="closed")),
            (after_polls("B", 6), change("A", status="active")),
        )
        exchange = Exchange(market("A"), market("B"))
        capture(exchange, self.output_dir, after_polls("B", 12), steps, tickers=("A", "B"))
        self.assertGreaterEqual(exchange.polls["A"], 6)

    def test_omitted_market_does_not_end_the_run(self):
        steps = ((after_polls("A", 2), lambda exchange: exchange.markets.pop("A")),)
        capture(Exchange(market("A")), self.output_dir, after_polls("A", 8), steps,
                tickers=("A",), discovery_refresh_seconds=0)
        self.assertNotIn("all_markets_closed", gap_events(self.output_dir))

    def test_series_market_closed_before_refresh_gets_a_result(self):
        steps = ((after_polls("B", 3), change("A", status="finalized", result="yes")),)
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 7), steps,
                series=("S",), discovery_refresh_seconds=0)
        self.assertEqual(self.results(), [("A", "finalized", "yes")])

    def gaps(self, event_type):
        return [row for row in read_csv(self.output_dir / "gaps.csv") if row["event_type"] == event_type]

    def test_only_listed_market_is_captured_again_after_reopen(self):
        steps = (
            (after_polls("A", 2), change("A", status="closed")),
            (after_seen("A", "closed"), change("A", status="active")),
        )
        exchange = Exchange(market("A"))
        capture(exchange, self.output_dir, after_polls("A", 5), steps, tickers=("A",))
        self.assertGreaterEqual(exchange.polls["A"], 5)
        self.assertEqual([row["ticker"] for row in self.gaps("market_reopened")], ["A"])

    def test_reopened_and_closed_again_records_one_result(self):
        steps = (
            (after_polls("B", 3), change("A", status="closed")),
            (after_polls("B", 6), change("A", status="active")),
            (after_polls("B", 9), change("A", status="closed")),
            (after_polls("B", 12), change("A", status="finalized", result="yes")),
        )
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 15), steps,
                tickers=("A", "B"), discovery_refresh_seconds=0)
        self.assertEqual(len(self.gaps("market_closed")), 2)
        self.assertEqual(self.results(), [("A", "finalized", "yes")])

    def test_waiting_for_a_result_is_not_an_error(self):
        steps = ((after_polls("A", 2), change("A", status="determined", result="yes")),)
        exchange = Exchange(market("A"))
        capture(exchange, self.output_dir, lambda ex: ex.served["A", "determined"] >= 5, steps, tickers=("A",))
        self.assertEqual(exchange.polls["A"], 2)
        self.assertEqual(run_errors(self.output_dir), 0)
        self.assertNotIn("empty_ticker_set", gap_events(self.output_dir))
        self.assertEqual(self.results(), [])

    def test_selector_waiting_for_a_result_is_not_an_error(self):
        steps = ((after_polls("A", 4), change("A", status="closed")),)
        capture(Exchange(market("A")), self.output_dir, lambda ex: ex.served["A", "closed"] >= 5, steps, select_liquid=1)
        self.assertEqual(run_errors(self.output_dir), 0)
        self.assertNotIn("empty_ticker_set", gap_events(self.output_dir))

    def test_shutdown_reports_the_provisional_result(self):
        steps = (
            (after_polls("B", 3), change("A", status="determined", result="yes")),
            (after_polls("B", 6), change("A", status="amended", result="no")),
        )
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 9), steps, tickers=("A", "B"))
        (pending,) = self.gaps("result_pending")
        self.assertEqual(pending["ticker"], "A")
        self.assertIn("status=amended", pending["detail"])
        self.assertIn("result=no", pending["detail"])

    def test_pending_result_is_logged_before_the_shutdown_report(self):
        (self.output_dir / "orderbooks" / "unreadable.csv").mkdir(parents=True)
        capture(Exchange(market("A", status="closed")), self.output_dir, tickers=("A",), once=True)
        events = gap_events(self.output_dir)
        self.assertLess(events.index("result_pending"), events.index("spread_depth_error"))

    def test_once_reports_a_pending_result_without_polling(self):
        exchange = Exchange(market("A", status="determined", result="yes"))
        capture(exchange, self.output_dir, tickers=("A",), once=True)
        self.assertEqual(exchange.polls["A"], 0)
        self.assertEqual(self.results(), [])
        self.assertEqual([row["ticker"] for row in self.gaps("result_pending")], ["A"])
        self.assertEqual(run_errors(self.output_dir), 0)
        self.assertNotIn("all_markets_closed", gap_events(self.output_dir))

    def test_finalized_market_without_result_gets_a_row_and_ends_the_run(self):
        steps = ((after_polls("A", 2), change("A", status="finalized", settlement_value_dollars="0.5000")),)
        capture(Exchange(market("A")), self.output_dir, steps=steps, tickers=("A",))
        self.assertEqual(self.results(), [("A", "finalized", "")])
        self.assertIn("all_markets_closed", gap_events(self.output_dir))

    def test_finalized_market_is_terminal(self):
        steps = (
            (after_polls("B", 3), change("A", status="finalized", result="yes")),
            (after_polls("B", 6), change("A", status="active", result="")),
        )
        exchange = Exchange(market("A"), market("B"))
        capture(exchange, self.output_dir, after_polls("B", 10), steps,
                tickers=("A", "B"), series=("S",), discovery_refresh_seconds=0)
        self.assertLessEqual(exchange.polls["A"], 3)
        self.assertEqual(self.results(), [("A", "finalized", "yes")])

    def test_each_omission_is_logged_once(self):
        hidden = market("A")
        steps = (
            (after_polls("B", 3), lambda exchange: exchange.markets.pop("A")),
            (after_polls("B", 7), lambda exchange: exchange.markets.update(A=hidden)),
            (after_polls("B", 11), lambda exchange: exchange.markets.pop("A")),
        )
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 15), steps, tickers=("A", "B"))
        self.assertEqual([row["ticker"] for row in self.gaps("market_missing")], ["A", "A"])

    def test_omitted_closed_market_still_gets_its_result(self):
        hidden = market("A", status="finalized", result="yes")
        steps = (
            (after_polls("B", 3), change("A", status="closed")),
            (after_polls("B", 6), lambda exchange: exchange.markets.pop("A")),
            (after_polls("B", 9), lambda exchange: exchange.markets.update(A=hidden)),
        )
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 12), steps,
                tickers=("A", "B"), discovery_refresh_seconds=0)
        self.assertEqual(self.results(), [("A", "finalized", "yes")])

    def test_closed_pick_frees_its_slot_before_finalization(self):
        exchange = Exchange(market("A", volume_24h_fp="200"), market("C", volume_24h_fp="100"))
        steps = ((after_polls("A", 4), change("A", status="closed")),)
        capture(exchange, self.output_dir, after_polls("C", 8), steps, select_liquid=1, discovery_refresh_seconds=0)
        self.assertTrue((self.output_dir / "orderbooks" / "C.csv").exists())

    def test_paused_or_unrecognized_status_is_still_captured(self):
        exchange = Exchange(market("A", status="inactive"), market("B", status="a_future_status"))
        capture(exchange, self.output_dir, after_polls("A", 4), tickers=("A", "B"))
        self.assertGreaterEqual(exchange.polls["B"], 4)

    def test_permanently_omitted_market_stops_being_watched(self):
        steps = ((after_polls("B", 3), lambda exchange: exchange.markets.pop("A")),)
        exchange = Exchange(market("A"), market("B"))
        capture(exchange, self.output_dir, after_polls("B", 40), steps, tickers=("A", "B"))
        self.assertLess(exchange.polls["A"], 25)
        self.assertEqual([row["ticker"] for row in self.gaps("market_unavailable")], ["A"])

    def test_run_ends_without_claiming_a_close_when_its_market_disappears(self):
        steps = ((after_polls("A", 2), lambda exchange: exchange.markets.pop("A")),)
        capture(Exchange(market("A")), self.output_dir, steps=steps, tickers=("A",), duration_seconds=2)
        events = gap_events(self.output_dir)
        self.assertIn("markets_unavailable", events)
        self.assertNotIn("all_markets_closed", events)
        self.assertEqual(run_errors(self.output_dir), 0)

    def test_disappeared_closed_market_reports_its_pending_result(self):
        steps = (
            (after_polls("A", 2), change("A", status="determined", result="yes")),
            (after_seen("A", "determined"), lambda exchange: exchange.markets.pop("A")),
        )
        capture(Exchange(market("A")), self.output_dir, steps=steps, tickers=("A",), duration_seconds=2)
        self.assertIn("markets_unavailable", gap_events(self.output_dir))
        self.assertIn("result=yes", self.gaps("result_pending")[0]["detail"])

    def test_unavailable_market_is_captured_when_discovery_finds_it_again(self):
        hidden = market("A")
        steps = (
            (after_polls("B", 3), lambda exchange: exchange.markets.pop("A")),
            (after_polls("B", 30), lambda exchange: exchange.markets.update(A=hidden)),
        )
        exchange = Exchange(market("A"), market("B"))
        capture(exchange, self.output_dir, after_polls("B", 45), steps, tickers=("A", "B"), discovery_refresh_seconds=0)
        self.assertGreater(exchange.polls["A"], 25)

    def test_series_and_category_runs_do_not_stop_by_themselves(self):
        for option in ({"series": ("S",)}, {"categories": ("Sports",)}):
            output_dir = self.output_dir / next(iter(option))
            steps = (
                (after_polls("A", 2), change("A", status="finalized", result="yes")),
                (after_seen("A", "finalized"), lambda exchange: exchange.markets.update(B=market("B"))),
            )
            exchange = Exchange(market("A"))
            capture(exchange, output_dir, after_polls("B", 2), steps, discovery_refresh_seconds=0, **option)
            self.assertGreaterEqual(exchange.polls["B"], 2)

    def test_reopened_pick_takes_its_slot_again(self):
        exchange = Exchange(market("A", volume_24h_fp="300"), market("C", volume_24h_fp="200"))
        steps = (
            (after_polls("A", 4), change("A", status="closed")),
            (after_polls("C", 4), change("A", status="active")),
            (after_polls("A", 8), lambda ex: ex.markets.update(D=market("D", volume_24h_fp="900"))),
            (after_polls("A", 10), change("C", status="closed")),
        )
        capture(exchange, self.output_dir, after_polls("A", 18), steps, select_liquid=1, discovery_refresh_seconds=0)
        self.assertFalse((self.output_dir / "orderbooks" / "D.csv").exists())

    def test_status_checks_follow_their_interval(self):
        exchange = Exchange(market("A"))
        capture(exchange, self.output_dir, after_polls("A", 6), tickers=("A",), status_check_seconds=999)
        self.assertEqual(exchange.served["A", "active"], 2)

    def test_settled_status_is_final(self):
        capture(Exchange(market("A", status="settled", result="yes")), self.output_dir, tickers=("A",), once=True)
        self.assertEqual(self.results(), [("A", "settled", "yes")])
        self.assertEqual(self.gaps("result_pending"), [])

    def test_summary_and_category_survive_the_auto_stop(self):
        steps = ((after_polls("A", 2), change("A", status="finalized", result="yes")),)
        capture(Exchange(market("A")), self.output_dir, steps=steps, tickers=("A",))
        summary = json.loads((self.output_dir / "run_summary.json").read_text())
        self.assertEqual(summary["tracked_categories"], 1)
        self.assertEqual(read_csv(self.output_dir / "latest_spread.csv")[0]["category"], "Sports")

    def test_summary_counts_polled_markets(self):
        capture(Exchange(market("A"), market("B")), self.output_dir, tickers=("A", "B"), once=True)
        self.assertEqual(json.loads((self.output_dir / "run_summary.json").read_text())["tracked_tickers"], 2)

    @known_bug("markets.csv keeps a closed market as active")
    def test_metadata_follows_the_close(self):
        steps = ((after_polls("B", 3), change("A", status="finalized", result="yes")),)
        capture(Exchange(market("A"), market("B")), self.output_dir, after_polls("B", 7), steps,
                tickers=("A", "B"))
        status = {row["ticker"]: row["status"] for row in read_csv(self.output_dir / "metadata" / "markets.csv")}
        self.assertEqual(status["A"], "finalized")
