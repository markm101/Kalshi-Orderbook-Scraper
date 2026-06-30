# V1 Runbook

This runbook is the recommended v1 workflow for collecting Kalshi order book data and preparing it for backtesting research.

The tool is read-only. It captures market data only.

## Recommended Flow

1. Run offline checks.
2. Run an auth smoke test.
3. Run a one-shot selector capture.
4. Inspect the one-shot output.
5. Run a short timed capture.
6. Inspect the short capture.
7. Run the spread/depth report.
8. Start a longer capture only after the short capture writes usable rows.

## Preflight

Run checks that do not call Kalshi:

```bash
python scripts/offline_checks.py
```

Verify imports and syntax:

```bash
python -m compileall kalshi_capture scripts
```

Run a read-only auth check:

```bash
python -m kalshi_capture.main --env prod --dry-run
```

Verify the machine clock before long captures:

```bash
date -u
```

## One-Shot Capture

Use the selector to find active markets with visible order book depth:

```bash
python -m kalshi_capture.main \
  --env prod \
  --select-liquid 5 \
  --selector-categories Exotics \
  --min-close-hours 1 \
  --min-top-level-size 1 \
  --output-dir exports/v1_smoke \
  --once
```

Inspect it:

```bash
python scripts/inspect_capture.py exports/v1_smoke
```

Good smoke-test signs:

- `rows` is greater than `0`
- `errors` is `0`
- `missing_tickers` is `0`
- `zero_row_batches` is `0`
- gap events are only `startup` and `shutdown`

## Short Timed Capture

Run a 5-minute capture before attempting anything longer:

```bash
python -m kalshi_capture.main \
  --env prod \
  --select-liquid 10 \
  --selector-categories Exotics \
  --min-close-hours 2 \
  --min-top-level-size 1 \
  --output-dir exports/v1_short_capture \
  --interval 2.0 \
  --duration-seconds 300
```

Inspect it:

```bash
python scripts/inspect_capture.py exports/v1_short_capture
```

Capture updates `latest_spread.csv` after every polling cycle and writes `spread_depth.csv` automatically at shutdown.

Use `latest_spread.csv` while a run is active to inspect the newest captured spread per ticker:

```bash
python scripts/latest_spread_report.py exports/v1_short_capture --limit 20
```

To regenerate it manually:

```bash
python scripts/latest_spread_report.py \
  exports/v1_short_capture \
  --output-csv exports/v1_short_capture/latest_spread.csv
```

Use `spread_depth.csv` for historical summary stats across all captured snapshots. To regenerate it manually:

```bash
python scripts/spread_depth_report.py \
  exports/v1_short_capture \
  --output-csv exports/v1_short_capture_spread_depth.csv
```

## Longer Capture

Use a unique output directory per longer run. Do not reuse the same output directory unless you intentionally want files, `run_summary.json`, and `spread_depth.csv` to be updated in place.

Example 2-hour run:

```bash
python -m kalshi_capture.main \
  --env prod \
  --select-liquid 20 \
  --selector-categories Exotics \
  --min-close-hours 6 \
  --min-top-level-size 1 \
  --output-dir exports/captures/$(date -u +%Y%m%dT%H%M%SZ)_exotics_2h \
  --interval 2.0 \
  --duration-seconds 7200
```

For an open-ended run, omit `--duration-seconds` and stop with `Ctrl-C` or a normal `SIGTERM`:

```bash
python -m kalshi_capture.main \
  --env prod \
  --select-liquid 20 \
  --selector-categories Exotics \
  --min-close-hours 6 \
  --min-top-level-size 1 \
  --output-dir exports/captures/$(date -u +%Y%m%dT%H%M%SZ)_exotics_open \
  --interval 2.0
```

## Operational Defaults

Recommended starting defaults for v1:

```text
interval: 2.0 seconds
select-liquid: 10 to 20 markets
liquid-scan-pages: 5
min-close-hours: 2 for short tests, 6+ for longer captures
min-top-level-size: 1 for broad capture, higher for stricter liquidity
max-levels: 0, meaning all levels
heartbeat-seconds: 300
discovery-refresh-seconds: 900
```

The selector scans a candidate pool and ranks the markets it finds by reported volume, open interest, visible top-level depth, and book rows. It returns up to the requested count while keeping one market per parent event, so one event ladder does not fill the whole selection. Category selection uses `--liquid-scan-pages` as a search-depth knob across matching series, not as an instruction to stop at the first markets with visible rows.

If rows are sparse, lower category restrictions or use a broader selector. If rate limits appear, reduce selected markets or increase `--interval`.

## Output Naming

