# Demo Commands

Run offline validation checks. This makes no Kalshi API calls.

```bash
python scripts/offline_checks.py
```

Check authentication and signing against read-only endpoints.

```bash
python -m kalshi_capture.main --env prod --dry-run
```

Capture one known ticker once.

```bash
python -m kalshi_capture.main \
  --env prod \
  --tickers MARKET-TICKER \
  --output-dir exports/demo_one_ticker \
  --once
```

Inspect a capture output directory.

```bash
python scripts/inspect_capture.py exports/demo_one_ticker
```

Auto-select active/liquid markets and capture one snapshot.

```bash
python -m kalshi_capture.main \
  --env prod \
  --select-liquid 5 \
  --min-close-hours 6 \
  --min-top-level-size 100 \
  --output-dir exports/demo_liquid_once \
  --once
```

Auto-select liquid markets from one category.

```bash
python -m kalshi_capture.main \
  --env prod \
  --select-liquid 5 \
  --selector-categories Crypto \
  --min-close-hours 6 \
  --min-top-level-size 100 \
  --output-dir exports/demo_crypto_once \
  --once
```

Run a short timed capture.

```bash
python -m kalshi_capture.main \
  --env prod \
  --select-liquid 10 \
  --min-close-hours 6 \
  --min-top-level-size 100 \
  --output-dir exports/demo_short_capture \
  --interval 2.0 \
  --duration-seconds 120
```

Review the automatic spread/depth report created by capture.

```bash
python scripts/spread_depth_report.py exports/demo_short_capture --limit 20
```

Review the latest captured spread for each ticker.

```bash
python scripts/latest_spread_report.py exports/demo_short_capture --limit 20
```

Regenerate the latest-spread report CSV manually.

```bash
python scripts/latest_spread_report.py \
  exports/demo_short_capture \
  --output-csv exports/demo_short_capture/latest_spread.csv
```

Regenerate the spread/depth report CSV manually.

```bash
python scripts/spread_depth_report.py \
  exports/demo_short_capture \
  --output-csv exports/demo_short_capture/spread_depth.csv
```

Filter the spread/depth report to one outcome.

```bash
python scripts/spread_depth_report.py \
  exports/demo_short_capture \
  --outcomes yes \
  --limit 20
```

Optionally convert a raw YES/NO bid capture to a derived bid/ask view.

```bash
python scripts/derive_bid_ask.py \
  exports/demo_short_capture \
  exports/demo_short_capture_bid_ask
```

Compile all Python files.

```bash
python -m compileall kalshi_capture scripts
```
