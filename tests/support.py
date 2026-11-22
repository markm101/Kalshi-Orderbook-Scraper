from __future__ import annotations

import contextlib
import csv
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from functools import wraps
import json
import logging
import os
from pathlib import Path
import signal
import tempfile
import time
from typing import Any
import unittest
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx

from kalshi_capture import main
from kalshi_capture.capture import run_capture
from kalshi_capture.config import Config

BOOK = {"yes_dollars": [["0.4000", "10.00"]], "no_dollars": [["0.5500", "10.00"]]}
EMPTY_BOOK = {"yes_dollars": [], "no_dollars": []}


class ScenarioTimeout(Exception):
    pass


class CaptureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.output_dir = Path(temp_dir.name)


def known_bug(summary: str, error: type[Exception] = AssertionError) -> Callable:
    # expectedFailure would also accept a broken test, so only the recorded failure type is skipped.
    def decorate(test: Callable) -> Callable:
        @wraps(test)
        def wrapper(self: unittest.TestCase) -> None:
            try:
                test(self)
            except error:
                self.skipTest(f"known bug: {summary}")
            self.fail(f"fixed, so remove @known_bug: {summary}")

        return wrapper

    return decorate


def market(ticker: str, **fields: Any) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "event_ticker": f"S-{ticker}",
        "status": "active",
        "result": "",
        "close_time": "2999-01-01T00:00:00Z",
        **fields,
    }


def http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://exchange.invalid")
    return httpx.HTTPStatusError(str(status_code), request=request, response=httpx.Response(status_code, request=request))


class Exchange:
    """In-memory stand-in for the public Kalshi endpoints that capture uses."""

    def __init__(
        self,
        *markets: dict[str, Any],
        series: list[dict[str, Any]] | None = None,
        book: Callable[[str, int], dict[str, Any]] = lambda ticker, poll: BOOK,
        fail: Callable[[Exchange, str], None] = lambda exchange, path: None,
    ) -> None:
        self.markets = {item["ticker"]: dict(item) for item in markets}
        self.series = [{"ticker": "S", "category": "Sports"}] if series is None else series
        self.book = book
        self.fail = fail
        self.polls: Counter[str] = Counter()
        self.served: Counter[tuple[str, str]] = Counter()
        self.batch_sizes: list[int] = []

    def update(self, ticker: str, **fields: Any) -> None:
        self.markets[ticker].update(fields)

    def get(self, path: str, params: Any = None) -> dict[str, Any]:
        self.fail(self, path)
        if path == "/markets/orderbooks":
            tickers = [value for _, value in params]
            self.batch_sizes.append(len(tickers))
            self.polls.update(tickers)
            return {"orderbooks": [{"ticker": t, "orderbook_fp": self.book(t, self.polls[t])} for t in tickers]}
        if path == "/markets":
            return self._markets(dict(params or {}))
        if path == "/series":
            category = dict(params or {}).get("category")
            found = [s for s in self.series if category in (s.get("category"), *s.get("categories", ()))]
            # Kalshi returns null here rather than an empty list.
            return {"series": found or None}
        if path.startswith("/series/"):
            for item in self.series:
                if path == f"/series/{item['ticker']}":
                    return {"series": item}
        raise http_error(404)

    def _markets(self, params: dict[str, Any]) -> dict[str, Any]:
        if "tickers" in params:
            found = [dict(self.markets[t]) for t in params["tickers"].split(",") if t in self.markets]
            self.served.update((item["ticker"], item["status"]) for item in found)
            return {"markets": found, "cursor": ""}
        found = [dict(item) for item in self.markets.values() if item["status"] == "active"]
        if series := params.get("series_ticker"):
            found = [item for item in found if item["event_ticker"].startswith(f"{series}-")]
        start = int(params.get("cursor") or 0)
        end = start + int(params.get("limit", 100))
        return {"markets": found[start:end], "cursor": str(end) if end < len(found) else ""}


def capture_config(output_dir: Path, **changes: Any) -> Config:
    config = Config(
        env="demo",
        base_url="",
        key_id="",
        private_key_path=Path("unused.key"),
        tickers=(),
        select_liquid=0,
        liquid_scan_pages=5,
        min_orderbook_rows=1,
        min_top_level_size=0,
        selector_categories=(),
        selector_exclude_categories=(),
        min_close_hours=0.0,
        min_volume=0,
        min_open_interest=0,
        series=(),
        categories=(),
        exclude_categories=(),
        interval=0.002,
        output_dir=output_dir,
        max_levels=0,
        dry_run=False,
        discover_only=False,
        once=False,
        duration_seconds=0.0,
        heartbeat_seconds=999,
        discovery_refresh_seconds=999,
        log_level="CRITICAL",
        status_check_seconds=0.0,
    )
    return replace(config, **changes)


def capture(
    exchange: Exchange,
    output_dir: Path,
    until: Callable[[Exchange], bool] | None = None,
    steps: tuple[tuple[Callable[[Exchange], bool], Callable[[Exchange], None]], ...] = (),
    **changes: Any,
) -> None:
    """Run capture, applying each step when its condition holds, until `until` holds or capture stops itself."""
    pending = list(steps)
    deadline = time.monotonic() + 10
    timed_out = False

    def should_stop() -> bool:
        nonlocal timed_out
        timed_out = time.monotonic() > deadline
        while pending and pending[0][0](exchange):
            pending.pop(0)[1](exchange)
        return timed_out or (not pending and until is not None and until(exchange))

    run_capture(capture_config(output_dir, **changes), exchange, should_stop)
    if timed_out:
        raise ScenarioTimeout("capture neither stopped nor reached the expected state")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def gap_events(output_dir: Path) -> list[str]:
    return [row["event_type"] for row in read_csv(output_dir / "gaps.csv")]


def run_errors(output_dir: Path) -> int:
    return json.loads((output_dir / "run_summary.json").read_text())["errors"]


@contextlib.contextmanager
def network(handler: Callable[[httpx.Request], httpx.Response]):
    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    with mock.patch.object(httpx, "Client", lambda **options: real_client(transport=transport, **options)):
        yield


def run_cli(work_dir: Path, exchange: Exchange, argv: list[str]) -> tuple[int, list[httpx.Request]]:
    """Run the real CLI, client, and signing with only the network replaced."""
    key_path = work_dir / "ephemeral-test-key"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path.removeprefix("/trade-api/v2")
        params = request.url.params.multi_items()
        try:
            return httpx.Response(200, json=exchange.get(path, params))
        except httpx.HTTPStatusError as exc:
            return httpx.Response(exc.response.status_code, json={})

    environ = {"KALSHI_KEY_ID": "test-key-id", "KALSHI_PRIVATE_KEY_PATH": str(key_path)}
    handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
    try:
        with mock.patch.dict(os.environ, environ), network(handle):
            return main.main(argv), requests
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
