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
    series: tuple[str, ...]
    categories: tuple[str, ...]
    exclude_categories: tuple[str, ...]
    interval: float
    output_dir: Path
    max_levels: int
    dry_run: bool
    discover_only: bool
    heartbeat_seconds: int
    discovery_refresh_seconds: int
    log_level: str


def parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture Kalshi order book snapshots.")
    parser.add_argument("--env", choices=("demo", "prod"), default="demo")
    parser.add_argument("--tickers", default="", help="Comma-separated market tickers")
    parser.add_argument("--series", default="", help="Comma-separated series tickers")
    parser.add_argument("--categories", default="", help="Comma-separated series categories")
    parser.add_argument("--exclude-categories", default="", help="Comma-separated categories to skip")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval in seconds")
    parser.add_argument("--output-dir", default="data", help="Output directory")
    parser.add_argument("--max-levels", type=int, default=0, help="0 means all levels")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and log without writing data")
    parser.add_argument("--discover-only", action="store_true", help="Write metadata and exit")
    parser.add_argument("--heartbeat-seconds", type=int, default=300)
    parser.add_argument("--discovery-refresh-seconds", type=int, default=900)
    parser.add_argument("--log-level", default="INFO")
    return parser


def load_config(argv: list[str] | None = None) -> Config:
    args = build_parser().parse_args(argv)
    key_id = os.environ.get("KALSHI_KEY_ID", "").strip()
    private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip()

    if not key_id:
        raise SystemExit("KALSHI_KEY_ID is required")
    if not private_key_path:
        raise SystemExit("KALSHI_PRIVATE_KEY_PATH is required")
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than 0")
    if args.max_levels < 0:
        raise SystemExit("--max-levels must be 0 or greater")

    return Config(
        env=args.env,
        base_url=REST_BASE_URLS[args.env],
        key_id=key_id,
        private_key_path=Path(private_key_path).expanduser(),
        tickers=parse_csv(args.tickers),
        series=parse_csv(args.series),
        categories=parse_csv(args.categories),
        exclude_categories=parse_csv(args.exclude_categories),
        interval=args.interval,
        output_dir=Path(args.output_dir),
        max_levels=args.max_levels,
        dry_run=args.dry_run,
        discover_only=args.discover_only,
        heartbeat_seconds=args.heartbeat_seconds,
        discovery_refresh_seconds=args.discovery_refresh_seconds,
        log_level=args.log_level.upper(),
    )
