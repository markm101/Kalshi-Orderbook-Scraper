import base64
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
import httpx

from kalshi_capture.auth import load_private_key
from kalshi_capture.client import KalshiClient
from tests.support import CaptureTestCase, known_bug, network

BASE_URL = "https://exchange.invalid/trade-api/v2"


class ClientTest(CaptureTestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def get(self, handler, path="/x", params=None):
        with network(handler), mock.patch("time.sleep"), KalshiClient(BASE_URL, "test-key-id", self.key) as client:
            return client.get(path, params)

    def test_signature_covers_path_without_query(self):
        def handle(request):
            headers = request.headers
            message = f"{headers['KALSHI-ACCESS-TIMESTAMP']}GET/trade-api/v2/markets/orderbooks".encode()
            signature = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
            pss = padding.PSS(padding.MGF1(hashes.SHA256()), 32)
            self.key.public_key().verify(signature, message, pss, hashes.SHA256())
            return httpx.Response(200, json={"tickers": request.url.params.get_list("tickers")})

        response = self.get(handle, "/markets/orderbooks", [("tickers", "A"), ("tickers", "B")])
        self.assertEqual(response, {"tickers": ["A", "B"]})

    def test_retryable_statuses_recover(self):
        for status in (429, 500, 502, 503, 504):
            replies = [httpx.Response(status), httpx.Response(status), httpx.Response(200, json={"ok": True})]
            self.assertEqual(self.get(lambda request, replies=replies: replies.pop(0)), {"ok": True})

    def test_gives_up_after_four_attempts(self):
        attempts = []

        def handle(request):
            attempts.append(request)
            return httpx.Response(503)

        with self.assertRaises(httpx.HTTPStatusError):
            self.get(handle)
        self.assertEqual(len(attempts), 4)

    def test_timeouts_and_bad_json_are_retried(self):
        attempts = []

        def handle(request):
            attempts.append(request)
            if len(attempts) == 1:
                raise httpx.ReadTimeout("timeout", request=request)
            if len(attempts) == 2:
                return httpx.Response(200, content=b"not json")
            return httpx.Response(200, json={"ok": True})

        self.assertEqual(self.get(handle), {"ok": True})

    def test_every_retry_is_signed_again(self):
        signatures = []

        def handle(request):
            signatures.append(request.headers["KALSHI-ACCESS-SIGNATURE"])
            return httpx.Response(429 if len(signatures) < 3 else 200, json={})

        self.get(handle)
        self.assertEqual(len(set(signatures)), 3)

    def test_only_rsa_keys_load(self):
        def save(key):
            path = self.output_dir / "ephemeral-test-key"
            encoding = (serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            path.write_bytes(key.private_bytes(*encoding))
            return path

        self.assertEqual(load_private_key(save(self.key)).key_size, 2048)
        with self.assertRaises(TypeError):
            load_private_key(save(ec.generate_private_key(ec.SECP256R1())))

    @known_bug("permanent 4xx responses are retried")
    def test_permanent_client_error_is_not_retried(self):
        attempts = []

        def handle(request):
            attempts.append(request)
            return httpx.Response(404)

        with self.assertRaises(httpx.HTTPStatusError):
            self.get(handle)
        self.assertEqual(len(attempts), 1)
