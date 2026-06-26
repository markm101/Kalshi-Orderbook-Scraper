# Kalshi Order Book Dataset Capture

This project captures live Kalshi order book snapshots to build a historical dataset for strategy research and backtesting.

Kalshi does not provide historical full-depth order books through its public API. The only reliable way to get historical depth is to collect the current order book continuously going forward.

## Scope

This is a data ingestion project only.

It does not:

- place trades
- manage orders
- implement strategies
- run backtests
- reconstruct order book history from before capture started

## Planned Capture Method

The collector will use Kalshi's REST API to bulk-poll current order books.

For many tickers, it will prefer:

```text
GET /markets/orderbooks?tickers=TICKER1&tickers=TICKER2
```

instead of one request per market. The batch endpoint supports up to 100 tickers per request, which reduces rate-limit risk and improves timestamp consistency.

## Data Layout

Output will be CSV, partitioned by category and UTC date.

```text
data/
  orderbooks/
    category=Sports/
      date=2026-06-26/
        orderbook.csv
    category=Weather/
      date=2026-06-26/
        orderbook.csv
    category=Politics/
      date=2026-06-26/
        orderbook.csv
  metadata/
    markets.csv
    series.csv
  gaps.csv
```

Category is stored in the directory path, not in each order book row.

## Order Book Schema

Each order book CSV contains:

```text
capture_ts_ms,ticker,side,level,price,size
```

Columns:

- `capture_ts_ms`: local capture timestamp in milliseconds since epoch
- `ticker`: Kalshi market ticker
- `side`: `yes` or `no` bid side
- `level`: 0 is the best bid for that side
- `price`: price in cents
- `size`: resting contracts at that level

Kalshi REST order books return YES bids and NO bids only. Explicit asks are not returned because binary market asks can be derived from the opposite side's bids.

## Metadata

Market metadata will be stored separately:

```text
data/metadata/markets.csv
```

Series metadata will be stored separately:

```text
data/metadata/series.csv
```

Series metadata contains the category mapping used to write order books into category directories.

## Gap Log

Capture failures are recorded in:

```text
data/gaps.csv
```

This file is important for backtesting because failed polls create unrecoverable holes in the order book history.

## Kalshi Environments

Demo REST API:

```text
https://external-api.demo.kalshi.co/trade-api/v2
```

Production REST API:

```text
https://external-api.kalshi.com/trade-api/v2
```

Initial testing should use demo.

## Authentication

The collector will use Kalshi API-key authentication with RSA-PSS signing.

Required environment variables:

```text
KALSHI_KEY_ID
KALSHI_PRIVATE_KEY_PATH
```

Important signing detail: Kalshi currently requires signing the API path without query parameters.

## Example Planned Usage

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Authenticated demo smoke test:

```bash
export KALSHI_KEY_ID="your-api-key-id"
export KALSHI_PRIVATE_KEY_PATH="/path/to/kalshi-private-key.key"

python -m kalshi_capture.main --env demo --dry-run
```

Discover open markets for a series and write metadata CSVs:

```bash
python -m kalshi_capture.main \
  --env demo \
  --series KXHIGHNY \
  --output-dir data \
  --discover-only
```

```bash
python -m kalshi_capture.main \
  --env demo \
  --categories Sports,Weather \
  --interval 2.0 \
  --output-dir data
```

```bash
python -m kalshi_capture.main \
  --env demo \
  --series KXHIGHNY,KXNBA \
  --interval 2.0 \
  --output-dir data
```

## More Detail

See `documentation.md` for the full implementation plan, verified API details, schemas, and operational requirements.
