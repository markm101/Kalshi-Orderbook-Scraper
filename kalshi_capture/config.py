from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path


REST_BASE_URLS = {
    "demo": "https://external-api.demo.kalshi.co/trade-api/v2",
    "prod": "https://external-api.kalshi.com/trade-api/v2",
}


@dataclass(frozen=True)
class Config:
    env: str
    base_url: str
    key_id: str
    private_key_path: Path
    tickers: tuple[str, ...]
    select_liquid: int
    liquid_scan_pages: int
    min_orderbook_rows: int
    min_top_level_size: int
    selector_categories: tuple[str, ...]
    selector_exclude_categories: tuple[str, ...]
    min_close_hours: float
    min_volume: int
    min_open_interest: int
    series: tuple[str, ...]
    categories: tuple[str, ...]
    exclude_categories: tuple[str, ...]
    interval: float
    output_dir: Path
    max_levels: int
    dry_run: bool
    discover_only: bool
    once: bool
    duration_seconds: float
    heartbeat_seconds: int
    discovery_refresh_seconds: int
    log_level: str


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture Kalshi order book snapshots.")
    parser.add_argument("--env", choices=("demo", "prod"), default="demo")
    parser.add_argument("--tickers", default="", help="Comma-separated market tickers")
    parser.add_argument("--select-liquid", type=int, default=0, help="Auto-select this many open markets currently returning orderbook rows")
    parser.add_argument("--liquid-scan-pages", type=int, default=5, help="Open-market pages to scan for liquid selection")
    parser.add_argument("--min-orderbook-rows", type=int, default=1, help="Minimum orderbook rows required for liquid selection")
    parser.add_argument("--min-top-level-size", type=int, default=0, help="Minimum combined level-0 size required for liquid selection")
    parser.add_argument("--selector-categories", default="", help="Comma-separated categories for liquid selection only")
    parser.add_argument("--selector-exclude-categories", default="", help="Comma-separated categories to skip during liquid selection only")
    parser.add_argument("--min-close-hours", type=float, default=0.0, help="Minimum hours before close for liquid selection")
    parser.add_argument("--min-volume", type=int, default=0, help="Minimum market volume for liquid selection when available")
    parser.add_argument("--min-open-interest", type=int, default=0, help="Minimum open interest for liquid selection when available")
    parser.add_argument("--series", default="", help="Comma-separated series tickers")
    parser.add_argument("--categories", default="", help="Comma-separated series categories")
    parser.add_argument("--exclude-categories", default="", help="Comma-separated categories to skip")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval in seconds")
    parser.add_argument("--output-dir", default="data", help="Output directory")
    parser.add_argument("--max-levels", type=int, default=0, help="0 means all levels")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and log without writing data")
    parser.add_argument("--discover-only", action="store_true", help="Write metadata and exit")
    parser.add_argument("--once", action="store_true", help="Run one capture cycle and exit")
    parser.add_argument("--duration-seconds", type=float, default=0.0, help="Stop capture after this many seconds")
    parser.add_argument("--heartbeat-seconds", type=int, default=300)
    parser.add_argument("--discovery-refresh-seconds", type=int, default=900)
    parser.add_argument("--log-level", default="INFO")
    return parser


def load_config(argv: list[str] | None = None) -> Config:
    args = build_parser().parse_args(argv)
    env_file = read_env_file(Path(".env"))
    key_id = os.environ.get("KALSHI_KEY_ID", env_file.get("KALSHI_KEY_ID", "")).strip()
    private_key_path = os.environ.get(
        "KALSHI_PRIVATE_KEY_PATH",
        env_file.get("KALSHI_PRIVATE_KEY_PATH", ""),
    ).strip()

    if not key_id:
        raise SystemExit("KALSHI_KEY_ID is required")
    if not private_key_path:
        raise SystemExit("KALSHI_PRIVATE_KEY_PATH is required")
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than 0")
    if args.max_levels < 0:
        raise SystemExit("--max-levels must be 0 or greater")
    if args.select_liquid < 0:
        raise SystemExit("--select-liquid must be 0 or greater")
    if args.liquid_scan_pages <= 0:
        raise SystemExit("--liquid-scan-pages must be greater than 0")
    if args.min_orderbook_rows < 0:
        raise SystemExit("--min-orderbook-rows must be 0 or greater")
    if args.min_top_level_size < 0:
        raise SystemExit("--min-top-level-size must be 0 or greater")
    if args.min_close_hours < 0:
        raise SystemExit("--min-close-hours must be 0 or greater")
    if args.min_volume < 0:
        raise SystemExit("--min-volume must be 0 or greater")
    if args.min_open_interest < 0:
        raise SystemExit("--min-open-interest must be 0 or greater")
    if args.duration_seconds < 0:
        raise SystemExit("--duration-seconds must be 0 or greater")
    if args.heartbeat_seconds <= 0:
        raise SystemExit("--heartbeat-seconds must be greater than 0")
    if args.discovery_refresh_seconds <= 0:
        raise SystemExit("--discovery-refresh-seconds must be greater than 0")

    return Config(
        env=args.env,
        base_url=REST_BASE_URLS[args.env],
        key_id=key_id,
        private_key_path=Path(private_key_path).expanduser(),
        tickers=parse_csv(args.tickers),
        select_liquid=args.select_liquid,
        liquid_scan_pages=args.liquid_scan_pages,
        min_orderbook_rows=args.min_orderbook_rows,
        min_top_level_size=args.min_top_level_size,
        selector_categories=parse_csv(args.selector_categories),
        selector_exclude_categories=parse_csv(args.selector_exclude_categories),
        min_close_hours=args.min_close_hours,
        min_volume=args.min_volume,
        min_open_interest=args.min_open_interest,
        series=parse_csv(args.series),
        categories=parse_csv(args.categories),
        exclude_categories=parse_csv(args.exclude_categories),
        interval=args.interval,
        output_dir=Path(args.output_dir),
        max_levels=args.max_levels,
        dry_run=args.dry_run,
        discover_only=args.discover_only,
        once=args.once,
        duration_seconds=args.duration_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
        discovery_refresh_seconds=args.discovery_refresh_seconds,
        log_level=args.log_level.upper(),
    )