Use one output directory per run:

```text
exports/captures/<UTC_RUN_ID>_<description>/
```

Example:

```text
exports/captures/20260626T180000Z_exotics_2h/
```

Keep generated captures under `exports/` during development. `exports/*` is ignored by Git except `exports/README.md`.

## Launchd Example

For macOS, create a local plist outside the repository, such as `~/Library/LaunchAgents/com.local.kalshi-capture.plist`.

Replace paths before use:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.kalshi-capture</string>
  <key>WorkingDirectory</key>
  <string>/Users/mark/Documents/GitHub/quant/kalshi_backtesting_set</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>kalshi_capture.main</string>
    <string>--env</string>
    <string>prod</string>
    <string>--select-liquid</string>
    <string>20</string>
    <string>--selector-categories</string>
    <string>Exotics</string>
    <string>--min-close-hours</string>
    <string>6</string>
    <string>--min-top-level-size</string>
    <string>1</string>
    <string>--output-dir</string>
    <string>exports/captures/launchd_exotics</string>
    <string>--interval</string>
    <string>2.0</string>
  </array>
  <key>StandardOutPath</key>
  <string>/tmp/kalshi-capture.out.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/kalshi-capture.err.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
```

Load and start manually:

```bash
launchctl load ~/Library/LaunchAgents/com.local.kalshi-capture.plist
launchctl start com.local.kalshi-capture
```

Stop it:

```bash
launchctl stop com.local.kalshi-capture
```

## Systemd Example

For Linux, create a service outside the repository, such as `/etc/systemd/system/kalshi-capture.service`.

Replace paths and user before use:

```ini
[Unit]
Description=Kalshi order book capture
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mark
WorkingDirectory=/home/mark/kalshi_backtesting_set
Environment=KALSHI_KEY_ID=your-api-key-id
Environment=KALSHI_PRIVATE_KEY_PATH=/home/mark/keys/kalshi-private-key.key
ExecStart=/usr/bin/python3 -m kalshi_capture.main --env prod --select-liquid 20 --selector-categories Exotics --min-close-hours 6 --min-top-level-size 1 --output-dir exports/captures/systemd_exotics --interval 2.0
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Start it:

```bash
sudo systemctl daemon-reload
sudo systemctl start kalshi-capture
```

Inspect status and logs:

```bash
sudo systemctl status kalshi-capture
journalctl -u kalshi-capture -f
```

Stop it:

```bash
sudo systemctl stop kalshi-capture
```

## Docker Note

Docker is optional for v1. The current workflow does not require a Dockerfile.

If Docker is added later, mount credentials read-only and mount an output directory separately. Do not bake `.env`, private keys, or generated capture data into an image.

## Troubleshooting

### `KALSHI_KEY_ID is required`

Create `.env` in the project root or export the environment variable in the shell running the command.

### `KALSHI_PRIVATE_KEY_PATH is required`

Set the private key path in `.env` or the shell. Keep the key file outside this repository.

### Auth Fails

Check that the key ID matches the private key, the environment is correct (`prod` vs `demo`), and the machine clock is accurate.

### Zero Rows

The request succeeded, but selected markets had no visible book depth. Use `--select-liquid`, increase `--liquid-scan-pages`, lower overly strict filters, or choose more active tickers.

### Missing Tickers

The batch response omitted one or more requested tickers. Inspect `gaps.csv`, then retry with fewer tickers or a different selection.

### Rate Limits

Increase `--interval`, reduce `--select-liquid`, or reduce discovery breadth. Avoid broad category captures until a short selector capture works.

### Large Category Crawls

Use `--selector-categories` for selector filtering. Use `--categories` only when you intentionally want to discover and capture markets from full categories.

### No Spread Metrics

Spread metrics require both bid and ask for the same outcome in the same snapshot. One-sided books still produce useful depth metrics.

### Size Units

Captured `size` values are fixed count units where `100 = 1 contract`. This preserves fractional API sizes such as `189.14` contracts as `18914`.

## V1 Done Criteria

V1 is ready when these pass:

```bash
python scripts/offline_checks.py
python -m compileall kalshi_capture scripts
python -m kalshi_capture.main --env prod --dry-run
python -m kalshi_capture.main --env prod --select-liquid 5 --min-top-level-size 1 --output-dir exports/v1_smoke --once
python scripts/inspect_capture.py exports/v1_smoke
python scripts/spread_depth_report.py exports/v1_smoke --output-csv exports/v1_smoke_spread_depth.csv
```

For final confidence, run a 30- to 120-minute timed capture and inspect the result before relying on the data for backtesting research.
