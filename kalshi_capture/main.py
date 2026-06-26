from __future__ import annotations

import logging
import signal
from typing import Any

from kalshi_capture.auth import load_private_key
from kalshi_capture.capture import run_capture
from kalshi_capture.client import KalshiClient
from kalshi_capture.config import Config, load_config
from kalshi_capture.discovery import discover_markets
from kalshi_capture.storage import write_metadata


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


def discover_only(config: Config) -> None:
    private_key = load_private_key(config.private_key_path)
    with KalshiClient(config.base_url, config.key_id, private_key) as client:
        discovery = discover_markets(
            client,
            tickers=config.tickers,
            series=config.series,
            categories=config.categories,
            exclude_categories=config.exclude_categories,
        )

    write_metadata(config.output_dir, discovery)
    logging.info(
        "wrote metadata markets=%s series=%s output_dir=%s",
        len(discovery.markets),
        len(discovery.series),
        config.output_dir,
    )


def install_signal_handlers() -> dict[str, bool]:
    state = {"stop": False}

    def request_stop(signum: int, _frame: object) -> None:
        logging.info("received signal=%s; stopping after current cycle", signum)
        state["stop"] = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return state


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    configure_logging(config.log_level)

    if config.dry_run:
        dry_run(config)
        return 0

    if config.discover_only:
        discover_only(config)
        return 0

    signal_state = install_signal_handlers()
    private_key = load_private_key(config.private_key_path)
    with KalshiClient(config.base_url, config.key_id, private_key) as client:
        run_capture(config, client, stop_requested=lambda: signal_state["stop"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
