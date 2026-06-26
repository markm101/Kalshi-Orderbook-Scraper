# Kalshi Order Book Capture

This project collects live Kalshi order book snapshots so we can build our own historical order book dataset for strategy research and realistic backtesting.

Kalshi offers price history, trades, and candles, but those are not the same as full order book history. Price history can show where a market traded or quoted. Order book history shows whether there was actually enough liquidity to trade size at a given time.

## What This Is

This is a read-only data capture tool.

It collects:

- current YES and NO bid books
- market metadata
- series/category metadata
- gap logs
- run summaries

It does not:

- place trades
- cancel orders
- manage a portfolio
- implement a strategy
- run a backtest
- recreate order books from before the collector was running

## Why Order Book Data Matters

Price history can answer:

```text
Did the market move from 40c to 55c?
```

Order book history can answer:

```text
Could I actually buy size at 40c?
How much slippage would I have taken?
Was the spread tradable?
How much depth was available?
```

This matters for realistic backtesting, especially for sizing, liquidity filters, spread-aware execution, and passive order assumptions.

## Current Status

Implemented:

- Kalshi RSA-PSS authentication
- production/demo REST environment support
- local `.env` loading
- market discovery by ticker, series, or category
- automatic selection of open markets currently returning order book rows
- series/category metadata export
- batch order book polling with up to 100 tickers per request
- CSV output partitioned by category and UTC date
- gap logging
- graceful shutdown
- heartbeat logging
- duration-limited captures
- run summaries
- local ignored `exports/` directory for reviewing test CSVs
- offline validation script
- capture inspection script
- derived bid/ask export script
- spread/depth reporting script
- v1 runbook for short and long captures

## Install

Use Python 3.11+.

```bash
python -m pip install -r requirements.txt
```

No extra packages are needed beyond `requirements.txt`.

## Credentials

Create a local `.env` file in the project root:

```bash
KALSHI_KEY_ID=your-api-key-id
KALSHI_PRIVATE_KEY_PATH=/path/to/kalshi-private-key.key
```

Keep the private key file outside this repository. Do not paste the private key into chat. Do not commit `.env`.

`.env` is ignored by Git.

## Quick Safety Check

Run this first. It only calls read-only endpoints.

```bash
python -m kalshi_capture.main --env prod --dry-run
```

This checks that authentication and signing work.

## One-Shot Capture

Run one read-only order book capture cycle:

```bash
python -m kalshi_capture.main \
  --env prod \
  --tickers MARKET-TICKER \
  --output-dir exports/smoke_one_ticker \
  --once
```

Inspect the result:

```bash
python scripts/inspect_capture.py exports/smoke_one_ticker
```

## Choosing Tickers

For targeted tests, copy the market ticker from Kalshi and pass it with `--tickers`.

Use a comma-separated list for multiple markets:

```bash
python -m kalshi_capture.main \
  --env prod \
  --tickers TICKER1,TICKER2,TICKER3 \
  --output-dir exports/my_test \
  --once
```

Good test tickers usually have visible bid/ask activity on the Kalshi market page. Markets with no resting book depth are still valid, but they will produce metadata, gap logs, and run summaries without order book rows.

Recommended workflow:

1. Start with one ticker and `--once`.
2. Inspect the output with `scripts/inspect_capture.py`.
3. If rows are zero, choose a more active market or add several tickers.
4. Move to `--duration-seconds` only after a one-shot capture writes rows.

For broader collection, use `--series` or `--categories`, but explicit `--tickers` is the easiest and safest way to test a market you personally care about.

You can also let the tool pick currently active markets by scanning open markets and choosing tickers whose order books return rows:

```bash
python -m kalshi_capture.main \
  --env prod \
  --select-liquid 5 \
  --output-dir exports/liquid_smoke \
  --once
```

Optional selector filters:

- `--liquid-scan-pages 5`: number of open-market pages to scan
- `--min-orderbook-rows 1`: minimum returned book rows per selected ticker
- `--min-top-level-size 0`: minimum combined best-level size across YES and NO bids
- `--selector-categories Sports,Financials`: only select markets from these categories
- `--selector-exclude-categories Exotics`: skip these categories during selection
- `--min-close-hours 6`: only select markets closing at least this many hours from now
- `--min-volume 100`: only select markets with at least this reported volume, when available
- `--min-open-interest 100`: only select markets with at least this reported open interest, when available

Example filtered selector run:

```bash
python -m kalshi_capture.main \
  --env prod \
  --select-liquid 10 \
  --selector-categories Sports \
  --min-close-hours 6 \
  --min-top-level-size 100 \
  --output-dir exports/sports_liquid \
  --once
```

## Short Timed Capture

Run a short capture for review:

```bash
python -m kalshi_capture.main \
  --env prod \
  --tickers MARKET-TICKER-1,MARKET-TICKER-2 \
  --output-dir exports/short_capture \
  --interval 2.0 \
  --duration-seconds 120
```

Generated files under `exports/` are ignored by Git so you can inspect CSVs locally without committing captured data.

## V1 Workflow

The complete v1 runbook is in `docs/v1_runbook.md`.

Recommended sequence:

