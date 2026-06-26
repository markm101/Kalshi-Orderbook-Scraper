from __future__ import annotations

import logging
from typing import Any

from kalshi_capture.auth import load_private_key
from kalshi_capture.client import KalshiClient
from kalshi_capture.config import Config, load_config


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )


def dry_run(config: Config) -> None:
    private_key = load_private_key(config.private_key_path)
    with KalshiClient(config.base_url, config.key_id, private_key) as client:
        status = client.get("/exchange/status")
        logging.info("exchange_status=%s", status)

        markets = client.get("/markets", params={"status": "open", "limit": 5})
        market_items: list[dict[str, Any]] = markets.get("markets", [])
        logging.info("sample_open_markets=%s", [market.get("ticker") for market in market_items])


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    configure_logging(config.log_level)

    if config.dry_run:
        dry_run(config)
        return 0

    raise SystemExit("Only --dry-run is implemented in this first slice")


if __name__ == "__main__":
    raise SystemExit(main())
