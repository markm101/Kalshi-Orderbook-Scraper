from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_UP
import random

from kalshi_capture.orderbook import OrderBookRow, flatten_orderbook_payload
from kalshi_capture.spread_depth import LatestSnapshots, build_latest_report, build_report
from kalshi_capture.storage import write_orderbook_rows
from scripts.derive_bid_ask import derive_capture
from scripts.inspect_capture import inspect_capture
from tests.support import CaptureTestCase, Exchange, capture, known_bug, market

RAW_HEADER = "capture_ts_ms,ticker,side,level,price,size,snapshot_id\n"


def mean(values):
    if not values:
        return ""
    return str((Decimal(sum(values)) / len(values)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class ReportTest(CaptureTestCase):
    def test_reports_agree_with_independent_totals(self):
        rng = random.Random(2)
        for case in range(100):
            output_dir = self.output_dir / str(case)
            in_memory = LatestSnapshots()
            snapshots, latest, spreads, row_count = {}, {}, {}, 0
            for cycle in range(rng.randint(1, 10)):
                for ticker in "ABC":
                    sides, book = {}, {}
                    for side in ("yes", "no"):
                        prices = rng.sample(range(1, 10000), rng.randint(0, 8))
                        sides[side] = [(price, rng.randint(1, 100000)) for price in prices]
                        book[f"{side}_dollars"] = [[str(Decimal(p) / 10000), str(Decimal(q) / 100)] for p, q in sides[side]]
                    if not (sides["yes"] or sides["no"]):
                        continue
                    ts = 1795000000000 + cycle * 2000
                    rows = flatten_orderbook_payload({"orderbooks": [{"ticker": ticker, "orderbook_fp": book}]}, ts)
                    write_orderbook_rows(output_dir, rows, {})
                    in_memory.update({key: str(value) for key, value in asdict(row).items()} for row in rows)
                    row_count += len(rows)
                    bid = max((p for p, _ in sides["yes"]), default=None)
                    ask = min((10000 - p for p, _ in sides["no"]), default=None)
                    spread = None if bid is None or ask is None else ask - bid
                    depth = {side: sum(q for _, q in levels) for side, levels in sides.items()}
                    snapshots.setdefault(ticker, []).append(depth)
                    spreads.setdefault(ticker, []).extend([] if spread is None else [spread])
                    latest[ticker] = (ts, bid, ask, spread)

            report = build_report(output_dir)
            self.assertEqual(len(report), 2 * len(snapshots))
            for row in report:
                opposite = "no" if row.outcome == "yes" else "yes"
                self.assertEqual(row.snapshots, len(snapshots[row.ticker]))
                self.assertEqual(row.avg_spread, mean(spreads[row.ticker]))
                self.assertEqual(row.avg_total_bid_size, mean([d[row.outcome] for d in snapshots[row.ticker]]))
                self.assertEqual(row.avg_total_ask_size, mean([d[opposite] for d in snapshots[row.ticker]]))

            from_files = build_latest_report(output_dir)
            self.assertEqual(from_files, build_latest_report(output_dir, snapshots=in_memory))
            actual = {r.ticker: (r.capture_ts_ms, r.yes_best_bid, r.yes_best_ask, r.yes_spread) for r in from_files}
            self.assertEqual(actual, latest)

            summary = inspect_capture(output_dir)
            self.assertEqual(summary.orderbook_rows, row_count)
            self.assertEqual(summary.spread_count, sum(map(len, spreads.values())))

            derived_dir = self.output_dir / f"{case}-derived"
            self.assertEqual(derive_capture(output_dir, derived_dir), 2 * row_count)
            self.assertEqual(build_report(derived_dir), report)

    @known_bug("deriving into the input directory truncates the raw CSVs")
    def test_derive_never_overwrites_its_input(self):
        path = self.output_dir / "orderbooks" / "T.csv"
        path.parent.mkdir()
        text = RAW_HEADER + "1,T,yes,0,4000,100,1:T\n"
        path.write_text(text)
        try:
            derive_capture(self.output_dir, self.output_dir)
        except ValueError:
            pass
        self.assertEqual(path.read_text(), text)

    @known_bug("a truncated row crashes the report", TypeError)
    def test_truncated_row_is_skipped(self):
        path = self.output_dir / "orderbooks" / "T.csv"
        path.parent.mkdir()
        path.write_text(RAW_HEADER + "1,T,yes,0,4000,100,1:T\n2,T,yes,0")
        self.assertEqual(len(build_report(self.output_dir)), 2)

    @known_bug("an append after a torn write corrupts the new row")
    def test_append_after_torn_write_keeps_new_row(self):
        path = self.output_dir / "orderbooks" / "T.csv"
        path.parent.mkdir()
        path.write_text(RAW_HEADER + "1000,T,yes,0,4000,1")
        write_orderbook_rows(self.output_dir, (OrderBookRow(2000, "T", "yes", 0, 4100, 700, "2000:T"),), {})
        self.assertTrue(any(line.startswith("2000,") for line in path.read_text().splitlines()))

    @known_bug("a restart overwrites the metadata of earlier markets")
    def test_restart_keeps_categories_of_earlier_markets(self):
        for ticker in ("A", "B"):
            capture(Exchange(market(ticker)), self.output_dir, tickers=(ticker,), once=True)
        self.assertEqual({row.category for row in build_report(self.output_dir)}, {"Sports"})
