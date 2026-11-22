from kalshi_capture.discovery import discover_markets
from kalshi_capture.selector import select_liquid_tickers
from tests.support import BOOK, CaptureTestCase, Exchange, capture, http_error, known_bug, market


class SelectionTest(CaptureTestCase):
    def test_selector_accepts_category_without_series(self):
        self.assertEqual(select_liquid_tickers(Exchange(), 1, include_categories=("sports",)), ())

    def test_discovery_accepts_category_without_series(self):
        self.assertEqual(discover_markets(Exchange(), categories=("sports",)).markets, ())

    @known_bug("the selector ranks only the 500 newest markets")
    def test_selector_finds_liquid_market_outside_the_newest_500(self):
        newest = [market(f"N{i}", volume_24h_fp="1.00") for i in range(500)]
        exchange = Exchange(*newest, market("BIG", volume_24h_fp="9000000.00"))
        self.assertIn("BIG", select_liquid_tickers(exchange, 5))

    @known_bug("a hyphenated series ticker is cut at the first hyphen", type(http_error(404)))
    def test_hyphenated_series_is_discovered(self):
        exchange = Exchange(market("KXA-P-26", event_ticker="KXA-P-26"), series=[{"ticker": "KXA-P", "category": "Science"}])
        self.assertEqual(len(discover_markets(exchange, categories=("Science",)).markets), 1)

    @known_bug("one large category uses the whole selector budget")
    def test_large_category_does_not_starve_the_next(self):
        series = [{"ticker": f"SP{i}", "category": "Sports"} for i in range(150)]
        series.append({"ticker": "S", "category": "Financials"})
        selected = select_liquid_tickers(Exchange(market("FIN"), series=series), 1, include_categories=("Sports", "Financials"))
        self.assertEqual(selected, ("FIN",))

    @known_bug("markets in a secondary category are dropped")
    def test_secondary_category_is_kept(self):
        series = [{"ticker": "S", "category": "Economics", "categories": ["Economics", "Commodities"]}]
        self.assertEqual(len(discover_markets(Exchange(market("A"), series=series), categories=("Commodities",)).markets), 1)

    @known_bug("a kept pick outside the candidates allows a second pick from its event")
    def test_kept_pick_still_reserves_its_event(self):
        one_sided = {**BOOK, "no_dollars": []}
        exchange = Exchange(
            market("E-K2", event_ticker="E"),
            market("E-K", event_ticker="E"),
            book=lambda ticker, _: BOOK if ticker == "E-K2" else one_sided,
        )
        self.assertEqual(select_liquid_tickers(exchange, 2, keep=("E-K",)), ("E-K",))

    @known_bug("a pick removed by discovery filters holds its slot")
    def test_filtered_pick_does_not_hold_a_slot(self):
        exchange = Exchange(
            market("A", event_ticker="X-A", volume_24h_fp="300"),
            market("B", volume_24h_fp="200"),
            market("C", volume_24h_fp="100"),
            series=[{"ticker": "X", "category": "Exotics"}, {"ticker": "S", "category": "Sports"}],
        )
        capture(exchange, self.output_dir, lambda ex: ex.polls["B"] >= 8,
                select_liquid=2, exclude_categories=("Exotics",), discovery_refresh_seconds=0)
        self.assertTrue((self.output_dir / "orderbooks" / "C.csv").exists())
