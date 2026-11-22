from decimal import Decimal
import random
import unittest

from kalshi_capture.orderbook import flatten_orderbook_payload


def flatten(book, capture_ts_ms=1, max_levels=0):
    payload = {"orderbooks": [{"ticker": "T", "orderbook_fp": book}]}
    return flatten_orderbook_payload(payload, capture_ts_ms, max_levels)


class FlattenTest(unittest.TestCase):
    def test_random_books_store_best_bid_first_in_fixed_units(self):
        rng = random.Random(1)
        for capture_ts_ms in range(5000):
            book, expected = {}, []
            max_levels = rng.choice((0, 0, 1, 3, 10))
            for side in ("yes", "no"):
                count = rng.randint(0, 25)
                levels = [(price, rng.randint(1, 10**9)) for price in rng.sample(range(1, 10000), count)]
                book[f"{side}_dollars"] = [
                    [f"{Decimal(price) / 10000:.4f}", f"{Decimal(size) / 100:.2f}"] for price, size in levels
                ]
                best_first = sorted(levels, reverse=True)
                stored = best_first[:max_levels] if max_levels else best_first
                expected += [
                    (capture_ts_ms, "T", side, level, price, size, f"{capture_ts_ms}:T")
                    for level, (price, size) in enumerate(stored)
                ]
            rows = flatten(book, capture_ts_ms, max_levels)
            actual = [(r.capture_ts_ms, r.ticker, r.side, r.level, r.price, r.size, r.snapshot_id) for r in rows]
            self.assertEqual(actual, expected)

    def test_sub_cent_prices_are_exact(self):
        for text, units in (("0.0001", 1), ("0.0150", 150), ("0.9999", 9999)):
            self.assertEqual(flatten({"yes_dollars": [[text, "1.00"]]})[0].price, units)

    def test_unrepresentable_values_are_rejected(self):
        for level in (["0.00005", "1.00"], ["0.5000", "1.001"], ["x", "1.00"]):
            with self.subTest(level=level), self.assertRaises(ValueError):
                flatten({"yes_dollars": [level]})