1. Run `python scripts/offline_checks.py`.
2. Run `python -m kalshi_capture.main --env prod --dry-run`.
3. Run a one-shot selector capture with `--once`.
4. Inspect it with `scripts/inspect_capture.py`.
5. Run a short timed capture.
6. Derive bid/ask rows with `scripts/derive_bid_ask.py`.
7. Report spread/depth metrics with `scripts/spread_depth_report.py`.
8. Start longer captures only after the short capture writes usable rows.

Recommended starting defaults:

- `--interval 2.0`
- `--select-liquid 10` to `20`
- `--liquid-scan-pages 5`
- `--min-close-hours 2` for short tests, `6` or more for longer captures
- `--min-top-level-size 1` for broad capture, higher for stricter liquidity
- `--max-levels 0` to store all returned levels

Use a unique output directory per run, such as `exports/captures/<UTC_RUN_ID>_<description>/`.

## Troubleshooting

- `KALSHI_KEY_ID is required`: create `.env` or export the environment variable.
- `KALSHI_PRIVATE_KEY_PATH is required`: set the private key path and keep the key outside this repository.
- Auth failures: check key ID, private key pairing, `prod` vs `demo`, and machine clock accuracy.
- Zero rows: selected markets had no visible depth; use `--select-liquid`, broaden filters, or choose more active tickers.
- Missing tickers: inspect `gaps.csv`, retry with fewer tickers, or use fresher selector results.
- Rate limits: increase `--interval`, reduce `--select-liquid`, or narrow discovery.
- Large category crawls: use `--selector-categories` for selection only; use `--categories` only when full category discovery is intended.
- No spread metrics: both bid and ask must exist for the same outcome and snapshot; one-sided books still produce depth metrics.

## Output Layout

```text
exports/short_capture/
  orderbooks/
    MARKET-TICKER-1.csv
    MARKET-TICKER-2.csv
  metadata/
    markets.csv
    series.csv
  gaps.csv
  run_summary.json
```

Each ticker gets its own CSV under `orderbooks/`. Category is stored in `metadata/series.csv`, not in every order book row.

## Raw Order Book CSV

Raw rows store exactly the bid books Kalshi returns.

```text
capture_ts_ms,ticker,side,level,price,size,snapshot_id
```

Columns:

- `capture_ts_ms`: local capture timestamp in milliseconds since epoch
- `ticker`: Kalshi market ticker
- `side`: `yes` or `no` bid side
- `level`: depth level, where `0` is best bid for that side
- `price`: fixed units where `10000` equals `$1.0000`
- `size`: fixed count units where `100` equals `1` contract
- `snapshot_id`: grouping key for one ticker's captured book at one timestamp

Price examples:

```text
1500 = $0.1500
9030 = $0.9030
10000 = $1.0000
```

Size examples:

```text
100 = 1 contract
10000 = 100 contracts
18914 = 189.14 contracts
```

Kalshi REST order books return YES bids and NO bids only. They do not return explicit asks. In binary markets, the opposite side implies asks.

Example:

```text
NO bid 9370 implies YES ask 630
```

because:

```text
10000 - 9370 = 630
```

## Derived Bid/Ask CSV

For backtesting, create a derived bid/ask view:

```bash
python scripts/derive_bid_ask.py exports/short_capture exports/short_capture_derived
```

Derived rows contain:

```text
capture_ts_ms,snapshot_id,ticker,outcome,book_side,level,price,size
```

Derivation rules:

```text
YES bid -> YES bid and NO ask at 10000 - price
NO bid  -> NO bid and YES ask at 10000 - price
```

## Spread And Depth Report

After creating derived bid/ask rows, summarize tradability by ticker and outcome:

```bash
python scripts/spread_depth_report.py \
  exports/short_capture_derived \
  --output-csv exports/short_capture_spread_depth.csv
```

The report includes:

- snapshot count
- spread snapshot count
- min/average/max spread
- average best bid and best ask
- average top-level bid and ask size
- average total bid and ask depth

## Inspect A Capture

```bash
python scripts/inspect_capture.py exports/short_capture
```

The inspector reports:

- order book file count
- row count
- unique tickers
- categories
- dates
- first/last capture timestamps
- snapshot count
- total depth size
- top-level depth size
- gap event counts
- run summary values
- basic spread metrics when both YES and NO best bids are present

## Offline Checks

Run checks that do not call Kalshi:

```bash
python scripts/offline_checks.py
```

## Important Files

- `kalshi_capture/main.py`: CLI entry point
- `kalshi_capture/client.py`: signed REST client
- `kalshi_capture/discovery.py`: market and series discovery
- `kalshi_capture/orderbook.py`: order book polling and flattening
- `kalshi_capture/capture.py`: capture loop
- `kalshi_capture/storage.py`: CSV writers
- `scripts/inspect_capture.py`: local output inspection
- `scripts/derive_bid_ask.py`: raw-to-derived bid/ask conversion
- `scripts/spread_depth_report.py`: derived bid/ask spread and depth reporting
- `docs/v1_runbook.md`: recommended v1 workflow, long-run notes, and troubleshooting
- `AGENTS.md`: implementation context for coding agents
