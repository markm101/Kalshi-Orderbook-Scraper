import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest import mock

from kalshi_capture.config import load_config
from tests.support import CaptureTestCase, Exchange, gap_events, known_bug, market, read_csv, run_cli

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS = {"KALSHI_KEY_ID": "test-key-id", "KALSHI_PRIVATE_KEY_PATH": "/unused"}


class CliTest(CaptureTestCase):
    def test_capture_sends_only_signed_gets_to_market_data_paths(self):
        out = self.output_dir / "out"
        argv = ["--tickers", "A", "--output-dir", str(out), "--once", "--log-level", "CRITICAL"]
        code, requests = run_cli(self.output_dir, Exchange(market("A")), argv)
        self.assertEqual(code, 0)
        self.assertTrue(read_csv(out / "orderbooks" / "A.csv"))
        for request in requests:
            self.assertEqual(request.method, "GET")
            self.assertRegex(request.url.path, r"^/trade-api/v2/(markets|series)")
            self.assertIn("KALSHI-ACCESS-SIGNATURE", request.headers)

    def test_negative_options_are_rejected(self):
        options = (
            "interval", "max-levels", "select-liquid", "liquid-scan-pages", "min-orderbook-rows", "min-top-level-size",
            "min-close-hours", "min-volume", "min-open-interest", "duration-seconds", "heartbeat-seconds",
            "discovery-refresh-seconds", "status-check-seconds",
        )
        with mock.patch.dict(os.environ, CREDENTIALS):
            for option in options:
                with self.subTest(option=option), self.assertRaises(SystemExit):
                    load_config([f"--{option}=-1"])

    def test_environment_overrides_env_file(self):
        (self.output_dir / ".env").write_text("KALSHI_KEY_ID=file\nKALSHI_PRIVATE_KEY_PATH=/from-file\n")
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.output_dir)
        with mock.patch.dict(os.environ, {"KALSHI_KEY_ID": "environment"}):
            os.environ.pop("KALSHI_PRIVATE_KEY_PATH", None)
            config = load_config([])
        self.assertEqual((config.key_id, str(config.private_key_path)), ("environment", "/from-file"))

    def test_signals_flush_every_output(self):
        child = (
            "import sys\nfrom pathlib import Path\nfrom tests.support import Exchange, market, run_cli\n"
            "raise SystemExit(run_cli(Path(sys.argv[1]), Exchange(market('A')), sys.argv[2:])[0])\n"
        )
        for signum in (signal.SIGTERM, signal.SIGINT):
            work_dir = self.output_dir / str(int(signum))
            work_dir.mkdir()
            out = work_dir / "out"
            argv = ["--tickers", "A", "--output-dir", str(out), "--interval", "0.05", "--log-level", "CRITICAL"]
            environ = {**os.environ, "PYTHONPATH": os.pathsep.join([str(PROJECT_ROOT), os.environ.get("PYTHONPATH", "")])}
            process = subprocess.Popen([sys.executable, "-c", child, str(work_dir), *argv], cwd=work_dir, env=environ)
            self.addCleanup(process.kill)
            deadline = time.monotonic() + 10
            while not (out / "latest_spread.csv").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            process.send_signal(signum)
            self.assertEqual(process.wait(10), 0)
            self.assertIn("shutdown", gap_events(out))
            self.assertTrue((out / "run_summary.json").exists() and (out / "spread_depth.csv").exists())

    @known_bug("--interval nan is accepted")
    def test_nan_interval_is_rejected(self):
        with mock.patch.dict(os.environ, CREDENTIALS), self.assertRaises(SystemExit):
            load_config(["--interval", "nan"])

    def test_unmatched_category_does_not_blank_metadata(self):
        out = self.output_dir / "out"
        exchange = Exchange(market("A"))
        common = ["--output-dir", str(out), "--log-level", "CRITICAL"]
        run_cli(self.output_dir, exchange, ["--tickers", "A", "--once", *common])
        run_cli(self.output_dir, exchange, ["--discover-only", "--categories", "sports", *common])
        self.assertTrue(read_csv(out / "metadata" / "markets.csv"))
        self.assertTrue(read_csv(out / "metadata" / "series.csv"))

    def test_discover_only_does_not_blank_metadata(self):
        out = self.output_dir / "out"
        exchange = Exchange(market("A"))
        common = ["--output-dir", str(out), "--log-level", "CRITICAL"]
        run_cli(self.output_dir, exchange, ["--tickers", "A", "--once", *common])
        run_cli(self.output_dir, exchange, ["--discover-only", "--select-liquid", "1", *common])
        self.assertTrue(read_csv(out / "metadata" / "markets.csv"))
