# Local Capture Exports

Use this directory for smoke-test and short-run CSV outputs that should be easy to inspect locally.

Example:

```bash
python -m kalshi_capture.main \
  --env prod \
  --tickers MARKET-TICKER \
  --output-dir exports/smoke_one_ticker \
  --once
```

Inspect output:

```bash
python scripts/inspect_capture.py exports/smoke_one_ticker
```

Generated export contents are ignored by Git. Only this README is tracked.
