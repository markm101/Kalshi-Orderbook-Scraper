# Agent Context

This file is for coding agents working on this repository. Keep it concise, factual, and implementation-focused. The human-facing overview belongs in `README.md`.

## Project Goal

Build a read-only Kalshi order book capture tool that accumulates live order book snapshots for future strategy research and backtesting.

Kalshi provides price history, trades, and candles, but not historical full-depth order books through the public REST API. Full-depth order book history must be captured going forward while this tool is running.

Out of scope:

- trading
- order placement
- order cancellation
- portfolio management
- strategy logic
- backtest engine
- reconstructing order books from before capture began

## Current Implementation

Package layout:

```text
kalshi_capture/
  __init__.py
  auth.py
  capture.py
  client.py
  config.py
  discovery.py
  gaps.py
  main.py
  orderbook.py
  selector.py
  storage.py
```

Scripts:

```text
scripts/offline_checks.py
scripts/inspect_capture.py
scripts/derive_bid_ask.py
scripts/spread_depth_report.py
```

Implemented behavior:

- RSA-PSS auth signing
- production/demo REST base URL selection
- `.env` loading from project root
- read-only dry-run mode
- market discovery by tickers, series, categories
- automatic liquid-market selection with `--select-liquid`, category filters, close-time filters, and volume/open-interest filters
- series/category metadata enrichment
- batch orderbook polling through `/markets/orderbooks`
- CSV storage by `category=<Category>/date=<YYYY-MM-DD>/orderbook.csv`
- metadata CSVs
- gap logging
- run summary JSON
- heartbeat logs
- graceful SIGINT/SIGTERM handling
- `--once` one-cycle capture
- `--duration-seconds` timed capture
- derived bid/ask export
- spread/depth reporting for derived bid/ask output
- standard-library inspection and offline checks

## Kalshi API Facts

Verified against docs/specs on 2026-06-26.

REST base URLs:

```text
prod: https://external-api.kalshi.com/trade-api/v2
demo: https://external-api.demo.kalshi.co/trade-api/v2
```

WebSocket URLs, future phase only:

```text
prod: wss://external-api-ws.kalshi.com/trade-api/ws/v2
demo: wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2
```

Auth headers:

```text
KALSHI-ACCESS-KEY
KALSHI-ACCESS-SIGNATURE
KALSHI-ACCESS-TIMESTAMP
```

Signing message:

```text
timestamp_ms + HTTP_METHOD + request_path_without_query_params
```

Important: sign the full API path from root without query parameters. Example URL:

```text
https://external-api.kalshi.com/trade-api/v2/markets?status=open
```

signs:

```text
/trade-api/v2/markets
```

Order book endpoints:

```text
GET /markets/{ticker}/orderbook
GET /markets/orderbooks?tickers=T1&tickers=T2
```

The batch endpoint accepts up to 100 repeated `tickers` params.

REST orderbooks return bid books only:

```json
{
  "orderbook_fp": {
    "yes_dollars": [["0.1500", "100.00"]],
    "no_dollars": [["0.8500", "50.00"]]
  }
}
```

Batch shape:

```json
{
  "orderbooks": [
    {
      "ticker": "MARKET-TICKER",
      "orderbook_fp": {
        "yes_dollars": [["0.1500", "100.00"]],
        "no_dollars": [["0.8500", "50.00"]]
      }
    }
  ]
}
```

## Raw Data Schema

Raw orderbook rows:

```text
capture_ts_ms,ticker,side,level,price,size,snapshot_id
```

Rules:

- `side` is `yes` or `no`, meaning Kalshi bid side.
- `level=0` is best bid for that side.
- `price` is fixed units where `10000 = $1.0000`.
- `size` is integer contracts from fixed-point count strings.
- `snapshot_id = capture_ts_ms:ticker`.
- Category is not stored in raw rows. It is encoded in the directory path and stored in `metadata/series.csv`.

Flattening example:

```json
["0.1500", "100.00"]
```

becomes:

```text
price=1500,size=100
```

Use `Decimal`, never binary float arithmetic.

## Derived Bid/Ask Schema

Derived rows from `scripts/derive_bid_ask.py`:

```text
capture_ts_ms,snapshot_id,ticker,outcome,book_side,level,price,size
```

Rules:

```text
YES bid -> YES bid and NO ask at 10000 - price
NO bid  -> NO bid and YES ask at 10000 - price
```

Raw capture remains the source of truth. Derived bid/ask is for analysis/backtesting convenience.

## Output Layout

Capture output:

```text
<output-dir>/
  orderbooks/
    category=<Category>/
      date=<YYYY-MM-DD>/
        orderbook.csv
  metadata/
    markets.csv
    series.csv
  gaps.csv
  run_summary.json
```

Use UTC dates.

Generated data should usually be written under `exports/` during development. `exports/*` is ignored except `exports/README.md`.

## Operational Rules

- Do not add trading code.
- Do not call portfolio/order placement endpoints.
- Do not read, print, copy, or inspect private key files.
- Using the private key path for approved authentication tests is allowed.
- Prefer read-only smoke tests before longer captures.
- Keep captured CSV exports out of Git.
- Do not install external packages unless explicitly needed and approved.
- Use standard library for scripts when feasible.

## Useful Commands

Offline checks, no API calls:

```bash
python scripts/offline_checks.py
```

Auth smoke test, read-only:

```bash
python -m kalshi_capture.main --env prod --dry-run
```

One capture cycle:

```bash
python -m kalshi_capture.main --env prod --tickers MARKET-TICKER --output-dir exports/smoke --once
```

Auto-select currently active/liquid markets:

```bash
python -m kalshi_capture.main --env prod --select-liquid 5 --output-dir exports/liquid_smoke --once
```

Filtered auto-selection:

```bash
python -m kalshi_capture.main --env prod --select-liquid 10 --selector-categories Sports --min-close-hours 6 --min-top-level-size 100 --output-dir exports/sports_liquid --once
```

Timed capture:

```bash
python -m kalshi_capture.main --env prod --tickers T1,T2 --output-dir exports/short_capture --interval 2.0 --duration-seconds 120
```

Inspect output:

```bash
python scripts/inspect_capture.py exports/short_capture
```

Create derived bid/ask rows:

```bash
python scripts/derive_bid_ask.py exports/short_capture exports/short_capture_derived
```

Report spread/depth metrics:

```bash
python scripts/spread_depth_report.py exports/short_capture_derived --output-csv exports/short_capture_spread_depth.csv
```

## Git Hygiene

Ignored local files/directories include:

```text
.env
.env.*
*.key
*key.txt
checkins/
exports/* except exports/README.md
__pycache__/
*.py[cod]
```

Before committing, check:

```bash
git status --short
git diff --stat
```

Do not commit secrets or generated capture exports.

## Recommended Next Work

High-value next tasks:

1. Add long-run deployment notes for `launchd`, `systemd`, or Docker.
2. Consider WebSocket capture only if REST polling resolution is insufficient.
